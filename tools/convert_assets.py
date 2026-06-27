#!/usr/bin/env python3
# ==========================================
# FILE VERSION: 2.0.0
# DESCRIPTION: Convert landscape/portrait source images into 4 binary
#              permutations for the ESP32-S3-PhotoPainter 6-color display.
# Usage:
#   pip install pillow numpy
#   python convert_assets.py -l landscape.jpg -p portrait.jpg -n name [-o output_dir]
# Output: <name>_l_u.bin, <name>_l_f.bin, <name>_p_u.bin, <name>_p_f.bin
# ==========================================
import argparse, os, sys
import numpy as np
from PIL import Image, ImageOps

# Spectra 6 display palette (RGB)
PALETTE = np.array([
    [0,   0,   0  ],  # 0: Black
    [255, 255, 255],  # 1: White
    [0,   255, 0  ],  # 2: Green
    [0,   0,   255],  # 3: Blue
    [255, 0,   0  ],  # 4: Red
    [255, 255, 0  ],  # 5: Yellow
], dtype=np.float32)

# Hardware register map: palette_idx -> hw_nibble
HW_MAP = np.array([0, 1, 6, 5, 3, 2], dtype=np.uint8)
DW, DH = 800, 480

def quantize_to_palette(rgb_arr):
    """Map each pixel to nearest palette color (vectorized)."""
    flat = rgb_arr.reshape(-1, 3).astype(np.float32)
    # dist shape: (N, 6)
    dists = np.sum((flat[:, None, :] - PALETTE[None, :, :])**2, axis=2)
    return np.argmin(dists, axis=1)

def floyd_steinberg(img_arr):
    """Floyd-Steinberg dither preserving pure black/white pixels."""
    h, w, _ = img_arr.shape
    is_black = np.all(img_arr == [0,0,0], axis=2)
    is_white = np.all(img_arr == [255,255,255], axis=2)
    padded = np.pad(img_arr.astype(np.float32), ((0,1),(1,1),(0,0)), mode='edge')
    for y in range(h):
        for x in range(1, w+1):
            oy, ox = y, x-1
            if is_black[oy,ox]: padded[y,x]=[0,0,0]; continue
            if is_white[oy,ox]: padded[y,x]=[255,255,255]; continue
            old = padded[y,x].copy()
            d = np.sum((PALETTE - old)**2, axis=1)
            new = PALETTE[np.argmin(d)]
            padded[y,x] = new
            err = old - new
            padded[y,x+1]   += err * (7/16)
            padded[y+1,x-1] += err * (3/16)
            padded[y+1,x]   += err * (5/16)
            padded[y+1,x+1] += err * (1/16)
    return np.clip(padded[:h,1:w+1], 0, 255).astype(np.uint8)

def to_bitstream(rgb_arr):
    h, w, _ = rgb_arr.shape
    flat = rgb_arr.reshape(-1, 3).astype(np.float32)
    dists = np.sum((flat[:,None,:] - PALETTE[None,:,:])**2, axis=2)
    hw_idx = HW_MAP[np.argmin(dists, axis=1)].reshape(h, w)
    packed = (hw_idx[:,0::2] << 4) | hw_idx[:,1::2]
    return packed.tobytes()

def load_crop(path, tw, th):
    img = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    w, h = img.size
    ratio = tw / th
    if w/h > ratio:
        nw = int(h*ratio); img = img.crop(((w-nw)//2, 0, (w-nw)//2+nw, h))
    else:
        nh = int(w/ratio); img = img.crop((0, (h-nh)//2, w, (h-nh)//2+nh))
    return img.resize((tw, th), Image.Resampling.LANCZOS)

def convert(img, rotate_180=False):
    if rotate_180:
        img = img.rotate(180)
    return to_bitstream(floyd_steinberg(np.array(img, dtype=np.float32)))

def convert_portrait(img, rotate_180=False):
    if rotate_180:
        img = img.rotate(180)
    arr = floyd_steinberg(np.array(img, dtype=np.float32))
    rotated = np.rot90(arr, k=-1)  # 90deg CW
    return to_bitstream(rotated)

def write_bin(path, data):
    with open(path, 'wb') as f:
        f.write(data)
    print(f'  {path} ({len(data):,} bytes)')

def main():
    ap = argparse.ArgumentParser(description='PicFrame asset converter (4 permutations)')
    ap.add_argument('-l', '--landscape', required=True)
    ap.add_argument('-p', '--portrait',  required=True)
    ap.add_argument('-o', '--output', default='.')
    ap.add_argument('-n', '--name',   default='image')
    args = ap.parse_args()
    os.makedirs(args.output, exist_ok=True)
    base = os.path.join(args.output, args.name)
    print(f'Loading landscape ({DW}x{DH}): {args.landscape}')
    l_img = load_crop(args.landscape, DW, DH)
    print(f'Loading portrait ({DH}x{DW}): {args.portrait}')
    p_img = load_crop(args.portrait, DH, DW)
    print('Generating binaries...')
    write_bin(base + '_l_u.bin', convert(l_img, rotate_180=False))
    write_bin(base + '_l_f.bin', convert(l_img, rotate_180=True))
    write_bin(base + '_p_u.bin', convert_portrait(p_img, rotate_180=False))
    write_bin(base + '_p_f.bin', convert_portrait(p_img, rotate_180=True))
    print('Done!')

if __name__ == '__main__':
    main()
