"""Animated map props (rigid objects with their own keys): every node's world transform from the
converted ASE (how ASE readers see it) vs the game's own maths, over the timeline.

  python scripts/check_props_vs_game.py <corpus Field dir> <game Field dir> [--max N]
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import ase_pose                                     # noqa: E402
import game_pose                                    # noqa: E402
from smdanim.aseparse import parse_ase, find_all    # noqa: E402
from smdanim.smdfile import Model, SMDError, file_kind   # noqa: E402

corpus, game = sys.argv[1:3]
limit = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else None


class Nodes(ase_pose.Rig):
    """ase_pose evaluation for every node of a file (meshes too, not only bones)."""
    def __init__(self, path):
        root = parse_ase(path)
        self.bones = {}
        for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
            b = ase_pose.Bone(g)
            self.bones.setdefault(b.name, b)
        self.meshes, self.verts, self.vbone = [], [], []


rows = []
n = 0
for d, _s, fs in os.walk(corpus):
    for f in fs:
        if not f.lower().endswith('.ase'):
            continue
        p = os.path.join(d, f)
        if b'*TM_ANIMATION' not in open(p, 'rb').read():
            continue
        smd = os.path.join(game, os.path.relpath(p, corpus)[:-4] + '.smd')
        if not os.path.isfile(smd) or file_kind(smd) != 'model':
            continue
        try:
            m = Model(smd)
        except SMDError:
            continue
        if any(o.physique for o in m.objects):
            continue                                # skinned (bones): covered by the character checks
        try:
            r = Nodes(p)
        except Exception:
            continue
        last = max([k[0] for o in m.objects for k in o.rot_keys + o.pos_keys + o.scale_keys] or [0])
        if not last:
            continue
        worst = 0.0
        for t in np.linspace(0, last, 9, endpoint=False):   # (the game never shows the exact last tick)
            gw = game_pose.world_of(m, float(t))
            for o in m.objects:
                if o.name not in r.bones:
                    continue
                R, pos = r.pose_bone(o.name, float(t))
                worst = max(worst, float(np.linalg.norm(pos - gw[o.name][1])),
                            float(np.abs(R - gw[o.name][0]).max()) * 10.0)
        rows.append((worst, os.path.relpath(p, corpus)))
        n += 1
        if limit and n >= limit:
            break
    if limit and n >= limit:
        break
rows.sort(reverse=True)
for w, nme in rows[:10]:
    print('%9.3f  %s' % (w, nme))
ws = np.array([r[0] for r in rows])
print('props %d   > 1: %d   > 0.1: %d   > 0.01: %d' % (len(rows), (ws > 1).sum(), (ws > 0.1).sum(), (ws > 0.01).sum()))
