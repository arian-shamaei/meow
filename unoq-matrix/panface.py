"""Higher effective resolution via a zoom+pan viewport over a hi-res cat face.
The 8x13 matrix is a small window that tours the face (ears, eyes, mouth),
showing crisp zoomed detail instead of the whole cat squeezed into 104 px."""
import sys, math, numpy as np, meowlib as M
from PIL import Image, ImageDraw

# ---- hi-res cat face: bright line-art on dark (matches the reference) ----
W, H = 260, 200
def draw_face():
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    LW = 7
    cx = W//2
    # head (rounded) outline
    d.ellipse([cx-95, 70, cx+95, 190], outline=255, width=LW)
    # ears: big pointed triangles
    d.line([(cx-92,110),(cx-78,18),(cx-20,86)], fill=255, width=LW, joint="curve")
    d.line([(cx+92,110),(cx+78,18),(cx+20,86)], fill=255, width=LW, joint="curve")
    # inner ears
    d.line([(cx-70,70),(cx-62,46),(cx-46,74)], fill=180, width=4, joint="curve")
    d.line([(cx+70,70),(cx+62,46),(cx+46,74)], fill=180, width=4, joint="curve")
    # eyes (big ovals)
    d.ellipse([cx-64,95, cx-20,150], outline=255, width=LW)
    d.ellipse([cx+20,95, cx+64,150], outline=255, width=LW)
    # pupils
    d.ellipse([cx-50,118, cx-34,140], fill=255)
    d.ellipse([cx+34,118, cx+50,140], fill=255)
    # nose + open smiling mouth
    d.line([(cx-8,150),(cx,158),(cx+8,150)], fill=255, width=5, joint="curve")
    d.arc([cx-26,150, cx+26,182], 20, 160, fill=255, width=LW)
    # cheek blush ticks
    for sx in (-1,1):
        for k in range(3):
            d.line([(cx+sx*(70+ k*10), 150+k*7),(cx+sx*(58+k*10),150+k*7)], fill=150, width=4)
    return np.asarray(img, dtype=np.uint8)

FACE = draw_face()

# ---- viewport: 13:8 aspect window, panned along a looping tour ----
VH = 96                       # viewport height in hi-res px (zoom level)
VW = int(round(VH*13/8))      # keep matrix aspect
# tour waypoints (center of viewport) touring the features, then loop
def clampc(cx, cy):
    cx = min(max(cx, VW//2), W-VW//2)
    cy = min(max(cy, VH//2), H-VH//2)
    return cx, cy
cx0 = W//2
WPTS = [
    (cx0-40, 122),   # left eye
    (cx0+40, 122),   # right eye
    (cx0,    165),   # mouth
    (cx0,    70),    # forehead/between ears
    (cx0-70, 60),    # left ear
    (cx0+70, 60),    # right ear
    (cx0,    122),   # center
]
def build_frames(steps_per_leg=7):
    pts = []
    n = len(WPTS)
    for i in range(n):
        a = WPTS[i]; b = WPTS[(i+1)%n]
        for s in range(steps_per_leg):
            t = s/steps_per_leg
            t = 0.5-0.5*math.cos(math.pi*t)   # ease in/out
            px = a[0]+(b[0]-a[0])*t
            py = a[1]+(b[1]-a[1])*t
            pts.append(clampc(px, py))
    frames=[]
    for (px,py) in pts:
        x0=int(px-VW/2); y0=int(py-VH/2)
        crop = Image.fromarray(FACE).crop((x0,y0,x0+VW,y0+VH))
        small = crop.resize((13,8), Image.BOX)
        g = np.asarray(small, dtype=float)
        # brighten lines
        hi = g.max() or 1
        g = (np.clip(g/hi,0,1)**0.7*255).astype(np.uint8)
        frames.append(g)
    return frames

FR = build_frames()
DU = [70]*len(FR)

if "--face" in sys.argv:
    Image.fromarray(FACE).save("hires_face.png"); print("saved hires_face.png", FACE.shape)
if "--strip" in sys.argv:
    idx=list(range(0,len(FR),3))
    M.contact_sheet([M.render_twin(FR[i], cell=22) for i in idx],
        [str(i) for i in idx], cols=7).save("pan_strip.png")
    print("saved pan_strip.png", len(FR), "frames")
if "--gif" in sys.argv:
    ims=[M.render_twin(f, cell=22).convert("P") for f in FR]
    ims[0].save("pan_twin.gif", save_all=True, append_images=ims[1:], duration=DU, loop=0)
    print("saved pan_twin.gif")
if "--out" in sys.argv:
    out=sys.argv[sys.argv.index("--out")+1]; N=len(FR)
    L=["/* Zoom+pan cat-face viewport over a hi-res image, Uno Q 8x13. */",
       '#include <Arduino_LED_Matrix.h>','','Arduino_LED_Matrix matrix;','',
       f'#define NFRAMES {N}','','static const uint8_t frames[NFRAMES][104] = {']
    for f in FR: L.append("  {%s}," % ",".join(str(int(v)) for v in f.flatten()))
    L+=['};','','static const uint16_t durations[NFRAMES] = {',
        "  "+",".join(str(d) for d in DU),'};','',
        'void setup(){ Serial.begin(115200); matrix.begin(); matrix.setGrayscaleBits(8); }','',
        'void loop(){ for(int f=0;f<NFRAMES;f++){ matrix.draw(frames[f]);',
        '  Serial.print("meow frame "); Serial.println(f); delay(durations[f]); } }']
    open(out,"w").write("\n".join(L)+"\n"); print("wrote",out,N,"frames")
