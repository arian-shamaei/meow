#!/usr/bin/env python3
"""Live kaleidoscope control for the Uno Q 8x13 matrix.

Architecture (this is the fix for "web page != board"):
  The MCU renders the kaleidoscope itself at ~60fps. We only send a few
  parameter bytes. Streaming 104-byte frames could never exceed ~1.6 fps on
  this core (Serial.read() costs ~6ms/BYTE), so the panel used to display
  frames many seconds stale. Now the board is authoritative and instant.

  Reactive (sensor) packets are fire-and-forget at ~10Hz -- measured working;
  waiting for acks is what was slow (~670ms), not the writes.

Run:  python3 kaleido_server.py            then open http://localhost:8080
Flash kaleido_fw/ to the board first.
"""
import sys, os, io, json, time, math, threading, base64, argparse, subprocess, struct, re
import serial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
STATE = {
    "params": {"pattern": 0, "speed": 120, "segments": 6, "scale": 85,
               "bright": 170, "gamma": 85, "react": 0, "flags": 0},
    "reactive_source": "none",     # none | audio | cpu
    "audio_device": 1,             # avfoundation audio index
    "level": 0,                    # 0..255 current reactive level
    "connected": False, "last_hb": 0.0, "board_lvl": 0,
    "board_temp": 0.0, "board_vdda": 0.0, "flags": 0,
    "text": "", "board_n": 0, "pending_text": None, "board_saved": 0,
}
PATTERNS = ["spin", "rings", "star", "rays", "diamond", "grid", "plasma"]

