"""Does composing the animation keys at a frame reproduce the stored bind pose (frame 0)?"""
import os, sys
import numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
from smdanim.convert import _model_world


def qmat(x, y, z, w):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])


def local_at(o, tick):
    """Local (parent-relative) rows + translation of a bone at a tick, from its keys."""
    R = qmat(*o.quat).T                     # static local rotation when there are no keys
    if o.rot_keys:
        R = np.eye(3)
        for i, (t, x, y, z, w) in enumerate(o.rot_keys):
            if t > tick and i > 0:          # the first key always applies (it is absolute)
                break
            R = R @ qmat(x, y, z, w).T
    p = np.array(o.pos)
    if o.pos_keys:
        cand = [k for k in o.pos_keys if k[0] <= tick] or o.pos_keys[:1]
        p = np.array(cand[-1][1:4])
    s = np.array(o.scale)
    if o.scale_keys:
        cand = [k for k in o.scale_keys if k[0] <= tick] or o.scale_keys[:1]
        s = np.array(cand[-1][1:4])
    return np.diag(s) @ R, p


for path in [r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\monster\Tees\Tees.smb',
             r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD\m1.smb']:
    m = Model(path)
    world = {}
    worst_r = worst_t = 0.0
    for o in m.objects:
        R, p = local_at(o, 0)
        if o.parent in world:
            PR, Pp = world[o.parent]
            R, p = R @ PR, p @ PR + Pp
        world[o.name] = (R, p)
        br, bt = _model_world(o)
        worst_r = max(worst_r, np.abs(R - np.array(br)).max())
        worst_t = max(worst_t, np.abs(p - np.array(bt)).max())
    print('%-10s bones %3d  frame-0 pose vs stored bind pose: rotation err %.4f, position err %.4f'
          % (os.path.basename(path), len(m.objects), worst_r, worst_t))
