"""Cat-FACE icon on the Uno Q 8x13 matrix (landscape, no rotation).
Simple loop: open eyes -> blink -> open -> meow (mouth opens). Emits sketch
and a digital-twin GIF/strip for verification."""
import sys, numpy as np, meowlib as M
CH = {' ':0, '.':70, ':':130, '+':190, '#':255}
def grid(rows):
    a=np.zeros((8,13),dtype=np.uint8)
    for r,line in enumerate(rows):
        assert len(line)==13,(r,len(line),repr(line))
        for c,ch in enumerate(line): a[r,c]=CH[ch]
    return a

OPEN = grid([
 ".#.........#.",
 "###.......###",
 "####.....####",
 "#############",
 "##..##.##..##",
 "##..##.##..##",
 "#############",
 "####.###.####",
])
BLINK = grid([   # eyes closed (lit), tiny lid line
 ".#.........#.",
 "###.......###",
 "####.....####",
 "#############",
 "#############",
 "##.:##.##:.##".replace("##.:##.##:.##","#############"),
 "#############",
 "####.###.####",
])
MEOW = grid([    # mouth open with tongue
 ".#.........#.",
 "###.......###",
 "####.....####",
 "#############",
 "##..##.##..##",
 "##..##.##..##",
 "#####...#####",
 "######+######",
])

# sequence of (frame, duration_ms)
SEQ = [(OPEN,1500),(BLINK,130),(OPEN,1100),(MEOW,280),(MEOW,120),(OPEN,600)]
FR = [f for f,_ in SEQ]; DU=[d for _,d in SEQ]; N=len(SEQ)

if "--strip" in sys.argv:
    M.contact_sheet([M.render_twin(f, cell=30) for f in FR],
        [f"{i}:{DU[i]}ms" for i in range(N)], cols=3).save("face_strip.png")
    print("saved face_strip.png"); sys.exit()
if "--gif" in sys.argv:
    ims=[M.render_twin(f, cell=26).convert("P") for f in FR]
    ims[0].save("face_twin.gif", save_all=True, append_images=ims[1:],
                duration=DU, loop=0); print("saved face_twin.gif"); sys.exit()

out=sys.argv[sys.argv.index("--out")+1]
L=["/* Cat-face icon (blink + meow) for Uno Q 8x13 matrix, landscape. */",
   '#include <Arduino_LED_Matrix.h>','','Arduino_LED_Matrix matrix;','',
   f'#define NFRAMES {N}','','static const uint8_t frames[NFRAMES][104] = {']
for f in FR:
    L.append("  {%s}," % ",".join(str(int(v)) for v in f.flatten()))
L+=['};','','static const uint16_t durations[NFRAMES] = {',
    "  "+",".join(str(d) for d in DU),'};','',
    'void setup() {','  Serial.begin(115200);','  matrix.begin();',
    '  matrix.setGrayscaleBits(8);','}','','void loop() {',
    '  for (int f = 0; f < NFRAMES; f++) {','    matrix.draw(frames[f]);',
    '    Serial.print("meow frame "); Serial.println(f);',
    '    delay(durations[f]);','  }','}']
open(out,"w").write("\n".join(L)+"\n"); print("wrote",out)
