"""For a converted model: the bones whose ASE pose differs most from the game's, with the key
situation the game sees at that tick (to tell which engine rule the converter misses).

  python scripts/why_bone_off.py <model.smd> [frame ...]
"""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import ase_pose                                     # noqa: E402
import game_pose                                    # noqa: E402
from smdanim.smdfile import Model                   # noqa: E402
from smdanim.convert import Options, convert_file   # noqa: E402

f = sys.argv[1]
out = os.path.join(tempfile.mkdtemp(), 'x.ase')
sc = convert_file(f, out, Options(animation='embed'))
skel = Model(sc.rig.smb)
r = ase_pose.Rig(out)
frames = [float(a) for a in sys.argv[2:]] or sorted({int(m.start + (m.end - m.start) * 0.5) for m in sc.motions[:5]})
print('glued', game_pose.glued(skel.objects[0]), 'motions', [(m.name, m.start, m.end) for m in sc.motions][:6])
for fr in frames:
    t = fr * 160.0
    gw = game_pose.world_of(skel, t)
    rows = []
    for b in skel.objects:
        if b.name not in r.bones:
            continue
        la = r._local(r.bones[b.name], t)
        lg = game_pose.bone_local(b, t, {x.name: x for x in skel.objects})
        dl = float(np.abs(la[0] - lg[0]).max() + np.abs(la[1] - lg[1]).max())
        R, p = r.pose_bone(b.name, t)
        rows.append((dl, float(np.linalg.norm(p - gw[b.name][1])), b.name,
                     [game_pose.piece_range(b, w, t) for w in range(3)],
                     (len(b.rot_keys), len(b.pos_keys), len(b.scale_keys))))
    rows.sort(reverse=True)
    print('frame %s' % fr)
    for dl, dw, n, pr, kc in rows[:5]:
        print('   local diff %.4f  world pos diff %.3f  %-22s keys r/p/s %s  playing %s' % (dl, dw, n, kc, pr))
