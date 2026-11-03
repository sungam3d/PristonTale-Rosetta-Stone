"""Candidate centre points of stage maps, in game X / Z (= 3ds Max X / Y), to match sField[].SetCenterPos.

  python scripts/map_center.py <map.smd> ...
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim.smdfile import Stage   # noqa: E402

for p in sys.argv[1:]:
    st = Stage(p)
    used = sorted(set(v for f in st.faces for v in f[:3]))
    P = [st.positions[v] for v in used]
    allp = st.positions
    xs, ys = [q[0] for q in P], [q[1] for q in P]
    ax, ay = [q[0] for q in allp], [q[1] for q in allp]
    # face-area weighted centroid (XY plane)
    sa = sx = sy = 0.0
    for a, b, c, _m in st.faces:
        A, B, C = st.positions[a], st.positions[b], st.positions[c]
        ar = abs((B[0] - A[0]) * (C[1] - A[1]) - (C[0] - A[0]) * (B[1] - A[1])) / 2.0
        sa += ar
        sx += ar * (A[0] + B[0] + C[0]) / 3.0
        sy += ar * (A[1] + B[1] + C[1]) / 3.0
    print('%-18s box %.0f..%.0f  %.0f..%.0f' % (os.path.basename(p), min(xs), max(xs), min(ys), max(ys)))
    print('   bbox centre (used verts) %10.1f %10.1f' % ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    print('   bbox centre (all verts)  %10.1f %10.1f' % ((min(ax) + max(ax)) / 2, (min(ay) + max(ay)) / 2))
    print('   vertex mean              %10.1f %10.1f' % (sum(xs) / len(xs), sum(ys) / len(ys)))
    print('   area centroid            %10.1f %10.1f' % (sx / sa, sy / sa))