# ---------------------------------------------------------------- serial
class Link(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.ser = serial.Serial(port, 115200, timeout=0.1, dsrdtr=True)
        self.ser.dtr = True
        time.sleep(3.5)                     # board resets on open; wait for boot
        self.ser.reset_input_buffer()
        self.dirty = True                   # send params on start
        self.buf = b""

    def send_params(self):
        with LOCK: p = dict(STATE["params"])
        pl = bytes([p["pattern"] & 0xFF, p["speed"] & 0xFF, p["segments"] & 0xFF,
                    p["scale"] & 0xFF, p["bright"] & 0xFF, p["gamma"] & 0xFF,
                    p["react"] & 0xFF, STATE["params"].get("flags",0) & 0xFF])
        try:
            self.ser.write(bytes([0xA5]) + pl + bytes([sum(pl) & 0xFF]))
            self.ser.flush()
        except Exception:
            pass

    def send_save(self, forget=False):
        try:
            self.ser.write(bytes([0xAB if forget else 0xAA, 0x00])); self.ser.flush()
        except Exception:
            pass

    def send_reactive(self, lvl, bass=0):
        pl = bytes([max(0, min(255, int(lvl))), max(0, min(255, int(bass)))])
        try:
            self.ser.write(bytes([0xA6]) + pl + bytes([sum(pl) & 0xFF]))
            self.ser.flush()
        except Exception:
            pass

    def send_text(self, txt):
        data = txt.encode("ascii", "replace")[:1400]
        self.ser.write(bytes([0xA9, 0x00])); self.ser.flush()   # clear
        time.sleep(0.25)
        for i in range(0, len(data), 32):
            ch = data[i:i+32]
            pl = bytes([len(ch)]) + ch
            self.ser.write(bytes([0xA7]) + pl + bytes([sum(pl) & 0xFF]))
            self.ser.flush()
            time.sleep(0.30)          # ~6ms/byte on this core
        # commit: swap staging into the live buffer atomically, so the
        # scrolling text is never rebuilt underneath itself mid-upload
        self.ser.write(bytes([0xA8, 0x00])); self.ser.flush()
        time.sleep(0.1)
        self.dirty = True

    def run(self):
        last_react = 0.0
        while True:
            with LOCK:
                pend = STATE["pending_text"]; STATE["pending_text"] = None
            if pend is not None:
                self.send_text(pend)
            with LOCK:
                sv = STATE.pop("pending_save", None)
            if sv is not None:
                self.send_save(forget=(sv == "forget"))
            if self.dirty:
                self.dirty = False
                self.send_params()
                time.sleep(0.05)
            now = time.time()
            with LOCK:
                src = STATE["reactive_source"]; lvl = STATE["level"]
            if src != "none" and now - last_react >= 0.1:      # 10 Hz
                last_react = now
                self.send_reactive(lvl)
            # read heartbeat ("KFW lvl=N")
            try:
                r = self.ser.read(256)
                if r:
                    self.buf += r
                    if len(self.buf) > 2048: self.buf = self.buf[-512:]
                    if b"KFW" in self.buf:
                        txt = self.buf.decode(errors="replace")
                        i = txt.rfind("lvl=")
                        with LOCK:
                            STATE["last_hb"] = now
                            if i >= 0:
                                num = ""
                                for c in txt[i+4:]:
                                    if c.isdigit(): num += c
                                    else: break
                                if num: STATE["board_lvl"] = int(num)
                            mt = re.search(r"t=(-?[\d.]+)", txt)
                            mv = re.search(r"v=(-?[\d.]+)", txt)
                            if mt: STATE["board_temp"] = float(mt.group(1))
                            if mv: STATE["board_vdda"] = float(mv.group(1))
                            mn = re.search(r"n=(\d+)", txt)
                            if mn: STATE["board_n"] = int(mn.group(1))
                            ms = re.search(r"saved=(\d+)", txt)
                            if ms: STATE["board_saved"] = int(ms.group(1))
                        self.buf = b""
            except Exception:
                pass
            with LOCK:
                STATE["connected"] = (time.time() - STATE["last_hb"]) < 3.0
            time.sleep(0.02)

LINK = None

# ---------------------------------------------------------------- sensors
class Audio(threading.Thread):
    """Mic / system-audio level via ffmpeg avfoundation -> 0..255, smoothed."""
    def __init__(self):
        super().__init__(daemon=True); self.proc = None; self.dev = None
        self.env = 0.0; self.peak = 500.0
    def stop(self):
        if self.proc:
            try: self.proc.kill()
            except Exception: pass
            self.proc = None
    def run(self):
        while True:
            with LOCK:
                want = STATE["reactive_source"] == "audio"
                dev = STATE["audio_device"]
            if not want:
                self.stop(); time.sleep(0.2); continue
            if self.proc is None or self.dev != dev:
                self.stop(); self.dev = dev
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "quiet",
                       "-f", "avfoundation", "-i", ":%d" % dev,
                       "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
                try:
                    self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                                 stderr=subprocess.DEVNULL)
                except Exception:
                    self.proc = None; time.sleep(1.0); continue
            try:
                raw = self.proc.stdout.read(1600)      # 0.1s @ 8kHz mono
                if not raw:
                    self.stop(); time.sleep(0.3); continue
                n = len(raw) // 2
                vals = struct.unpack("<%dh" % n, raw[:n*2])
                rms = math.sqrt(sum(v*v for v in vals) / max(1, n))
                self.peak = max(rms, self.peak * 0.995, 200.0)   # auto-gain
                t = min(1.0, rms / self.peak)
                self.env = max(t, self.env * 0.72)               # fast attack, decay
                with LOCK: STATE["level"] = int(self.env * 255)
            except Exception:
                self.stop(); time.sleep(0.3)

class CpuLoad(threading.Thread):
    def run(self):
        while True:
            with LOCK: want = STATE["reactive_source"] == "cpu"
            if want:
                try:
                    la = os.getloadavg()[0]
                    with LOCK:
                        STATE["level"] = int(max(0, min(255, la / 8.0 * 255)))
                except Exception: pass
            time.sleep(0.5)
    def __init__(self): super().__init__(daemon=True)

# ---------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE, "text/html")
        elif self.path == "/state":
            with LOCK:
                self._send(200, json.dumps({
                    "params": STATE["params"], "connected": STATE["connected"],
                    "level": STATE["level"], "board_lvl": STATE["board_lvl"],
                    "reactive_source": STATE["reactive_source"],
                    "audio_device": STATE["audio_device"],
                    "board_temp": STATE["board_temp"], "board_vdda": STATE["board_vdda"],
                    "board_n": STATE["board_n"], "text": STATE["text"],
                    "board_saved": STATE["board_saved"]}))
        else:
            self._send(404, "{}")
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            upd = json.loads(raw)
        except Exception:
            return self._send(400, '{"err":"bad json"}')
        if "save" in upd:
            with LOCK: STATE["pending_save"] = upd["save"]
        if "text" in upd:
            with LOCK:
                STATE["text"] = str(upd["text"])[:1400]
                STATE["pending_text"] = STATE["text"]
        with LOCK:
            for k in ("pattern","speed","segments","scale","bright","gamma","react","flags"):
                if k in upd: STATE["params"][k] = int(upd[k])
            if "reactive_source" in upd: STATE["reactive_source"] = upd["reactive_source"]
            if "audio_device" in upd: STATE["audio_device"] = int(upd["audio_device"])
            if STATE["reactive_source"] == "none": STATE["level"] = 0
        if LINK: LINK.dirty = True
        self._send(200, '{"ok":true}')

