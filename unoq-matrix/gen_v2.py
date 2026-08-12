"""Final meow->8x13 pipeline: silhouette-fill, GLOBAL bbox (stable anchor),
portrait viewer image, rotate into physical array, emit Arduino sketch.
Also renders a digital-twin animation strip for visual verification."""
import sys, meowlib as M, numpy as np
import scipy.ndimage as ndi
from PIL import Image

NF = M.NFRAMES
GAMMA = 0.85
FLIP = ("--flip" in sys.argv)

def silhouette(a, close=2):
    ink = (a >= 2)
    ink = ndi.binary_dilation(ink, iterations=close)
    filled = ndi.binary_fill_holes(ink)
    filled = ndi.binary_erosion(filled, iterations=close)
    return filled

# 1) all silhouettes + global bbox
sils = [silhouette(M.decode_frame(f)) for f in range(NF)]
union = np.zeros_like(sils[0])
for s in sils: union |= s
ys, xs = np.where(union)
y0,y1,x0,x1 = ys.min(), ys.max()+1, xs.min(), xs.max()+1

def viewer(f):
    s = sils[f][y0:y1, x0:x1].astype(np.uint8)*9
    return M.normalize(M.downsample(s, 8, 13, "mean"), gamma=GAMMA)  # 13x8

def to_physical(V):
    A = np.zeros((8,13), dtype=np.uint8)
    for pr in range(8):
        for pc in range(13):
            vy, vx = (pc, 7-pr) if FLIP else (12-pc, pr)
            A[pr,pc] = V[vy,vx]
    return A

if "--twin" in sys.argv:
    frames = list(range(0, NF, 4))
    imgs = [M.render_twin(viewer(f), cell=26) for f in frames]
    labs = [f"f{f}" for f in frames]
    M.contact_sheet(imgs, labs, cols=6).save("twin_final.png")
    print("saved twin_final.png"); sys.exit()

if "--gif" in sys.argv:
    frames=[M.render_twin(viewer(f), cell=26).convert("P") for f in range(NF)]
    frames[0].save("meow_twin.gif", save_all=True, append_images=frames[1:],
                   duration=[M.DUR[f] for f in range(NF)], loop=0)
    print("saved meow_twin.gif"); sys.exit()

# emit sketch
out = sys.argv[sys.argv.index("--out")+1]
L=["/* Auto-generated (silhouette-fill, global-bbox, portrait). */",
   '#include <Arduino_LED_Matrix.h>', '', 'Arduino_LED_Matrix matrix;', '',
   f'#define NFRAMES {NF}', '', 'static const uint8_t frames[NFRAMES][104] = {']
for f in range(NF):
    A = to_physical(viewer(f))
    L.append("  {%s}," % ",".join(str(int(v)) for v in A.flatten()))
L += ['};','','static const uint16_t durations[NFRAMES] = {',
      "  "+",".join(str(M.DUR[f]) for f in range(NF)),'};','',
      'void setup() {','  Serial.begin(115200);','  matrix.begin();',
      '  matrix.setGrayscaleBits(8);','}','','void loop() {',
      '  for (int f = 0; f < NFRAMES; f++) {','    matrix.draw(frames[f]);',
      '    Serial.print("meow frame "); Serial.println(f);',
      '    delay(durations[f]);','  }','}']
open(out,"w").write("\n".join(L)+"\n")
print("wrote", out)
