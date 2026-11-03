"""More centre candidates: floor faces only (normal pointing up), non-collision faces, walls only.

  python scripts/map_center2.py <map.smd> [targetX targetZ] ...
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim.smdfile import Stage   # noqa: E402

args = sys.argv[1:]
while args:
    p = args.pop(0)
    tgt = None
    if len(args) >= 2 and not args[0].lower().endswith('.smd'):
        tgt = (float(args.pop(0)), float(args.pop(0)))
    st = Stage(p)
    groups = {}
    for a, b, c, m in st.faces:
        A, B, C = st.positions[a], st.positions[b], st.positions[c]
        ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
        vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        upn = abs(nz) / ln
        mat = st.materials[m] if m < len(st.materials) else None
        coll = mat is None or mat.is_collision
        walk = mat is not None and (mat.use_state & 0x800)            # pass:
        nopass = mat is not None and (mat.use_state & 0x1000)         # notpass:
        keys = ['all']
        if not coll:
            keys.append('visible')
        if upn > 0.7 and not coll:
            keys.append('floor (visible, up-facing)')
        if coll:
            keys.append('collision only')
        if upn > 0.7 and coll:
            keys.append('collision floor')
        if nopass:
            keys.append('notpass')
        for k in keys:
            g = groups.setdefault(k, [1e18, 1e18, -1e18, -1e18, 0.0, 0.0, 0.0])
            for q in (A, B, C):
                g[0] = min(g[0], q[0]); g[1] = min(g[1], q[1]); g[2] = max(g[2], q[0]); g[3] = max(g[3], q[1])
            ar = ln / 2.0
            g[4] += ar; g[5] += ar * (A[0] + B[0] + C[0]) / 3; g[6] += ar * (A[1] + B[1] + C[1]) / 3
    print('== %s  target %s' % (os.path.basename(p), tgt))
    for k, g in groups.items():
        bc = ((g[0] + g[2]) / 2, (g[1] + g[3]) / 2)
        ac = (g[5] / g[4], g[6] / g[4]) if g[4] else (0, 0)
        d = lambda c: '' if tgt is None else '  off %6.0f %6.0f' % (c[0] - tgt[0], c[1] - tgt[1])
        print('   %-28s box centre %9.0f %9.0f%s | area centroid %9.0f %9.0f%s' % (k, bc[0], bc[1], d(bc), ac[0], ac[1], d(ac)))