# ---------------------------------------------------------------- page
PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Uno Q · Kaleidoscope</title><style>
:root{color-scheme:dark}
body{margin:0;background:#0b0d12;color:#e6e9ef;font:14px/1.45 system-ui,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:18px}
h1{font-size:18px;margin:0 0 2px}.sub{color:#8b93a3;margin:0 0 16px;font-size:12px}
.grid{display:grid;grid-template-columns:400px 1fr;gap:22px}
@media(max-width:780px){.grid{grid-template-columns:1fr}}
canvas{background:#05060a;border-radius:10px;width:100%}
.card{background:#12151d;border:1px solid #222836;border-radius:10px;padding:14px}
.row{display:flex;align-items:center;gap:10px;margin:9px 0}
.row label{width:92px;color:#aab2c4;font-size:12px}
.row input[type=range]{flex:1}
.val{width:42px;text-align:right;color:#7fd1ff;font-variant-numeric:tabular-nums}
button{background:#1b2230;border:1px solid #2c3547;color:#dfe5f0;padding:7px 10px;
  border-radius:8px;cursor:pointer;font-size:12px}
button:hover{background:#232c3d}
.seg{display:inline-flex;flex-wrap:wrap;gap:4px}
.seg button.on{background:#2563eb;border-color:#2563eb;color:#fff}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#e5484d;margin-right:6px}
.dot.ok{background:#30d158}
.meter{height:8px;background:#1b2230;border-radius:5px;overflow:hidden;flex:1}
.meter i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#7fd1ff);width:0}
.hint{color:#8b93a3;font-size:11px}
</style></head><body><div class=wrap>
<h1>Uno Q · Kaleidoscope</h1>
<p class=sub><span id=stat class=dot></span><span id=statt>connecting…</span>
 · rendered on the board at 60fps — the page sends parameters only</p>
<div class=grid>
 <div>
  <canvas id=cv width=400 height=246></canvas>
  <div class=hint style="margin-top:6px">Preview uses the same math as the firmware.</div>
 </div>
 <div class=card>
  <div class=row><label>Mode</label><span class=seg id=modeseg>
    <button data-m=0 class=on>Kaleidoscope</button><button data-m=1>Scrolling text</button></span></div>
  <div id=textsec style=display:none>
    <div class=row style="align-items:flex-start"><label>Text</label>
      <textarea id=txt rows=5 style="flex:1;background:#0d1017;color:#e6e9ef;border:1px solid #2c3547;
        border-radius:8px;padding:8px;font:12px/1.4 ui-monospace,monospace;resize:vertical"
        placeholder="Paste any text you like — it scrolls across the panel."></textarea></div>
    <div class=row><label></label><button id=sendtxt>Send to board</button>
      <span class=hint id=txtstat>0 chars</span></div>
  </div>
  <div id=kalsec><div class=row><label>Pattern</label><span class=seg id=patseg></span></div></div>
  <div class=row><label>Speed</label><input id=speed type=range min=0 max=255><span class=val id=speedv></span></div>
  <div class=row><label>Segments</label><input id=segments type=range min=2 max=12><span class=val id=segmentsv></span></div>
  <div class=row><label>Scale</label><input id=scale type=range min=0 max=255><span class=val id=scalev></span></div>
  <div class=row><label>Brightness</label><input id=bright type=range min=0 max=255><span class=val id=brightv></span></div>
  <div class=row><label>Contrast</label><input id=gamma type=range min=0 max=255><span class=val id=gammav></span></div>
  <hr style="border:0;border-top:1px solid #222836;margin:14px 0">
  <div class=row><label>Reactive</label><span class=seg id=srcseg>
    <button data-s=none class=on>Off</button><button data-s=audio>Audio</button><button data-s=cpu>CPU load</button><button data-s=board>Board temp</button>
  </span></div>
  <div class=row id=devrow style=display:none><label>Input</label><span class=seg id=devseg>
    <button data-d=1 class=on>Mic</button><button data-d=0>System audio</button>
  </span></div>
  <div class=row><label>Drives</label><span class=seg id=reactseg>
    <button data-b=1>Brightness</button><button data-b=2>Scale</button>
    <button data-b=4>Speed</button><button data-b=8>Segments</button>
  </span></div>
  <div class=row><label>Level</label><span class=meter><i id=lvlbar></i></span><span class=val id=lvlv>0</span></div>
  <div class=row><label>On-board</label><span class=hint id=sens>die temp — · VDDA —</span></div>
  <hr style="border:0;border-top:1px solid #222836;margin:14px 0">
  <div class=row><label>Persist</label>
    <button id=savebtn>Save to board</button><button id=forgetbtn>Forget</button>
    <span class=hint id=savestat></span></div>
  <div class=row><label></label><span class=hint>Saved settings + text reload on power-up — unplug and replug and it keeps running with no computer.</span></div>
 </div>
</div></div>
<script>
const $=s=>document.querySelector(s);
const FONT7=[0,168,0,136,0,168,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,32,32,32,32,0,32,0,80,80,80,0,0,0,0,0,80,248,80,248,80,0,0,112,160,112,40,112,0,128,144,32,64,144,16,0,0,64,160,64,160,80,0,32,32,32,0,0,0,0,32,64,64,64,64,32,0,64,32,32,32,32,64,0,0,80,32,112,32,80,0,0,32,32,248,32,32,0,0,0,0,0,48,32,64,0,0,0,240,0,0,0,0,0,0,0,96,96,0,0,16,32,64,128,0,0,32,80,80,80,80,32,0,32,96,32,32,32,112,0,96,144,16,32,64,240,0,240,16,96,16,144,96,0,32,96,160,240,32,32,0,240,128,224,16,144,96,0,96,128,224,144,144,96,0,240,16,32,32,64,64,0,96,144,96,144,144,96,0,96,144,144,112,16,96,0,0,96,96,0,96,96,0,0,96,96,0,96,64,128,0,16,32,64,32,16,0,0,0,240,0,240,0,0,0,64,32,16,32,64,0,32,80,16,32,0,32,0,96,144,176,176,128,96,0,96,144,144,240,144,144,0,224,144,224,144,144,224,0,96,144,128,128,144,96,0,224,144,144,144,144,224,0,240,128,224,128,128,240,0,240,128,224,128,128,128,0,96,144,128,176,144,112,0,144,144,240,144,144,144,0,112,32,32,32,32,112,0,16,16,16,16,144,96,0,144,160,192,192,160,144,0,128,128,128,128,128,240,0,144,240,240,144,144,144,0,144,208,208,176,176,144,0,96,144,144,144,144,96,0,224,144,144,224,128,128,0,96,144,144,144,208,96,16,224,144,144,224,160,144,0,96,144,64,32,144,96,0,112,32,32,32,32,32,0,144,144,144,144,144,96,0,144,144,144,144,96,96,0,144,144,144,240,240,144,0,144,144,96,96,144,144,0,80,80,80,32,32,32,0,240,16,32,64,128,240,0,112,64,64,64,64,112,0,0,128,64,32,16,0,0,112,16,16,16,16,112,0,32,80,0,0,0,0,0,0,0,0,0,0,240,0,64,32,0,0,0,0,0,0,0,112,144,176,80,0,128,128,224,144,144,224,0,0,0,96,128,128,96,0,16,16,112,144,144,112,0,0,0,96,176,192,96,0,32,80,64,224,64,64,0,0,0,112,144,96,128,112,128,128,224,144,144,144,0,32,0,96,32,32,112,0,16,0,16,16,16,80,32,128,128,160,192,160,144,0,96,32,32,32,32,112,0,0,0,160,240,144,144,0,0,0,224,144,144,144,0,0,0,96,144,144,96,0,0,0,224,144,144,224,128,0,0,112,144,144,112,16,0,0,224,144,128,128,0,0,0,112,192,48,224,0,64,64,224,64,64,48,0,0,0,144,144,144,112,0,0,0,80,80,80,32,0,0,0,144,144,240,240,0,0,0,144,96,96,144,0,0,0,144,144,80,32,64,0,0,240,32,64,240,0,16,32,96,32,32,16,0,32,32,32,32,32,32,0,64,32,48,32,32,64,0,80,160,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,32,0,32,32,32,32,0,0,32,112,160,160,112,32,0,48,64,224,64,176,0,0,136,112,80,112,136,0,80,80,32,112,32,32,0,0,32,32,0,32,32,0,48,64,96,80,48,16,96,80,0,0,0,0,0,0,112,136,168,200,168,136,112,96,160,96,0,0,0,0,0,0,72,144,72,0,0,0,0,0,240,16,0,0,0,0,0,112,0,0,0,112,136,232,200,200,136,112,240,0,0,0,0,0,0,32,80,32,0,0,0,0,32,32,248,32,32,248,0,96,32,64,96,0,0,0,96,96,32,96,0,0,0,32,64,0,0,0,0,0,0,0,144,144,144,224,128,112,208,208,80,80,80,0,0,0,96,96,0,0,0,0,0,0,0,0,32,64,32,96,32,112,0,0,0,64,160,64,0,0,0,0,0,0,144,72,144,0,0,128,128,128,144,48,112,16,128,128,128,176,16,32,48,192,192,64,208,48,112,16,32,0,32,64,80,32,0,96,144,144,240,144,144,0,96,144,144,240,144,144,0,96,144,144,240,144,144,0,96,144,144,240,144,144,0,144,96,144,240,144,144,0,96,96,144,240,144,144,0,112,160,176,224,160,176,0,96,144,128,128,144,96,64,240,128,224,128,128,240,0,240,128,224,128,128,240,0,240,128,224,128,128,240,0,240,128,224,128,128,240,0,112,32,32,32,32,112,0,112,32,32,32,32,112,0,112,32,32,32,32,112,0,112,32,32,32,32,112,0,224,80,208,80,80,224,0,176,144,208,176,176,144,0,96,144,144,144,144,96,0,96,144,144,144,144,96,0,96,144,144,144,144,96,0,96,144,144,144,144,96,0,144,96,144,144,144,96,0,0,0,144,96,96,144,0,112,176,176,208,208,224,0,144,144,144,144,144,96,0,144,144,144,144,144,96,0,144,144,144,144,144,96,0,144,0,144,144,144,96,0,80,80,80,32,32,32,0,128,224,144,224,128,128,0,96,144,160,144,144,160,0,64,32,112,144,176,80,0,32,64,112,144,176,80,0,32,80,112,144,176,80,0,80,160,112,144,176,80,0,80,0,112,144,176,80,0,96,96,112,144,176,80,0,0,0,112,176,160,112,0,0,0,48,64,64,48,32,64,32,96,176,192,96,0,32,64,96,176,192,96,0,64,160,96,176,192,96,0,160,0,96,176,192,96,0,64,32,96,32,32,112,0,32,64,96,32,32,112,0,32,80,96,32,32,112,0,80,0,96,32,32,112,0,64,48,96,144,144,96,0,80,160,224,144,144,144,0,64,32,96,144,144,96,0,32,64,96,144,144,96,0,96,0,96,144,144,96,0,80,160,96,144,144,96,0,80,0,96,144,144,96,0,0,96,0,240,0,96,0,0,0,112,176,208,224,0,64,32,144,144,144,112,0,32,64,144,144,144,112,0,96,0,144,144,144,112,0,80,0,144,144,144,112,0,32,64,144,144,80,32,64,0,128,224,144,144,224,128];const FONTN=255;
let MODE=0, TXT='', scrollx=0;
const PATS=["spin","rings","star","rays","diamond","grid","plasma"];
let P={pattern:0,speed:120,segments:6,scale:85,bright:170,gamma:85,react:0};
let SRC="none", DEV=1, LEVEL=0, pt=null;
function post(o){clearTimeout(pt);pt=setTimeout(()=>fetch('/params',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}),20)}
// pattern buttons
PATS.forEach((n,i)=>{const b=document.createElement('button');b.textContent=n;b.dataset.p=i;
  b.onclick=()=>{P.pattern=i;syncPat();post({pattern:i})};$('#patseg').appendChild(b)});
function syncPat(){document.querySelectorAll('#patseg button').forEach(b=>b.classList.toggle('on',+b.dataset.p===P.pattern))}
['speed','segments','scale','bright','gamma'].forEach(k=>{const el=$('#'+k);
  el.oninput=()=>{P[k]=+el.value;$('#'+k+'v').textContent=el.value;post({[k]:P[k]})}});
document.querySelectorAll('#modeseg button').forEach(b=>b.onclick=()=>{MODE=+b.dataset.m;
  document.querySelectorAll('#modeseg button').forEach(x=>x.classList.toggle('on',x===b));
  $('#textsec').style.display=MODE?'':'none';$('#kalsec').style.display=MODE?'none':'';
  P.flags=(P.flags&~2)|(MODE?2:0);post({flags:P.flags})});
$('#savebtn').onclick=()=>{$('#savestat').textContent='saving…';
  fetch('/params',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({save:'save'})})};
$('#forgetbtn').onclick=()=>{$('#savestat').textContent='clearing…';
  fetch('/params',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({save:'forget'})})};
$('#txt').addEventListener('input',()=>$('#txtstat').textContent=$('#txt').value.length+' chars');
$('#sendtxt').onclick=()=>{TXT=$('#txt').value;scrollx=0;
  $('#txtstat').textContent='sending '+TXT.length+' chars…';
  fetch('/text',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:TXT,flags:(P.flags|2)})}).then(()=>{P.flags|=2;
    $('#txtstat').textContent=TXT.length+' chars sent'})};
document.querySelectorAll('#srcseg button').forEach(b=>b.onclick=()=>{SRC=b.dataset.s;
  document.querySelectorAll('#srcseg button').forEach(x=>x.classList.toggle('on',x===b));
  $('#devrow').style.display=SRC==='audio'?'':'none';
  P.flags=(SRC==='board')?1:0;
  post({reactive_source:(SRC==='board'?'none':SRC),flags:P.flags})});
document.querySelectorAll('#devseg button').forEach(b=>b.onclick=()=>{DEV=+b.dataset.d;
  document.querySelectorAll('#devseg button').forEach(x=>x.classList.toggle('on',x===b));post({audio_device:DEV})});
document.querySelectorAll('#reactseg button').forEach(b=>b.onclick=()=>{const bit=+b.dataset.b;
  P.react^=bit;b.classList.toggle('on',(P.react&bit)!==0);post({react:P.react})});
// ---- preview: same formulas as kaleido_fw.ino ----
const cv=$('#cv'),cx=cv.getContext('2d');let phase=0,last=performance.now();
function u8f(v,lo,hi){return lo+(hi-lo)*(v/255)}
function gpow(v,g){if(v<=0)return 0;if(g<1){let t=Math.min(1,Math.max(0,(1-g)/0.6));return v+(Math.sqrt(v)-v)*t}
  let t=Math.min(1,Math.max(0,(g-1)/0.6));return v+(v*v-v)*t}
function frame(t){
  let sc=u8f(P.scale,0.4,2.5),br=u8f(P.bright,0,1.5),gm=u8f(P.gamma,0.4,1.6);
  let seg=Math.max(2,Math.min(12,P.segments));
  const lvl=LEVEL/255;
  if(P.react&1)br*=(0.35+1.1*lvl);
  if(P.react&2)sc*=(0.60+1.2*lvl);
  if(P.react&8)seg=Math.max(2,Math.min(12,2+Math.floor(lvl*10)));
  const wseg=6.28318530718/seg,out=new Float32Array(104);
  for(let row=0;row<8;row++){const y=row-3.5,fy=Math.abs(y);
    for(let col=0;col<13;col++){const x=col-6,fx=Math.abs(x);
      const r=Math.sqrt(x*x+y*y)*sc,ang=Math.atan2(y,x);
      let m=ang+3.14159265;m-=Math.floor(m/wseg)*wseg;
      const wedge=Math.abs(m-wseg*0.5);let v;
      switch(P.pattern){
        case 1:v=0.5+0.5*Math.sin(r*1.4-t*3);break;
        case 2:v=0.5+0.5*Math.sin(r*1.2-t*2)*Math.cos(wedge*seg);break;
        case 3:v=0.5+0.5*Math.sin(wedge*seg*1.5+t*2);break;
        case 4:v=0.5+0.5*Math.sin((fx+fy)*1.05*sc-t*3);break;
        case 5:v=0.5+0.25*(Math.sin(fx*1.3-t*2)+Math.sin(fy*1.3+t*2));break;
        case 6:v=0.5+0.5*((Math.sin(fx*0.8*sc+t)+Math.sin(fy*1.1*sc-t)+Math.sin((fx+fy)*0.6*sc+t*0.7))/3);break;
        default:v=0.5+0.5*Math.sin(r*1.5-t*2+wedge*4);}
      v=Math.max(0,Math.min(1,v));out[row*13+col]=Math.max(0,Math.min(255,gpow(v,gm)*255*br));}}
  return out;}
function textFrame(){
  const out=new Float32Array(104);const ADV=6,total=TXT.length*ADV,cycle=total+13;
  let br=u8f(P.bright,0,1.5); if(P.react&1)br*=(0.35+1.1*(LEVEL/255));
  if(total<=0)return out;
  for(let c=0;c<13;c++){let i=(Math.floor(scrollx)+c)%cycle; if(i<0)i+=cycle;
    if(i>=total)continue; const gi=(i/ADV)|0,gc=i%ADV; if(gc>=5)continue;
    let code=TXT.charCodeAt(gi); if(code>=FONTN)code=32;
    for(let r=0;r<7;r++){ const row=FONT7[code*7+r];
      if((row>>(7-gc))&1) out[r*13+c]=Math.min(255,255*br);} }
  return out;}
function draw(){
  const now=performance.now(),dt=(now-last)/1000;last=now;
  let sp=u8f(P.speed,0,3); if(P.react&4)sp*=(0.3+1.8*(LEVEL/255));
  let f;
  if(MODE){scrollx+=dt*sp*12;const cyc=TXT.length*6+13; if(cyc>0&&scrollx>=cyc)scrollx-=cyc; f=textFrame();}
  else {phase+=dt*sp*2; f=frame(phase);}
  const W=cv.width,H=cv.height,cw=W/13,ch=H/8,r=Math.min(cw,ch)*0.42;
  cx.fillStyle='#05060a';cx.fillRect(0,0,W,H);
  for(let y=0;y<8;y++)for(let x=0;x<13;x++){const v=f[y*13+x]/255,px=x*cw+cw/2,py=y*ch+ch/2;
    cx.beginPath();cx.arc(px,py,r,0,7);cx.fillStyle='#1e2430';cx.fill();
    if(v>0.02){cx.beginPath();cx.arc(px,py,r,0,7);
      cx.fillStyle='rgb('+Math.round(70*v)+','+Math.round(150*v)+','+Math.round(255*v)+')';cx.fill();}}
  requestAnimationFrame(draw);}
requestAnimationFrame(draw);
let inited=false;
async function poll(){try{const j=await(await fetch('/state')).json();
  LEVEL=(P.flags&1)?j.board_lvl:j.level;
  $('#lvlbar').style.width=(LEVEL/255*100)+'%';$('#lvlv').textContent=LEVEL;
  $('#savestat').textContent=(j.board_saved==1?'saved ✓ (survives power-off)':(j.board_saved==2?'save failed':'not saved'));
  $('#sens').textContent='die temp '+j.board_temp.toFixed(1)+' °C · VDDA '+j.board_vdda.toFixed(0)+' mV';
  $('#stat').classList.toggle('ok',j.connected);
  $('#statt').textContent=j.connected?'board live · rendering on-board':'board not responding';
  if(!inited){inited=true;P=Object.assign(P,j.params);SRC=j.reactive_source;
    ['speed','segments','scale','bright','gamma'].forEach(k=>{$('#'+k).value=P[k];$('#'+k+'v').textContent=P[k]});
    syncPat();
    document.querySelectorAll('#srcseg button').forEach(x=>x.classList.toggle('on',x.dataset.s===SRC));
    $('#devrow').style.display=SRC==='audio'?'':'none';
    document.querySelectorAll('#reactseg button').forEach(b=>b.classList.toggle('on',(P.react&+b.dataset.b)!==0));}
 }catch(e){$('#statt').textContent='server offline'}}
setInterval(poll,200);poll();
</script></body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem19841116482")
    ap.add_argument("--http", type=int, default=8080)
    a = ap.parse_args()
    global LINK
    print("opening serial", a.port, "(board resets, ~4s)…"); sys.stdout.flush()
    LINK = Link(a.port); LINK.start()
    Audio().start(); CpuLoad().start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.http), H)
    print("\n  >>> open  http://localhost:%d  <<<\n" % a.http); sys.stdout.flush()
    srv.serve_forever()

if __name__ == "__main__":
    main()
