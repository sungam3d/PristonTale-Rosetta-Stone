"""The game's own pose math (reference for importer tests).

posed_vertices(smd, smb, frame) -> numpy array of skinned vertex world positions, computed
the way Priston Tale does it: keys of the playing motion piece only, cached rotation at the
previous key turned by the given fraction of the next key's delta, linear positions, static
transform for pieces without keys; vertex = bone-local vertex x bone world matrix.
"""
import math
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model          # noqa: E402


def qmat_rows(x, y, z, w):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])


def glued(o):
    """A glued motion file (several motion ASEs end to end, smOBJ3D TmFrameCnt > 0): every .smb
    has the piece tables, only glued ones have pieces with a length (as convert._pieces)."""
    return bool(o.frames and o.frames[0] and any(e > s and s >= 0 for s, e, _i, _n in o.frames[0]))


def piece_range(o, which, tick):
    """smOBJ3D::GetTmFrameRot/Pos/Scale: the keys of the motion piece playing at `tick`, but only
    a piece that has keys for this channel.  Single-timeline files: all keys, but only while the
    tick is before the channel's last key (from the last key on the game shows the static value).
    (-1, -1) = no keys apply."""
    keys = [o.rot_keys, o.pos_keys, o.scale_keys][which]
    if glued(o):
        for s, e, idx, n in o.frames[which]:
            if n > 0 and s <= tick < e:
                return idx, idx + n
        return -1, -1
    if keys and keys[-1][0] > tick:
        return 0, len(keys)
    return -1, -1


def _tm_local(o, by_name):
    """Tm x parent->TmInvert (8.8 world matrices): what the game shows for a bone without keys."""
    Tm = np.array(o.tm, dtype=float) / 256.0
    p = by_name.get(o.parent) if by_name else None
    if p is not None:
        Tm = Tm @ (np.array(p.tminv, dtype=float) / 256.0)
    return Tm[:3, :3], Tm[3, :3]


def bone_local(o, tick, by_name=None):
    """Local (parent-relative) rows and position of a bone at `tick`, as smOBJ3D::TmAnimation
    computes them."""
    rlo, rhi = piece_range(o, 0, tick)
    plo, phi = piece_range(o, 1, tick)
    slo, shi = piece_range(o, 2, tick)
    if glued(o):
        keyed = rlo >= 0 or plo >= 0 or slo > 0            # (the game tests the scale index with > 0)
    else:
        keyed = bool(o.rot_keys or o.pos_keys or o.scale_keys)
    if not keyed:
        return _tm_local(o, by_name)
    lo, hi = rlo, rhi
    if hi > lo:
        acc = [(o.rot_keys[k][0], np.array(o.prev_rot[k], dtype=float).reshape(4, 4)[:3, :3]) for k in range(lo, hi)]
        i = max([k for k, (t, _q) in enumerate(acc) if t <= tick] or [0])
        R = acc[i][1]
        if i + 1 < len(acc) and acc[i][0] <= tick < acc[i + 1][0]:
            f = (tick - acc[i][0]) / float(acc[i + 1][0] - acc[i][0])
            _t, x, y, z, w = o.rot_keys[lo + i + 1]
            if w < 0.0:
                x, y, z, w = -x, -y, -z, -w
            s = math.sqrt(x * x + y * y + z * z)
            if s > 1e-12:
                h = math.atan2(s, w) * f
                k = math.sin(h) / s
                R = R @ qmat_rows(x * k, y * k, z * k, math.cos(h)).T
    else:
        R = qmat_rows(*o.quat).T

    def interp(which, keys, default):
        lo, hi = piece_range(o, which, tick)
        keys = keys[lo:hi] if lo >= 0 else []
        if not keys:
            return np.array(default, dtype=float)
        i = max([k for k, kk in enumerate(keys) if kk[0] <= tick] or [0])
        a = np.array(keys[i][1:4], dtype=float)
        if i + 1 < len(keys) and keys[i][0] <= tick:
            b = np.array(keys[i + 1][1:4], dtype=float)
            return a + (b - a) * (tick - keys[i][0]) / float(keys[i + 1][0] - keys[i][0])
        return a
    # no scale keys playing: the game applies no scale at all
    return np.diag(interp(2, o.scale_keys, (1.0, 1.0, 1.0))) @ R, interp(1, o.pos_keys, o.pos)


def world_of(skel, tick):
    """{bone: (world rows, world position)} of a skeleton at `tick`."""
    by_name = {b.name: b for b in skel.objects}
    world = {}
    for b in skel.objects:
        R, p = bone_local(b, tick, by_name)
        if b.parent in world:
            PR, Pp = world[b.parent]
            R, p = R @ PR, p @ PR + Pp
        world[b.name] = (R, p)
    return world


def posed_vertices(smd, smb, frame):
    skel, mesh = Model(smb), Model(smd)
    tick = frame * 160.0
    world = {}
    by_name = {b.name: b for b in skel.objects}
    for b in skel.objects:
        R, p = bone_local(b, tick, by_name)
        if b.parent in world:
            PR, Pp = world[b.parent]
            R, p = R @ PR, p @ PR + Pp
        world[b.name] = (R, p)
    out = []
    for o in mesh.objects:
        if o.physique:
            for lv, bn in zip(o.local_verts, o.physique):
                if bn in world:
                    R, p = world[bn]
                    out.append(np.array(lv) @ R + p)
                else:
                    out.append(np.array([np.nan] * 3))
    return np.array(out)


def posed_vertices_for(smd, smb, frame, names):
    """Like posed_vertices, but only the meshes `names` (in this order; a name used several times
    takes the next mesh of that name) - the skinned meshes a converted ASE contains, which leaves
    out the lower detail levels."""
    skel, mesh = Model(smb), Model(smd)
    world = world_of(skel, frame * 160.0)
    by = {}
    for o in mesh.objects:
        if o.physique:
            by.setdefault(o.name, []).append(o)
    nth = {}
    out = []
    for nm in names:
        k = nth.get(nm, 0)
        nth[nm] = k + 1
        lst = by.get(nm, [])
        if k >= len(lst):
            continue
        for lv, bn in zip(lst[k].local_verts, lst[k].physique):
            out.append(np.array(lv) @ world[bn][0] + world[bn][1] if bn in world else np.array([np.nan] * 3))
    return np.array(out)
