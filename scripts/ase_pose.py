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
import os
import re
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
        self.mesh = find(g, '*MATERIAL_REF') is not None      # a drawn object, not a bone
        # what the game uses for a channel without keys: TM_POS / TM_ROTAXIS + TM_ROTANGLE, which
        # 3ds Max writes relative to the parent (used when the file has them that way: a root
        # node, or TM_POS away from TM_ROW3; never for a mirrored node)
        self.static = None
        if tm is not None and val(tm, '*TM_POS') is not None and val(tm, '*TM_ROTANGLE') is not None:
            tp = np.array(_fl(val(tm, '*TM_POS', '0 0 0'), 3))
            if not self.parent or np.abs(tp - self.t).max() > 0.01:
                ax = np.array(_fl(val(tm, '*TM_ROTAXIS', '0 0 1'), 3))
                n = np.linalg.norm(ax)
                rot = _std(ax / n, _fl(val(tm, '*TM_ROTANGLE', '0'), 1)[0]) if n > 1e-9 else np.eye(3)
                self.static = (rot, tp)
        self.pos, self.rot, self.scl = [], [], []
        a = find(g, '*TM_ANIMATION')
        if a is not None:
            # the key lines the game's ASE reader takes (smRead3d.cpp): samples and 3ds Max
            # TCB / Bezier keys alike, first 4 or 5 numbers
            rows = np.eye(3)
            for blk in a[2] or ():
                for c in blk[2] or ():
                    if c[0] in ('*CONTROL_POS_SAMPLE', '*CONTROL_TCB_POS_KEY', '*CONTROL_BEZIER_POS_KEY'):
                        f = _fl(c[1], 4)
                        self.pos.append((f[0], np.array(f[1:4])))
                    elif c[0] in ('*CONTROL_SCALE_SAMPLE', '*CONTROL_TCB_SCALE_KEY', '*CONTROL_BEZIER_SCALE_KEY'):
                        f = _fl(c[1], 4)
                        self.scl.append((f[0], np.array(f[1:4])))
                    elif c[0] in ('*CONTROL_ROT_SAMPLE', '*CONTROL_TCB_ROT_KEY'):
                        f = _fl(c[1], 5)
                        ax = np.array(f[1:4])
                        n = np.linalg.norm(ax)
                        ax = ax / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])
                        # in between keys the game blends towards the key's turn (a slerp from a
                        # zero quaternion, smObj3d GetRotFrame): the short way round, so a turn
                        # of 5.94 rad about -z (as 3ds Max writes a windmill) is 0.34 about +z
                        ang = math.remainder(f[4], 2.0 * math.pi)
                        rows = rows @ _std(ax, ang)
                        self.rot.append((f[0], rows.copy(), ax, ang))


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
        # per skinned mesh: (name, first vertex, vertex count, corners) - corners = vertex index of
        # every corner of the faces with three different vertices (the ones every importer keeps)
        self.parts = []
        for g in self.meshes:
            fl = find(find(g, '*MESH'), '*MESH_FACE_LIST')
            corners = []
            for c in (fl[2] if fl is not None else None) or []:
                m = re.search(r'A:\s*(\d+)\s+B:\s*(\d+)\s+C:\s*(\d+)', c[1])
                if m and len(set(m.groups())) == 3:
                    corners += [len(self.verts) + int(x) for x in m.groups()]
            vl = find(find(g, '*MESH'), '*MESH_VERTEX_LIST')[2] or []
            self.parts.append((unquote(val(g, '*NODE_NAME', '')), len(self.verts), len(vl), corners))
            vs = [np.array(_fl(c[1], 4)[1:4]) for c in vl]
            names = [''] * len(vs)
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bltest'))
            from asecheck import read_physique          # the game's reading of *PHYSIQUE
            for i, bn in read_physique(find(g, '*PHYSIQUE')).items():
                if 0 <= i < len(names):
                    names[i] = bn
            self.verts += vs
            self.vbone += names

    def _local(self, b, tick):
        p = self.bones.get(b.parent)
        if p is not None:
            rest = b.R @ np.linalg.inv(p.R)                      # rest local rows
            rest_t = (b.t - p.t) @ np.linalg.inv(p.R)
        else:
            rest, rest_t = b.R, b.t
        rest_r = rest / np.linalg.norm(rest, axis=1)[:, None]
        if b.static is not None and np.linalg.det(rest) > 0:
            rest_r, rest_t = b.static
        elif b.mesh and np.linalg.det(rest) < 0:
            rest_r = -rest_r        # mirrored: a proper rotation next to the negative scale below
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
            R = rest_r

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
        # no scale keys: a drawn object keeps its resting scale (3ds Max; the game bakes it into
        # the mesh, smOBJ3D::ReformTM); a bone has none (the game applies no scale)
        # (a mirrored node: 3ds Max keeps the mirror as a negative scale next to its rotation)
        s = lerp(b.scl, np.linalg.norm(rest, axis=1) * np.sign(np.linalg.det(rest)) if b.mesh else np.ones(3))
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
