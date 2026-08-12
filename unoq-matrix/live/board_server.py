#!/usr/bin/env python3
"""Live bridge: serves a web control page and streams rendered 8x13 frames to
the Uno Q over serial in real time. Flash matrix_serial_slave first.

    python3 board_server.py [--port /dev/cu.usbmodem...] [--http 8080]

Open http://localhost:8080 , upload an image, drag the sliders / pan pad, and
the LED matrix follows live."""
import sys, os, io, json, time, math, threading, base64, argparse
import numpy as np
from PIL import Image
import scipy.ndimage as ndi
import serial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAGIC = bytes([0xFE, 0xED, 0xBE, 0xEF])
DEFAULT_IMG = os.path.expanduser(
    "~/.claude/image-cache/9322520d-0903-47a3-8251-b6ef4d82fbae/1.png")

# ------------------------------------------------------------------ state
LOCK = threading.Lock()
STATE = {
    "params": {
        "invert": True, "floor": 35, "gain": 1.6, "dilation": 2,
        "vh": 0.42, "gamma": 0.8, "bright": 1.0, "fps": 15,
        "mode": "tour", "tour_speed": 1.0, "x": 0.5, "y": 0.46,
        # source: "image" pans an uploaded picture; "kaleido" = procedural
        "source": "kaleido", "pattern": "spin", "kspeed": 1.0,
        "ksegments": 6, "kscale": 1.0,
    },
    "src": None, "W": 0, "H": 0,
    "frame": [0]*104, "acks": 0, "aps": 0.0, "connected": False,
}

TOUR = [(0.50,0.46),(0.36,0.44),(0.34,0.16),(0.70,0.17),
        (0.63,0.42),(0.50,0.60),(0.48,0.82),(0.50,0.46)]

def process_image(pil, p):
    g = np.asarray(pil.convert("L"), dtype=np.uint8)
    if p["invert"]:
        g = 255 - g
    g = np.clip((g.astype(float) - p["floor"]) * p["gain"], 0, 255).astype(np.uint8)
    if p["dilation"] > 0:
        g = ndi.grey_dilation(g, size=int(p["dilation"]))
    return g

def set_image(pil):
    with LOCK:
        p = STATE["params"]
        src = process_image(pil, p)
        STATE["src"] = src; STATE["H"], STATE["W"] = src.shape

def reprocess(orig_pil):
    if orig_pil is not None:
        set_image(orig_pil)

def maxpool_8x13(crop):
    ch, cw = crop.shape
    out = np.zeros((8,13))
    for r in range(8):
        y0,y1 = r*ch//8,(r+1)*ch//8
        for c in range(13):
            x0,x1 = c*cw//13,(c+1)*cw//13
            out[r,c] = crop[y0:max(y1,y0+1), x0:max(x1,x0+1)].max()
    return out

def tour_point(phase):
    n = len(TOUR)-1
    leg = int(phase) % n
    t = phase - int(phase)
    t = 0.5-0.5*math.cos(math.pi*t)
    a,b = TOUR[leg], TOUR[leg+1]
    return (a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t)

def render(src, W, H, cx, cy, vh, gamma, bright):
    VH = max(8, int(H*vh)); VW = max(13, int(round(VH*13/8)))
    x0 = int(min(max(cx-VW/2, 0), max(0, W-VW)))
    y0 = int(min(max(cy-VH/2, 0), max(0, H-VH)))
    crop = src[y0:y0+VH, x0:x0+VW].astype(float)
    if crop.size == 0: return [0]*104
    grid = maxpool_8x13(crop)
    hi = grid.max() or 1
    grid = np.clip((grid/hi)**gamma * 255 * bright, 0, 255).astype(np.uint8)
    return [int(v) for v in grid.flatten()]

