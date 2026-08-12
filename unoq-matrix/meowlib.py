"""Shared helpers: decode meow_frames.h, downsample, and a digital-twin
renderer of the Uno Q 8x13 blue LED matrix."""
import re, numpy as np
from PIL import Image, ImageDraw, ImageFilter

SRC = "/Users/arianshamaei/Projects/silly-catui/c/meow_frames.h"
MEOW_SIZE = 110
NFRAMES = 45
LEVELS = 10
ROWS, COLS = 8, 13  # physical matrix

def _parse(text, name):
    m = re.search(name + r"\[\d*\]\s*=\s*\{(.*?)\};", text, re.S)
    return [int(x) for x in re.findall(r"-?\d+", m.group(1))]

_T = open(SRC).read()
VAL = _parse(_T, "meow_rle_value")
CNT = _parse(_T, "meow_rle_count")
OFF = _parse(_T, "meow_frame_off")
DUR = _parse(_T, "meow_duration_ms")

def decode_frame(f):
    """Return 110x110 uint8 (levels 0..9)."""
    px = bytearray()
    for r in range(OFF[f], OFF[f+1]):
        px.extend(bytes([VAL[r]]) * CNT[r])
    a = np.frombuffer(bytes(px), dtype=np.uint8).reshape(MEOW_SIZE, MEOW_SIZE)
    return a

def autocrop(a, thresh=2, pad=2):
    """Crop to the cat's bounding box (level>=thresh), with padding."""
    ys, xs = np.where(a >= thresh)
    if len(ys) == 0:
        return a
    y0, y1 = max(0, ys.min()-pad), min(a.shape[0], ys.max()+1+pad)
    x0, x1 = max(0, xs.min()-pad), min(a.shape[1], xs.max()+1+pad)
    return a[y0:y1, x0:x1]

def downsample(a, W, H, kernel="mean"):
    """a (any HxW uint8 levels) -> HxW float grid via block kernel."""
    src_h, src_w = a.shape
    out = np.zeros((H, W), dtype=float)
    for oy in range(H):
        y0, y1 = oy*src_h//H, (oy+1)*src_h//H
        for ox in range(W):
            x0, x1 = ox*src_w//W, (ox+1)*src_w//W
            blk = a[y0:max(y1,y0+1), x0:max(x1,x0+1)].astype(float)
            if kernel == "mean":  out[oy, ox] = blk.mean()
            elif kernel == "max": out[oy, ox] = blk.max()
            elif kernel == "cover": out[oy, ox] = (blk >= 2).mean() * (LEVELS-1)
            elif kernel == "p75": out[oy, ox] = np.percentile(blk, 75)
    return out

def normalize(g, gamma=0.65, floor=0.0):
    hi = g.max() or 1.0
    t = np.clip(g/hi, 0, 1)
    v = (t ** gamma)
    v = floor + (1-floor)*v
    v[g <= 0] = 0
    return (v*255).astype(np.uint8)

def render_twin(grid255, cell=42, scale=1, bg=(8,10,16),
                led=(70,150,255), glow=True, gap=0.16, title=None):
    """grid255: HxW uint8 in VIEWER orientation. Returns a PIL image that
    mimics the blue LED matrix (dots, brightness, glow)."""
    H, W = grid255.shape
    margin = cell
    img = Image.new("RGB", (W*cell + 2*margin, H*cell + 2*margin), bg)
    dr = ImageDraw.Draw(img)
    r = cell*(1-gap)/2
    for y in range(H):
        for x in range(W):
            b = int(grid255[y, x])
            cx = margin + x*cell + cell/2
            cy = margin + y*cell + cell/2
            # unlit dot faint outline
            dr.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(18,20,26))
            if b > 4:
                f = b/255.0
                col = tuple(int(c*f) for c in led)
                dr.ellipse([cx-r, cy-r, cx+r, cy+r], fill=col)
    if glow:
        img = img.filter(ImageFilter.GaussianBlur(cell*0.06))
        # re-draw bright cores on top for crispness
        dr2 = ImageDraw.Draw(img)
        for y in range(H):
            for x in range(W):
                b = int(grid255[y, x])
                if b > 4:
                    cx = margin + x*cell + cell/2
                    cy = margin + y*cell + cell/2
                    f = b/255.0
                    col = tuple(min(255,int(c*f*1.1)) for c in led)
                    rr = r*0.6
                    dr2.ellipse([cx-rr, cy-rr, cx+rr, cy+rr], fill=col)
    if scale != 1:
        img = img.resize((img.width*scale, img.height*scale), Image.NEAREST)
    return img

def contact_sheet(images, labels, cols=4, pad=10, bg=(0,0,0)):
    from PIL import ImageFont
    w = max(i.width for i in images); h = max(i.height for i in images)
    rows = (len(images)+cols-1)//cols
    lab_h = 22
    sheet = Image.new("RGB", (cols*(w+pad)+pad, rows*(h+lab_h+pad)+pad), bg)
    dr = ImageDraw.Draw(sheet)
    for i,(im,lab) in enumerate(zip(images,labels)):
        r,c = divmod(i, cols)
        x = pad + c*(w+pad); y = pad + r*(h+lab_h+pad)
        sheet.paste(im, (x, y+lab_h))
        dr.text((x+2, y+4), lab, fill=(230,230,230))
    return sheet
