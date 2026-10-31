"""Pose any PT character/monster ASE the way the game does, in numpy doubles.

    rest   : bone NODE_TM rows (world), skinned mesh vertices (world, rest pose), *PHYSIQUE
    keys   : CONTROL_POS_SAMPLE (parent-relative), CONTROL_ROT_SAMPLE (turn from the previous
             key, axis+angle, first absolute; in between: that fraction of the next key's turn),
             CONTROL_SCALE_SAMPLE
    vertex : v(t) = (v_rest - bind_t) @ inv(bind_R) @ R_world(t) + t_world(t)

Used to prove round trips: converter ASE -> import -> export -> same poses.
"""
import bisect
import math
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402


def _fl(s, n):
    out = []
    for t in s.split():
        try:
            out.append(float(t))
        except ValueError:
            out.append(0.0)
    return (out + [0.0] * n)[:n]


def _std(axis, ang):
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


class Bone(object):
    def __init__(self, g):
        self.name = unquote(val(g, '*NODE_NAME', ''))
        self.parent = unquote(val(g, '*NODE_PARENT', ''))
        tm = find(g, '*NODE_TM')
        r = [_fl(val(tm, k, '0 0 0'), 3) for k in ('*TM_ROW0', '*TM_ROW1', '*TM_ROW2', '*TM_ROW3')]
        self.R = np.array(r[:3])
        self.t = np.array(r[3])
        self.pos, self.rot, self.scl = [], [], []
        a = find(g, '*TM_ANIMATION')
        if a is not None:
            for blk in a[2] or ():
                if blk[0] == '*CONTROL_POS_TRACK':
                    self.pos = [(f[0], np.array(f[1:4])) for f in (_fl(c[1], 4) for c in blk[2] or ())]
                elif blk[0] == '*CONTROL_SCALE_TRACK':
                    self.scl = [(f[0], np.array(f[1:4])) for f in (_fl(c[1], 4) for c in blk[2] or ())]
                elif blk[0] == '*CONTROL_ROT_TRACK':
                    rows = np.eye(3)
                    for c in blk[2] or ():
                        f = _fl(c[1], 5)
                        ax = np.array(f[1:4])
                        n = np.linalg.norm(ax)
                        ax = ax / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])
                        rows = rows @ _std(ax, f[4])
                        self.rot.append((f[0], rows.copy(), ax, f[4]))


class Rig(object):
    def __init__(self, path, anim_path=None):
        root = parse_ase(path)
        nodes = find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT')
        self.meshes = [g for g in nodes if find(g, '*PHYSIQUE') is not None]
        self.bones = {}
        for g in nodes:
            if find(g, '*PHYSIQUE') is None and (g[0] == '*HELPEROBJECT' or find(g, '*MATERIAL_REF') is None):
                b = Bone(g)
                self.bones[b.name] = b
        if anim_path:                                   # keys from a separate (shared) motions file
            for g in find_all(parse_ase(anim_path), '*GEOMOBJECT') + find_all(parse_ase(anim_path), '*HELPEROBJECT'):
                b = Bone(g)
                if b.name in self.bones:
                    o = self.bones[b.name]
                    o.pos, o.rot, o.scl = b.pos, b.rot, b.scl
        self.verts, self.vbone = [], []
        for g in self.meshes:
            vl = find(find(g, '*MESH'), '*MESH_VERTEX_LIST')[2] or []
            vs = [np.array(_fl(c[1], 4)[1:4]) for c in vl]
            names = [''] * len(vs)
            for c in find(g, '*PHYSIQUE')[2] or ():
                if c[0].startswith('*PHYSIQUE_VERTEXASSIGNMENT'):
                    i, bn = c[1].split(None, 1)
                    names[int(i)] = bn.strip().strip('"')
            self.verts += vs
            self.vbone += names

    def _local(self, b, tick):
        p = self.bones.get(b.parent)
        if p is not None:
            rest = b.R @ np.linalg.inv(p.R)                      # rest local rows
            rest_t = (b.t - p.t) @ np.linalg.inv(p.R)
        else:
            rest, rest_t = b.R, b.t
        # rotation
        if b.rot:
            ts = [k[0] for k in b.rot]
            i = bisect.bisect_right(ts, tick) - 1
            if i < 0:
                R = b.rot[0][1]
            else:
                R = b.rot[i][1]
                if i + 1 < len(b.rot) and b.rot[i + 1][0] > b.rot[i][0]:
                    f = (tick - b.rot[i][0]) / (b.rot[i + 1][0] - b.rot[i][0])
                    R = R @ _std(b.rot[i + 1][2], b.rot[i + 1][3] * f)
        else:
            R = rest / np.linalg.norm(rest, axis=1)[:, None]

        def lerp(keys, default):
            if not keys:
                return default
            ts = [k[0] for k in keys]
            i = bisect.bisect_right(ts, tick) - 1
            if i < 0:
                return keys[0][1]
            if i + 1 < len(keys) and keys[i + 1][0] > keys[i][0]:
                f = (tick - keys[i][0]) / (keys[i + 1][0] - keys[i][0])
                return keys[i][1] + (keys[i + 1][1] - keys[i][1]) * f
            return keys[i][1]
        t = lerp(b.pos, rest_t)
        s = lerp(b.scl, np.ones(3))
        return np.diag(s) @ R, t

    def pose_bone(self, name, tick):
        """World (rows, translation) of one bone at a tick."""
        b = self.bones[name]
        R, t = self._local(b, tick)
        if b.parent in self.bones:
            PR, Pt = self.pose_bone(b.parent, tick)
            R, t = R @ PR, t @ PR + Pt
        return R, t

    def pose(self, tick):
        world = {}

        def W(name):
            if name in world:
                return world[name]
            b = self.bones[name]
            R, t = self._local(b, tick)
            if b.parent in self.bones:
                PR, Pt = W(b.parent)
                R, t = R @ PR, t @ PR + Pt
            world[name] = (R, t)
            return world[name]
        out = []
        for v, bn in zip(self.verts, self.vbone):
            if bn not in self.bones:
                out.append(v)
                continue
            b = self.bones[bn]
            local = (v - b.t) @ np.linalg.inv(b.R)
            R, t = W(bn)
            out.append(local @ R + t)
        return np.array(out)