# --- kaleidoscope: procedural symmetric patterns on the 8x13 grid ----------
KX, KY = np.meshgrid(np.arange(13.0), np.arange(8.0))   # KX=col, KY=row
def kaleido(pattern, t, p):
    x = KX - 6.0; y = KY - 3.5                # centered
    fx = np.abs(x); fy = np.abs(y)            # mirror both axes
    r = np.hypot(x, y) * p.get("kscale", 1.0)
    ang = np.arctan2(y, x)
    seg = max(2, int(p.get("ksegments", 6)))
    w = 2*math.pi/seg
    wedge = np.abs((np.mod(ang + math.pi, w)) - w/2)     # fold angle into a wedge
    if pattern == "rings":
        v = 0.5 + 0.5*np.sin(r*1.4 - t*3)
    elif pattern == "diamond":
        v = 0.5 + 0.5*np.sin((fx+fy)*1.05*p.get("kscale",1.0) - t*3)
    elif pattern == "rays":
        v = 0.5 + 0.5*np.sin(wedge*seg*1.5 + t*2)
    elif pattern == "spin":
        v = 0.5 + 0.5*np.sin(r*1.5 - t*2 + wedge*4)
    elif pattern == "star":
        v = np.clip(0.5 + 0.5*np.sin(r*1.2 - t*2)*np.cos(wedge*seg), 0, 1)
    elif pattern == "grid":
        v = 0.5 + 0.25*(np.sin(fx*1.3 - t*2) + np.sin(fy*1.3 + t*2))
    else:  # plasma
        s = p.get("kscale", 1.0)
        v = (np.sin(fx*0.8*s + t) + np.sin(fy*1.1*s - t)
             + np.sin((fx+fy)*0.6*s + t*0.7)) / 3.0
        v = 0.5 + 0.5*v
    g = np.clip(v**p.get("gamma",0.8) * 255 * p.get("bright",1.0), 0, 255).astype(np.uint8)
    return [int(u) for u in g.flatten()]

# ------------------------------------------------------------------ streamer
class Streamer(threading.Thread):
    def __init__(self, ser):
        super().__init__(daemon=True); self.ser=ser; self.phase=0.0; self.tt=0.0
        self.ack_t0=time.time(); self.ack_n=0
    def run(self):
        while True:
            with LOCK:
                p = dict(STATE["params"]); src=STATE["src"]; W=STATE["W"]; H=STATE["H"]
            fps = max(2, min(30, p["fps"]))
            frame = None
            if p.get("source") == "kaleido":
                self.tt += p.get("kspeed",1.0)/fps*2.0
                frame = kaleido(p.get("pattern","spin"), self.tt, p)
            elif src is not None:
                if p["mode"] == "manual":
                    cx,cy = p["x"]*W, p["y"]*H
                else:
                    self.phase = (self.phase + p["tour_speed"]/fps*0.7) % (len(TOUR)-1)
                    fx,fy = tour_point(self.phase); cx,cy = fx*W, fy*H
                frame = render(src, W, H, cx, cy, p["vh"], p["gamma"], p["bright"])
            if frame is not None:
                try:
                    self.ser.write(MAGIC + bytes(frame)); self.ser.flush()
                except Exception:
                    pass
                with LOCK: STATE["frame"]=frame
                # drain acks
                try:
                    r=self.ser.read(self.ser.in_waiting or 0)
                    self.ack_n += r.count(b'K')
                except Exception:
                    pass
                if time.time()-self.ack_t0 >= 1.0:
                    with LOCK:
                        STATE["aps"]=self.ack_n/(time.time()-self.ack_t0)
                        STATE["connected"]=STATE["aps"]>0.5; STATE["acks"]+=self.ack_n
                    self.ack_n=0; self.ack_t0=time.time()
            time.sleep(1.0/fps)

