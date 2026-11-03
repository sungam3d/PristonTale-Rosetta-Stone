"""How far the resting offset a reader rebuilds from the bones' world matrices (what an ASE
without position keys implies) is from the offset the game stores and uses (smb object pos),
for animated bones that have no position keys.

  python scripts/survey_static_pos.py <char folder>
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim.smdfile import Model, SMDError     # noqa: E402
from smdanim.convert import _model_world        # noqa: E402

rows = []
for d, _s, fs in os.walk(sys.argv[1]):
    for f in fs:
        if not f.lower().endswith('.smb'):
            continue
        p = os.path.join(d, f)
        try:
            m = Model(p)
        except (SMDError, Exception):
            continue
        world = {}
        for o in m.objects:
            R, t = _model_world(o)
            world[o.name] = (np.array(R), np.array(t))
        worst, n = 0.0, 0
        for o in m.objects:
            if o.pos_keys or not o.rot_keys or o.parent not in world:
                continue
            R, t = world[o.name]
            PR, Pt = world[o.parent]
            rest_t = (t - Pt) @ np.linalg.inv(PR)
            e = float(np.abs(rest_t - np.array(o.pos)).max())
            worst = max(worst, e)
            n += 1
        if n:
            rows.append((worst, n, os.path.relpath(p, sys.argv[1])))
rows.sort(reverse=True)
for r in rows[:12]:
    print('%8.3f  %3d bones  %s' % r)
print('skeletons %d; worst > 0.05: %d, > 0.01: %d' % (len(rows), sum(1 for r in rows if r[0] > 0.05),
                                                     sum(1 for r in rows if r[0] > 0.01)))
