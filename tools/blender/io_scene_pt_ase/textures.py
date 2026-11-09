"""Priston Tale texture header de-obfuscation.

Client .bmp/.tga files have their file header scrambled:
  BMP: 'A8' magic instead of 'BM', then byte[i] += i*i for i in 2..13
  TGA: 'G8' magic instead of the (normally zero) id-length / colormap bytes,
       then byte[i] += i*i for i in 2..17 (the whole 18-byte TGA header)
Everything after the header (14 bytes BMP / 18 bytes TGA) is untouched.
"""

import os
import shutil


def tga_header_ok(h, file_len):
    """An 18-byte TGA header a reader can use: a known image type, a usual pixel size and
    (uncompressed) pixels that fit in a file of file_len bytes."""
    id_len, cmap, typ = h[0], h[1], h[2]
    w, ht, bpp = h[12] | h[13] << 8, h[14] | h[15] << 8, h[16]
    if cmap > 1 or typ not in (1, 2, 3, 9, 10, 11):
        return False
    if w == 0 or ht == 0 or bpp not in (8, 15, 16, 24, 32):
        return False
    if typ in (2, 3) and 18 + id_len + w * ht * ((bpp + 7) // 8) > file_len:
        return False
    return True


def bmp_header_ok(h, file_len):
    """A BMP file header (14 bytes) whose pixel offset lies inside a file of file_len bytes."""
    pix = int.from_bytes(h[10:14], 'little')
    return 26 <= pix < file_len


def decode_texture_bytes(data):
    """Return (decoded_bytes, kind) where kind is 'bmp', 'tga' or None (unchanged)."""
    if len(data) < 18:
        return data, None
    head = bytearray(data[:14])
    if head[0:2] == b'A8':
        head[0:2] = b'BM'
        for i in range(2, 14):
            head[i] = (head[i] - i * i) & 0xFF
        # scrambled twice (StartImage\...\Mokoba.BMP): the pixel offset points past the end once
        # undone; twice, size and offset are right
        if not bmp_header_ok(head, len(data)):
            twice = bytearray(14)
            for i in range(2, 14):
                twice[i] = (head[i] - i * i) & 0xFF
            if bmp_header_ok(twice, len(data)) and int.from_bytes(twice[2:6], 'little') == len(data):
                head[2:14] = twice[2:14]
        return bytes(head) + data[14:], 'bmp'
    if head[0:2] == b'G8':
        head = bytearray(data[:18])
        head[0] = 0
        head[1] = 0
        for i in range(2, 18):
            head[i] = (head[i] - i * i) & 0xFF
        # some client TGAs were scrambled twice (Field\castle, Fall_Game, Iron): once undone
        # they still have no sane header, twice they do
        if not tga_header_ok(head, len(data)):
            twice = bytearray(18)
            for i in range(2, 18):
                twice[i] = (head[i] - i * i) & 0xFF
            if tga_header_ok(twice, len(data)):
                head[2:18] = twice[2:18]
        return bytes(head) + data[18:], 'tga'
    if head[0:2] == b'BM':
        # Already plain BMP.  Some third-party decoders leave a garbage
        # bfSize field which a few loaders reject - normalise it.
        size = len(data)
        head[2:6] = bytes((size & 0xFF, (size >> 8) & 0xFF, (size >> 16) & 0xFF, (size >> 24) & 0xFF))
        return bytes(head) + data[14:], 'bmp'
    return data, None


def decode_texture_file(src, dst):
    with open(src, 'rb') as f:
        data = f.read()
    out, kind = decode_texture_bytes(data)
    d = os.path.dirname(dst)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(dst, 'wb') as f:
        f.write(out)
    return kind


_dir_cache = {}


def _listdir_ci(d):
    key = os.path.normcase(os.path.abspath(d))
    if key not in _dir_cache:
        try:
            _dir_cache[key] = {n.lower(): n for n in os.listdir(d)}
        except OSError:
            _dir_cache[key] = {}
    return _dir_cache[key]


def resolve_case_insensitive(root, rel):
    """Find root/rel on disk ignoring case and trying .bmp<->.tga swaps.
    Returns the real path or None."""
    rel = rel.replace('\\', '/').strip('/')
    if not rel:
        return None
    parts = rel.split('/')
    cur = root
    for i, p in enumerate(parts):
        entries = _listdir_ci(cur)
        last = (i == len(parts) - 1)
        name = entries.get(p.lower())
        if name is None and last:
            base, ext = os.path.splitext(p)
            for alt in ('.bmp', '.tga', '.png', '.jpg', '.dds'):
                name = entries.get((base + alt).lower())
                if name:
                    break
        if name is None:
            return None
        cur = os.path.join(cur, name)
    return cur if os.path.isfile(cur) else None
