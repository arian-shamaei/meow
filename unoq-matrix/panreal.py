"""Pan a zoomed 8x13 viewport over the ACTUAL reference drawing (not a redraw).
The drawing is black lines on white -> invert so lines light up on the dark
matrix. Max-pool downsample keeps thin lines crisp when zoomed in."""
import sys, math, numpy as np, meowlib as M
from PIL import Image
import scipy.ndimage as ndi

IMG = "/Users/arianshamaei/.claude/image-cache/9322520d-0903-47a3-8251-b6ef4d82fbae/1.png"

im = Image.open(IMG).convert("L")
W, H = im.size
g = 255 - np.asarray(im, dtype=np.uint8)      # invert: lines bright, paper dark
g = np.clip((g.astype(float) - 35) * 1.6, 0, 255).astype(np.uint8)  # kill paper, boost lines
DIL = int(sys.argv[sys.argv.index("--dil")+1]) if "--dil" in sys.argv else 2
if DIL: g = ndi.grey_dilation(g, size=DIL)    # fatten lines so they survive shrink
SRC = g

VHF = float(sys.argv[sys.argv.index("--vh")+1]) if "--vh" in sys.argv else 0.34
VH = int(H * VHF)             # viewport height (zoom); smaller = more zoom
VW = int(round(VH * 13/8))    # match matrix aspect
def clampc(cx, cy):
    return (min(max(cx, VW/2), W-VW/2), min(max(cy, VH/2), H-VH/2))

# feature waypoints as fractions of the drawing (tour of the face)
F = [(0.50,0.46),  # both eyes / center
     (0.36,0.44),  # left eye
     (0.34,0.16),  # left ear
     (0.70,0.17),  # right ear
     (0.63,0.42),  # right eye
     (0.50,0.60),  # mouth
     (0.48,0.82),  # chin ruff
     (0.50,0.46)]  # back to center
WP = [clampc(fx*W, fy*H) for fx,fy in F]

def maxpool(crop):  # crop float HxW -> 8x13 via max (keeps lines)
    ch, cw = crop.shape
    out = np.zeros((8,13))
    for r in range(8):
        y0,y1 = r*ch//8, (r+1)*ch//8
        for c in range(13):
            x0,x1 = c*cw//13, (c+1)*cw//13
            out[r,c] = crop[y0:max(y1,y0+1), x0:max(x1,x0+1)].max()
    return out

def frames(steps=8):
    pts=[]
    for i in range(len(WP)-1):
        a,b = WP[i], WP[i+1]
        for s in range(steps):
            t=s/steps; t=0.5-0.5*math.cos(math.pi*t)
            pts.append((a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t))
    out=[]
    for px,py in pts:
        x0=int(px-VW/2); y0=int(py-VH/2)
        crop=SRC[y0:y0+VH, x0:x0+VW].astype(float)
        grid=maxpool(crop)
        hi=grid.max() or 1
        out.append((np.clip(grid/hi,0,1)**0.8*255).astype(np.uint8))
    return out

FR=frames(); DU=[80]*len(FR)

if "--src" in sys.argv:
    Image.fromarray(SRC).save("real_src.png"); print("saved real_src.png", (W,H), "VW,VH",VW,VH)
if "--strip" in sys.argv:
    idx=list(range(0,len(FR),3))
    M.contact_sheet([M.render_twin(FR[i], cell=22) for i in idx],[str(i) for i in idx],cols=7).save("panreal_strip.png")
    print("saved panreal_strip.png", len(FR),"frames")
if "--gif" in sys.argv:
    ims=[M.render_twin(f, cell=22).convert("P") for f in FR]
    ims[0].save("panreal_twin.gif", save_all=True, append_images=ims[1:], duration=DU, loop=0)
    print("saved panreal_twin.gif")
if "--out" in sys.argv:
    out=sys.argv[sys.argv.index("--out")+1]; N=len(FR)
    L=["/* Zoom+pan over the ACTUAL cat drawing, Uno Q 8x13. */",
       '#include <Arduino_LED_Matrix.h>','','Arduino_LED_Matrix matrix;','',
       f'#define NFRAMES {N}','','static const uint8_t frames[NFRAMES][104] = {']
    for f in FR: L.append("  {%s}," % ",".join(str(int(v)) for v in f.flatten()))
    L+=['};','','static const uint16_t durations[NFRAMES] = {',"  "+",".join(str(d) for d in DU),'};','',
        'void setup(){ Serial.begin(115200); matrix.begin(); matrix.setGrayscaleBits(8); }','',
        'void loop(){ for(int f=0;f<NFRAMES;f++){ matrix.draw(frames[f]);',
        '  Serial.print("meow frame "); Serial.println(f); delay(durations[f]); } }']
    open(out,"w").write("\n".join(L)+"\n"); print("wrote",out,N,"frames")
