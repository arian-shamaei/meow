#!/usr/bin/env python3
"""Pack the arrays in c/meow_frames.h into assets/meow.bin.

Layout (all big-endian):
    u32 nframes, u32 size, u32 nruns
    u32 frame_off[nframes+1]
    u8  rle_value[nruns]
    u8  rle_count[nruns]
    u16 duration_ms[nframes]
"""
import re
import struct
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
hdr = (root.parent / "c" / "meow_frames.h").read_text()

def define(name):
    return int(re.search(rf"#define {name} (\d+)", hdr).group(1))

def array(name):
    m = re.search(rf"meow_{name}\[[^]]*\]\s*=\s*\{{(.*?)\}};", hdr, re.S)
    return [int(x) for x in re.findall(r"\d+", m.group(1))]

nframes, size, nruns = define("MEOW_NFRAMES"), define("MEOW_SIZE"), define("MEOW_NRUNS")
off, val, cnt, dur = array("frame_off"), array("rle_value"), array("rle_count"), array("duration_ms")
assert len(off) == nframes + 1 and len(val) == nruns and len(cnt) == nruns and len(dur) == nframes

out = root / "assets" / "meow.bin"
with open(out, "wb") as f:
    f.write(struct.pack(">III", nframes, size, nruns))
    f.write(struct.pack(f">{nframes + 1}I", *off))
    f.write(bytes(val))
    f.write(bytes(cnt))
    f.write(struct.pack(f">{nframes}H", *dur))
print(f"{out}: {out.stat().st_size} bytes, {nframes} frames of {size}x{size}")