# ------------------------------------------------------------------ http
ORIG_PIL = {"img": None}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body,str) else body
        self.send_response(code); self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE, "text/html")
        elif self.path == "/frame":
            with LOCK:
                self._send(200, json.dumps({"frame":STATE["frame"],
                    "aps":round(STATE["aps"],1),"connected":STATE["connected"],
                    "has_img":STATE["src"] is not None,"params":STATE["params"]}))
        else:
            self._send(404, "{}")
    def do_POST(self):
        n=int(self.headers.get("Content-Length",0)); raw=self.rfile.read(n)
        if self.path == "/params":
            try:
                upd=json.loads(raw)
                with LOCK: STATE["params"].update(upd)
                # reprocess if image-processing params changed
                if any(k in upd for k in ("invert","floor","gain","dilation")):
                    reprocess(ORIG_PIL["img"])
                self._send(200,'{"ok":true}')
            except Exception as e:
                self._send(400, json.dumps({"err":str(e)}))
        elif self.path == "/upload":
            try:
                data=json.loads(raw)["png"]
                if "," in data: data=data.split(",",1)[1]
                pil=Image.open(io.BytesIO(base64.b64decode(data)))
                ORIG_PIL["img"]=pil.copy(); set_image(pil)
                with LOCK: W,Hh=STATE["W"],STATE["H"]
                self._send(200, json.dumps({"ok":True,"w":W,"h":Hh}))
            except Exception as e:
                self._send(400, json.dumps({"err":str(e)}))
        else:
            self._send(404,"{}")

