"""What is under a point of a map: every face whose XY triangle contains (x, z), with its height,
slope and material flags (to check a SetCenterPos / arrival spot is standable).

  python scripts/floor_at.py <map.smd> x z [x z ...]
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim.smdfile import Stage   # noqa: E402

st = Stage(sys.argv[1])
pts = [(float(sys.argv[i]), float(sys.argv[i + 1])) for i in range(2, len(sys.argv) - 1, 2)]
for px, pz in pts:
    hits = []
    for a, b, c, m in st.faces:
        A, B, C = st.positions[a], st.positions[b], st.positions[c]
        d = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
        if abs(d) < 1e-9:
            continue
        l1 = ((B[1] - C[1]) * (px - C[0]) + (C[0] - B[0]) * (pz - C[1])) / d
        l2 = ((C[1] - A[1]) * (px - C[0]) + (A[0] - C[0]) * (pz - C[1])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) < 0:
            continue
        h = l1 * A[2] + l2 * B[2] + l3 * C[2]
        ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
        vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        slope = math.degrees(math.acos(min(1.0, abs(nz) / (math.sqrt(nx * nx + ny * ny + nz * nz) or 1))))
        mat = st.materials[m] if m < len(st.materials) else None
        tex = os.path.basename(mat.textures[0][0].replace(chr(92), '/')) if mat and mat.textures else '-'
        flags = ''.join(mat.flags) if mat else '?'
        hits.append((h, slope, tex, flags, mat.is_collision if mat else True))
    hits.sort(reverse=True)
    print('point %.0f %.0f: %d faces above/below' % (px, pz, len(hits)))
    for h, s, t, f, coll in hits[:8]:
        print('   height %8.1f  slope %4.0f deg  %-22s %s%s' % (h, s, t[:22], f, '  (collision/invisible)' if coll else ''))
