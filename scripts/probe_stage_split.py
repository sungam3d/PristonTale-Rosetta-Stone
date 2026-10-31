"""Recover object boundaries from a stage .smd alone and score them against the original ASE.

A cut between face i-1 and i is possible when every vertex used before it is lower
than every vertex used from i on (the game appends each object's vertex list as is).

  python scripts/probe_stage_split.py <original.ASE> <stage.smd>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.smdfile import Stage                                       # noqa: E402

root = parse_ase(sys.argv[1])
st = Stage(sys.argv[2])
true_cuts = set()
f0 = 0
for g in find_all(root, '*GEOMOBJECT'):
    m = find(g, '*MESH')
    if m is not None:
        f0 += int(val(m, '*MESH_NUMFACES', 0))
        true_cuts.add(f0)
true_cuts.discard(f0)
n = len(st.faces)
suf = [0] * (n + 1)
suf[n] = 1 << 30
for i in range(n - 1, -1, -1):
    a, b, c, _ = st.faces[i]
    suf[i] = min(suf[i + 1], a, b, c)
cuts = set()
hi = -1
for i in range(1, n):
    a, b, c, _ = st.faces[i - 1]
    hi = max(hi, a, b, c)
    if hi < suf[i]:
        cuts.add(i)
print('objects', len(true_cuts) + 1, 'possible cuts', len(cuts), 'true cuts found', len(true_cuts & cuts),
      'missed', len(true_cuts - cuts))