# ------------------------------------------------------------------ page
PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Uno Q Matrix Live</title><style>
:root{color-scheme:dark}
body{margin:0;background:#0b0d12;color:#e6e9ef;font:14px/1.4 system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:18px}
h1{font-size:18px;margin:0 0 4px}.sub{color:#8b93a3;margin:0 0 16px;font-size:12px}
.grid{display:grid;grid-template-columns:360px 1fr;gap:22px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
canvas{background:#05060a;border-radius:10px;width:100%;touch-action:none;cursor:crosshair}
.card{background:#12151d;border:1px solid #222836;border-radius:10px;padding:14px}
.row{display:flex;align-items:center;gap:10px;margin:10px 0}
.row label{width:96px;color:#aab2c4;font-size:12px}
.row input[type=range]{flex:1}
.val{width:44px;text-align:right;color:#7fd1ff;font-variant-numeric:tabular-nums}
button,.file{background:#1b2230;border:1px solid #2c3547;color:#dfe5f0;
  padding:9px 12px;border-radius:8px;cursor:pointer;font-size:13px}
button:hover,.file:hover{background:#232c3d}
.seg{display:inline-flex;border:1px solid #2c3547;border-radius:8px;overflow:hidden}
.seg button{border:0;border-radius:0;background:#141a25}
.seg button.on{background:#2563eb;color:#fff}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#e5484d;margin-right:6px}
.dot.ok{background:#30d158}
.hint{color:#8b93a3;font-size:11px;margin-top:6px}
input[type=file]{display:none}
</style></head><body><div class=wrap>
<h1>Uno Q · Matrix Live</h1>
<p class=sub><span id=stat class=dot></span><span id=statt>connecting…</span> · drag on the preview to pan (Manual mode)</p>
<div class=grid>
 <div>
  <canvas id=cv width=390 height=240></canvas>
  <div class=hint>Live preview mirrors the board (8×13).</div>
 </div>
 <div class=card>
  <div class=row>
   <label>Source</label>
   <span class=seg><button id=skal class=on>Kaleidoscope</button><button id=simg>Image</button></span>
  </div>
  <div id=ksec>
   <div class=row><label>Pattern</label>
    <span class=seg id=patseg>
     <button data-p=spin class=on>Spin</button><button data-p=rings>Rings</button><button data-p=star>Star</button>
     <button data-p=rays>Rays</button><button data-p=diamond>Diamond</button><button data-p=grid>Grid</button><button data-p=plasma>Plasma</button>
    </span></div>
   <div class=row><label>Speed</label><input id=ksp type=range min=0 max=3 step=0.05><span class=val id=kspv></span></div>
   <div class=row><label>Segments</label><input id=kseg type=range min=2 max=12 step=1><span class=val id=ksegv></span></div>
   <div class=row><label>Scale</label><input id=ksc type=range min=0.4 max=2.5 step=0.05><span class=val id=kscv></span></div>
  </div>
  <div id=imgsec style=display:none>
   <div class=row><label>Image</label><label class=file>Upload…<input id=file type=file accept="image/*"></label><span class=hint id=imgs></span></div>
   <div class=row><label>Mode</label><span class=seg><button id=mtour class=on>Tour</button><button id=mman>Manual</button></span></div>
   <div class=row><label>Zoom</label><input id=vh type=range min=0.20 max=0.80 step=0.01><span class=val id=vhv></span></div>
   <div class=row id=rspeed><label>Tour speed</label><input id=spd type=range min=0.2 max=3 step=0.1><span class=val id=spdv></span></div>
   <div class=row id=rx style=display:none><label>Pan X</label><input id=px type=range min=0 max=1 step=0.005><span class=val id=pxv></span></div>
   <div class=row id=ry style=display:none><label>Pan Y</label><input id=py type=range min=0 max=1 step=0.005><span class=val id=pyv></span></div>
   <div class=row><label>Line width</label><input id=dil type=range min=0 max=4 step=1><span class=val id=dilv></span></div>
   <div class=row><label>Invert</label><input id=inv type=checkbox checked><span class=hint>dark lines → lit</span></div>
  </div>
  <div class=row><label>Brightness</label><input id=br type=range min=0.2 max=1.5 step=0.05><span class=val id=brv></span></div>
  <div class=row><label>Contrast γ</label><input id=gm type=range min=0.4 max=1.6 step=0.05><span class=val id=gmv></span></div>
  <div class=row><label>FPS</label><input id=fps type=range min=4 max=30 step=1><span class=val id=fpsv></span></div>
 </div>
</div></div>
<script>
const $=s=>document.querySelector(s);
let P={};
function post(url,obj){return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)})}
let pt=null;
function pushParams(){post('/params',P)}
function bindSlider(id,key,valel,fmt){const el=$('#'+id);el.oninput=()=>{P[key]=parseFloat(el.value);$(valel).textContent=(fmt||(x=>x))(el.value);clearTimeout(pt);pt=setTimeout(pushParams,25)}}
bindSlider('vh','vh','#vhv');bindSlider('spd','tour_speed','#spdv');
bindSlider('px','x','#pxv');bindSlider('py','y','#pyv');
bindSlider('dil','dilation','#dilv');bindSlider('br','bright','#brv');
bindSlider('gm','gamma','#gmv');bindSlider('fps','fps','#fpsv');
bindSlider('ksp','kspeed','#kspv');bindSlider('kseg','ksegments','#ksegv');bindSlider('ksc','kscale','#kscv');
$('#inv').onchange=()=>{P.invert=$('#inv').checked;pushParams()}
function setSource(s){P.source=s;$('#skal').classList.toggle('on',s=='kaleido');$('#simg').classList.toggle('on',s=='image');
  $('#ksec').style.display=s=='kaleido'?'':'none';$('#imgsec').style.display=s=='image'?'':'none';pushParams()}
$('#skal').onclick=()=>setSource('kaleido');$('#simg').onclick=()=>setSource('image');
document.querySelectorAll('#patseg button').forEach(b=>b.onclick=()=>{P.pattern=b.dataset.p;
  document.querySelectorAll('#patseg button').forEach(x=>x.classList.toggle('on',x==b));pushParams()});
function setMode(m){P.mode=m;$('#mtour').classList.toggle('on',m=='tour');$('#mman').classList.toggle('on',m=='manual');
  $('#rspeed').style.display=m=='tour'?'':'none';$('#rx').style.display=m=='manual'?'':'none';$('#ry').style.display=m=='manual'?'':'none';pushParams()}
$('#mtour').onclick=()=>setMode('tour');$('#mman').onclick=()=>setMode('manual');
$('#file').onchange=e=>{const f=e.target.files[0];if(!f)return;const r=new FileReader();
  r.onload=()=>{post('/upload',{png:r.result}).then(x=>x.json()).then(j=>{$('#imgs').textContent=j.ok?(j.w+'×'+j.h):'err'})};r.readAsDataURL(f)}
// preview + pan pad
const cv=$('#cv'),cx=cv.getContext('2d');
function draw(fr){const W=cv.width,H=cv.height,cols=13,rows=8;cx.fillStyle='#05060a';cx.fillRect(0,0,W,H);
  const cw=W/cols,ch=H/rows,r=Math.min(cw,ch)*0.42;
  for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){const v=fr[y*cols+x]/255;const px=x*cw+cw/2,py=y*ch+ch/2;
    cx.beginPath();cx.arc(px,py,r,0,7);cx.fillStyle='rgba(30,36,48,1)';cx.fill();
    if(v>0.02){cx.beginPath();cx.arc(px,py,r,0,7);cx.fillStyle='rgba('+Math.round(70*v)+','+Math.round(150*v)+','+Math.round(255*v)+',1)';cx.fill();}}}
function panFromEvent(e){if(P.source!=='image')return;const rect=cv.getBoundingClientRect();const t=e.touches?e.touches[0]:e;
  P.x=Math.min(1,Math.max(0,(t.clientX-rect.left)/rect.width));P.y=Math.min(1,Math.max(0,(t.clientY-rect.top)/rect.height));
  $('#px').value=P.x;$('#py').value=P.y;$('#pxv').textContent=P.x.toFixed(2);$('#pyv').textContent=P.y.toFixed(2);
  if(P.mode!=='manual')setMode('manual');clearTimeout(pt);pt=setTimeout(pushParams,25)}
let down=false;
cv.addEventListener('pointerdown',e=>{down=true;panFromEvent(e)});
cv.addEventListener('pointermove',e=>{if(down)panFromEvent(e)});
addEventListener('pointerup',()=>down=false);
// init from server
function initUI(p){P=Object.assign({},p);
  $('#vh').value=p.vh;$('#vhv').textContent=p.vh;$('#spd').value=p.tour_speed;$('#spdv').textContent=p.tour_speed;
  $('#px').value=p.x;$('#pxv').textContent=p.x;$('#py').value=p.y;$('#pyv').textContent=p.y;
  $('#dil').value=p.dilation;$('#dilv').textContent=p.dilation;$('#br').value=p.bright;$('#brv').textContent=p.bright;
  $('#gm').value=p.gamma;$('#gmv').textContent=p.gamma;$('#fps').value=p.fps;$('#fpsv').textContent=p.fps;
  $('#ksp').value=p.kspeed;$('#kspv').textContent=p.kspeed;$('#kseg').value=p.ksegments;$('#ksegv').textContent=p.ksegments;
  $('#ksc').value=p.kscale;$('#kscv').textContent=p.kscale;
  document.querySelectorAll('#patseg button').forEach(x=>x.classList.toggle('on',x.dataset.p==p.pattern));
  $('#inv').checked=p.invert;setMode(p.mode);setSource(p.source||'kaleido')}
let inited=false;
async function tick(){try{const j=await(await fetch('/frame')).json();
  if(!inited){initUI(j.params);inited=true}
  draw(j.frame);$('#stat').classList.toggle('ok',j.connected);
  $('#statt').textContent=(j.connected?'board live · '+(P.source||'kaleido'):'board idle');
 }catch(e){$('#statt').textContent='server offline'}}
setInterval(tick,66);tick();
</script></body></html>"""

# ------------------------------------------------------------------ main
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem19841116482")
    ap.add_argument("--http", type=int, default=8080)
    a=ap.parse_args()
    print("opening serial", a.port, "…"); sys.stdout.flush()
    ser=serial.Serial(a.port, 115200, timeout=0.05, dsrdtr=True); ser.dtr=True
    time.sleep(3.0); ser.reset_input_buffer()   # wait for board reset+boot
    print("serial ready.")
    # default image
    try:
        if os.path.exists(DEFAULT_IMG):
            pil=Image.open(DEFAULT_IMG); ORIG_PIL["img"]=pil.copy(); set_image(pil)
            print("loaded default image", STATE["W"],"x",STATE["H"])
    except Exception as e:
        print("no default image:", e)
    Streamer(ser).start()
    srv=ThreadingHTTPServer(("127.0.0.1", a.http), H)
    print("\n  >>> open  http://localhost:%d  <<<\n" % a.http); sys.stdout.flush()
    srv.serve_forever()

if __name__=="__main__":
    main()
