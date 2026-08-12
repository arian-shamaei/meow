#!/usr/bin/env python3
"""Decode meow_frames.h, downsample each 110x110 frame to an 8x13 LED-matrix
frame (8x8 cat centred in the 13-wide grid), quantise to 0..255, and emit an
Arduino sketch for the Uno Q. Also prints an ASCII preview to pick the kernel."""
import re, sys

SRC = "/Users/arianshamaei/Projects/silly-catui/c/meow_frames.h"
MEOW_SIZE = 110
NFRAMES = 45
LEVELS = 10  # levels 0..9

def parse_array(text, name):
    m = re.search(name + r"\[\d*\]\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        sys.exit("array not found: " + name)
    body = m.group(1)
    return [int(x) for x in re.findall(r"-?\d+", body)]

def main():
    text = open(SRC).read()
    val = parse_array(text, "meow_rle_value")
    cnt = parse_array(text, "meow_rle_count")
    off = parse_array(text, "meow_frame_off")
    dur = parse_array(text, "meow_duration_ms")
    assert len(off) == NFRAMES + 1, len(off)
    assert len(dur) == NFRAMES, len(dur)

    def decode(f):
        px = []
        for r in range(off[f], off[f+1]):
            px.extend([val[r]] * cnt[f])  # placeholder; fixed below
        return px

    # decode correctly (count per run, not per index)
    def decode_frame(f):
        px = bytearray()
        for r in range(off[f], off[f+1]):
            px.extend(bytes([val[r]]) * cnt[r])
        assert len(px) == MEOW_SIZE*MEOW_SIZE, (f, len(px))
        return px

    # downsample 110x110 frame into a W x H mean block (H rows, W cols)
    def down(px, W, H):
        out = [[0.0]*W for _ in range(H)]
        for oy in range(H):
            y0 = oy*MEOW_SIZE//H
            y1 = (oy+1)*MEOW_SIZE//H
            for ox in range(W):
                x0 = ox*MEOW_SIZE//W
                x1 = (ox+1)*MEOW_SIZE//W
                acc = 0; n = 0
                for y in range(y0, y1):
                    row = y*MEOW_SIZE
                    for x in range(x0, x1):
                        acc += px[row+x]; n += 1
                out[oy][ox] = acc/n
        return out

    def stretch_gamma(block, gamma=0.65):
        H = len(block); W = len(block[0])
        hi = max(v for r in block for v in r) or 1.0
        out = [[0.0]*W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                t = block[y][x]/hi if hi>0 else 0.0
                out[y][x] = (t**gamma) * 255.0
        return out

    RAMP = " .:-=+*#%@"
    def ascii_preview(rows):
        lines = []
        for r in rows:
            s = "".join(RAMP[min(9, int(v)*10//256)] for v in r)
            lines.append("|"+s+"|")
        return "\n".join(lines)

    # Physical matrix is 8 rows x 13 cols (landscape). We render an UPRIGHT
    # portrait cat 8 wide x 13 tall (viewer coords V[vy][vx]) so it fills all
    # 104 LEDs, then rotate 90deg into the physical array A[pr][pc].
    # Mapping (90 deg): A[pr][pc] = V[12 - pc][pr]. Set ROT_FLIP to try the
    # other rotation if it shows up upside-down/mirrored.
    ROT_FLIP = ("--flip" in sys.argv)
    def to_physical(V):
        A = [[0]*13 for _ in range(8)]
        for pr in range(8):
            for pc in range(13):
                if ROT_FLIP:
                    vy, vx = pc, 7 - pr
                else:
                    vy, vx = 12 - pc, pr
                A[pr][pc] = int(round(V[vy][vx]))
        return A

    # build all 45 frames: portrait viewer image (8w x 13h), then rotate
    all_frames = []   # each is physical 8x13 flattened (104)
    viewer = []       # keep viewer images for preview
    for f in range(NFRAMES):
        V = stretch_gamma(down(decode_frame(f), 8, 13))  # 13 rows x 8 cols
        viewer.append(V)
        A = to_physical(V)
        all_frames.append([v for r in A for v in r])

    if "--preview" in sys.argv:
        for f in (0, 22, 44):
            print("-- frame", f, "dur", dur[f], "ms  (VIEWER: upright, 8 wide x 13 tall) --")
            print(ascii_preview(viewer[f]))
        return

    # emit Arduino sketch
    out = sys.argv[sys.argv.index("--out")+1]
    lines = []
    lines.append("/* Auto-generated from meow_frames.h -- silly-cat on the Uno Q 8x13 LED matrix. */")
    lines.append('#include <Arduino_LED_Matrix.h>')
    lines.append("")
    lines.append("Arduino_LED_Matrix matrix;")
    lines.append("")
    lines.append("#define NFRAMES %d" % NFRAMES)
    lines.append("")
    lines.append("static const uint8_t frames[NFRAMES][104] = {")
    for f in range(NFRAMES):
        vals = ",".join(str(v) for v in all_frames[f])
        lines.append("  {%s}," % vals)
    lines.append("};")
    lines.append("")
    lines.append("static const uint16_t durations[NFRAMES] = {")
    lines.append("  " + ",".join(str(d) for d in dur))
    lines.append("};")
    lines.append("")
    lines.append("void setup() {")
    lines.append("  matrix.begin();")
    lines.append("  matrix.setGrayscaleBits(8);  // 0..255, auto-mapped to 8 hw levels")
    lines.append("}")
    lines.append("")
    lines.append("void loop() {")
    lines.append("  for (int f = 0; f < NFRAMES; f++) {")
    lines.append("    matrix.draw(frames[f]);")
    lines.append("    delay(durations[f]);")
    lines.append("  }")
    lines.append("}")
    open(out, "w").write("\n".join(lines) + "\n")
    print("wrote", out, "(", NFRAMES, "frames )")

if __name__ == "__main__":
    main()
