"""Priston Tale texture header de-obfuscation.

Client .bmp/.tga files have their file header scrambled:
  BMP: 'A8' magic instead of 'BM', then byte[i] += i*i for i in 2..13
  TGA: 'G8' magic instead of the (normally zero) id-length / colormap bytes,
       then byte[i] += i*i for i in 2..17 (the whole 18-byte TGA header)
Everything after the header (14 bytes BMP / 18 bytes TGA) is untouched.
"""

import os
import shutil


def decode_texture_bytes(data):
    """Return (decoded_bytes, kind) where kind is 'bmp', 'tga' or None (unchanged)."""
    if len(data) < 18:
        return data, None
    head = bytearray(data[:14])
    if head[0:2] == b'A8':
        head[0:2] = b'BM'
        for i in range(2, 14):
            head[i] = (head[i] - i * i) & 0xFF
        return bytes(head) + data[14:], 'bmp'
    if head[0:2] == b'G8':
        head = bytearray(data[:18])
        head[0] = 0
        head[1] = 0
        for i in range(2, 18):
            head[i] = (head[i] - i * i) & 0xFF
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
