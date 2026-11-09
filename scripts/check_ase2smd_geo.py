"""Compare two map .smd files as geometry (order-free): every face is matched by its three corner
positions (rotation kept, so winding counts), then material textures / flags, UVs per corner and
vertex colours are compared.  For round trips (game .smd -> our .ase -> .smd) where objects come
back in another order.

    python check_ase2smd_geo.py <game.smd> <ours.smd>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_ase2smd import stage, chains   # noqa: E402


def faces(s):
    ch = chains(s)
    out = {}
    for i, f in enumerate(s['faces']):
        corners = [s['verts'][f[k]] for k in range(3)]
        pos = [c[:3] for c in corners]
        r = pos.index(min(pos))                          # rotate so the smallest corner leads
        order = [(r + k) % 3 for k in range(3)]
        key = tuple(pos[k] for k in order)
        raw, names = s['mats'][f[3]]
        mat = (tuple(names), struct.unpack_from('<I', raw, 4)[0], raw[40:132], raw[132:304])
        uvs = tuple(tuple((layer[k], layer[3 + k]) for k in order) for layer in ch[i])
        cols = tuple(corners[k][3:] for k in order)
        out.setdefault(key, []).append((mat, uvs, cols, f[5:8]))
    return out


def main():
    a, b = stage(sys.argv[1]), stage(sys.argv[2])
    fa, fb = faces(a), faces(b)
    only_a = sum(len(v) for k, v in fa.items() if k not in fb)
    only_b = sum(len(v) for k, v in fb.items() if k not in fa)
    flipped = 0
    for k in fa:
        if k not in fb:
            r = (k[0], k[2], k[1])
            rr = min(r[i:] + r[:i] for i in range(3))
            if rr in fb:
                flipped += 1
    mat = uv = col = nrm = same = 0
    ex = {}
    for k, la in fa.items():
        lb = fb.get(k)
        if not lb:
            continue
        x, y = la[0], lb[0]
        same += 1
        if x[0][0] != y[0][0]:
            mat += 1; ex.setdefault('texture', (x[0][0], y[0][0]))
        elif x[0] != y[0]:
            mat += 1; ex.setdefault('material', (x[0][1:2], y[0][1:2]))
        if len(x[1]) != len(y[1]) or any(abs(p - q) > 1e-4 for u, v in zip(x[1], y[1]) for c, d in zip(u, v) for p, q in zip(c, d)):
            uv += 1; ex.setdefault('uv', (x[1], y[1]))
        if any(abs(p - q) > 1 for c, d in zip(x[2], y[2]) for p, q in zip(c, d)):
            col += 1; ex.setdefault('colour', (x[2], y[2]))
        if any(abs(p - q) > 1 for p, q in zip(x[3], y[3])):
            nrm += 1
    print('faces: %d / %d, matched %d, only in first %d (%d of them with the opposite winding), only in second %d'
          % (len(a['faces']), len(b['faces']), same, only_a, flipped, only_b))
    print('of the matched: material %d, uv %d, colour %d, normal %d' % (mat, uv, col, nrm))
    for k, v in ex.items():
        print('  first %s difference: %s' % (k, str(v)[:400]))
    print('lights: %d / %d, same set: %s' % (len(a['lights']), len(b['lights']), sorted(a['lights']) == sorted(b['lights'])))
    if sorted(a['lights']) != sorted(b['lights']):
        print('  ', sorted(a['lights'])[:2], sorted(b['lights'])[:2])
    print('lighting %s / %s, map rect %s / %s' % (a['light'], b['light'], a['rect'], b['rect']))


if __name__ == '__main__':
    main()
