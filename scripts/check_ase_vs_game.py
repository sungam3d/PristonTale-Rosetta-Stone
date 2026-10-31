"""Converter ASE posed with ase_pose.py vs the game's own math (game_pose.py), no 3D program involved.
Also compares every bone's world transform, to find the first bone that goes wrong.

  python scripts/check_ase_vs_game.py <file.ase> <file.smd> <file.smb> [frame ...]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ase_pose                       # noqa: E402
import game_pose                      # noqa: E402
from smdanim.smdfile import Model     # noqa: E402

ase, smd, smb = sys.argv[1:4]
frames = [float(f) for f in sys.argv[4:]] or [0.0]
rig = ase_pose.Rig(ase)
skel = Model(smb)
for fr in frames:
    tick = fr * 160.0
    a = rig.pose(tick)
    g = game_pose.posed_vertices(smd, smb, fr)
    n = min(len(a), len(g))
    d = np.linalg.norm(a[:n] - g[:n], axis=1)
    print('frame %6.1f  vertices %d/%d  error median %.4f  max %.4f' % (fr, len(a), len(g), np.median(d), d.max()))
    # bone world: game vs ase
    gw = {}
    for b in skel.objects:
        R, p = game_pose.bone_local(b, tick)
        if b.parent in gw:
            PR, Pp = gw[b.parent]
            R, p = R @ PR, p @ PR + Pp
        gw[b.name] = (R, p)
    shown = 0
    for b in skel.objects:
        if b.name not in rig.bones:
            continue
        R, t = rig.pose_bone(b.name, tick) if hasattr(rig, 'pose_bone') else (None, None)
        if R is None:
            break
        e = np.linalg.norm(t - gw[b.name][1]) + np.abs(R - gw[b.name][0]).max()
        if e > 0.05 and shown < 6:
            shown += 1
            print('   bone %-24s parent %-20s error %.3f  game pos %s  ase pos %s' % (
                b.name, b.parent, e, np.round(gw[b.name][1], 2), np.round(t, 2)))
