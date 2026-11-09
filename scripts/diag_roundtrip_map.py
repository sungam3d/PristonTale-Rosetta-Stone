"""One map: decode -> encode -> what differs in materials and UVs, grouped (for roundtrip_maps.py DIFFs).

    python diag_roundtrip_map.py <map.smd> <smd2ase.exe> <work folder>
"""
import os
import struct
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_ase2smd import stage, texdir                 # noqa: E402
from check_ase2smd_geo import faces                      # noqa: E402

NAMES = ('InUse TexCnt t0 t1 t2 t3 t4 t5 t6 t7 TSS0 TSS1 TSS2 TSS3 TSS4 TSS5 TSS6 TSS7 TFS0 TFS1 TFS2 TFS3 TFS4 TFS5 '
         'TFS6 TFS7 Reform MapOpac TexType Blend Shade TwoSide Serial DifR DifG DifB Transp Self TexSwap MatFrame '
         'TexClip UseState MeshState Wind').split()


def main():
    p, exe, work = sys.argv[1:4]
    dec = os.path.join(work, 'dec')
    subprocess.run([exe, p, '-o', dec], capture_output=True)
    base = os.path.splitext(os.path.basename(p))[0].lower() + '.ase'
    ase = next(os.path.join(dp, f) for dp, dn, fn in os.walk(dec) for f in fn if f.lower() == base)
    g = stage(p)
    out = os.path.join(work, 'rt.smd')
    c, br, lx, ly, lz = g['light']
    subprocess.run([exe, '--ase2smd', ase, out, texdir(g), str(c), str(br), str(lx), str(ly), str(lz)], capture_output=True)
    o = stage(out)
    fa, fb = faces(g), faces(o)
    mc, uc = Counter(), Counter()
    mex, uex = {}, {}
    for k, la in fa.items():
        lb = fb.get(k)
        if not lb:
            continue
        x, y = la[0], lb[0]
        if x[0] != y[0]:
            if x[0][0] != y[0][0]:
                key = ('names',)
                ex = (x[0][0], y[0][0])
            else:
                ra, rb = x[0][2] + x[0][3], y[0][2] + y[0][3]
                key = tuple(NAMES[10 + i // 4] if 10 + i // 4 < len(NAMES) else 'anim+%d' % (i - 4 * (len(NAMES) - 10))
                            for i in range(0, len(ra), 4) if ra[i:i + 4] != rb[i:i + 4])
                if x[0][1] != y[0][1]:
                    key = ('TexCnt',) + key
                ex = (x[0][0][:2], [struct.unpack_from('<i', ra, 4 * (NAMES.index(n) - 10))[0] for n in key if n in NAMES[10:]],
                      [struct.unpack_from('<i', rb, 4 * (NAMES.index(n) - 10))[0] for n in key if n in NAMES[10:]])
            mc[key] += 1
            mex.setdefault(key, ex)
        if len(x[1]) != len(y[1]):
            uc['layer count %d vs %d' % (len(x[1]), len(y[1]))] += 1
            uex.setdefault('layer count %d vs %d' % (len(x[1]), len(y[1])), (x[0][0][:1], x[1], y[1]))
        elif any(abs(p - q) > 1e-4 for u, v in zip(x[1], y[1]) for cc, d in zip(u, v) for p, q in zip(cc, d)):
            uc['values'] += 1
            uex.setdefault('values', (x[0][0][:1], x[1], y[1]))
    for k, n in mc.most_common(10):
        print('material %-40s %6d  e.g. %s' % (k, n, str(mex[k])[:300]))
    for k, n in uc.most_common(10):
        print('uv       %-40s %6d  e.g. %s' % (k, n, str(uex[k])[:300]))


if __name__ == '__main__':
    main()
