"""Skeletons, skinning and animation for Priston Tale character / monster ASE files.

How the game animates a model (and how this maps to Blender)
  * Bones are Bip01 helpers/meshes with a bind-pose NODE_TM (world space).
    -> one Armature; every bone's rest matrix is its bind TM.
  * A skinned mesh has a *PHYSIQUE block: each vertex follows exactly one bone
    (rigid skinning).  -> one vertex group per bone, weight 1, Armature modifier.
  * *TM_ANIMATION per bone (3ds Max ASE convention):
        CONTROL_POS_SAMPLE  tick x y z        position relative to the parent
        CONTROL_ROT_SAMPLE  tick ax ay az ang rotation DELTA from the previous key
                                              (the first key is absolute)
        CONTROL_SCALE_SAMPLE tick sx sy sz ...
    The game interpolates linearly / by slerp between keys, 160 ticks a frame,
    30 frames a second.  -> one Action with linear keys on the pose bones.
  * *PT_ANIMATION (written by char2ase) names the skeleton, an optional shared
    animation file (m1_motions.ase for player classes) and the motion list
    (walk, attack ...) on the timeline.  -> timeline markers + "PT Motions" panel.
"""

import bisect
import re
import json
import math
import os

import bpy
from mathutils import Matrix, Quaternion, Vector

from .aseparse import parse_ase, find, find_all, val, unquote

TICKS = 160.0
# animation key lines the game's ASE reader accepts (smRead3d.cpp)
POS_KEYS = ('*CONTROL_POS_SAMPLE', '*CONTROL_TCB_POS_KEY', '*CONTROL_BEZIER_POS_KEY')
ROT_KEYS = ('*CONTROL_ROT_SAMPLE', '*CONTROL_TCB_ROT_KEY')
SCALE_KEYS = ('*CONTROL_SCALE_SAMPLE', '*CONTROL_TCB_SCALE_KEY', '*CONTROL_BEZIER_SCALE_KEY')
# Blender bones point along their local Y axis, Biped bones along local X.
AXIS = Matrix(((0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
AXIS_INV = AXIS.inverted()
# A bone pointing (nearly) along -Y: Blender's bone roll is ill-conditioned there, and far from the
# origin, where head and tail are coarse 32-bit floats, Bip helpers of map props came out 13
# degrees off.  Such bones point the other way (Blender Y = -3ds Max X); see bone_axes().
AXIS_FLIP = AXIS @ Matrix.Diagonal((-1.0, -1.0, 1.0, 1.0))


def bone_axes(arm_ob):
    """{bone: 3ds Max bone axes -> Blender bone axes} (AXIS, or AXIS_FLIP for the flipped bones)."""
    flipped = set(json.loads(arm_ob.get('pt_axis_flip', '[]'))) if arm_ob is not None else set()
    return {b.name: (AXIS_FLIP if b.name in flipped else AXIS) for b in arm_ob.data.bones} if arm_ob else {}


def _floats(s):
    out = []
    for t in s.split():
        try:
            out.append(float(t))
        except ValueError:
            out.append(0.0)
    return out


def _nodes(root):
    out = []
    for c in root[2] or ():
        if c[0] in ('*GEOMOBJECT', '*HELPEROBJECT'):
            out.append(c)
        elif c[0] == '*GROUP':
            out.extend(_nodes(c))
    return out


def _name(node):
    return unquote(val(node, '*NODE_NAME', ''))


def _parent(node):
    return unquote(val(node, '*NODE_PARENT', ''))


def _world(node):
    tm = find(node, '*NODE_TM')
    r = [_floats(val(tm, k, d)) for k, d in (('*TM_ROW0', '1 0 0'), ('*TM_ROW1', '0 1 0'),
                                             ('*TM_ROW2', '0 0 1'), ('*TM_ROW3', '0 0 0'))] if tm else \
        [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]]
    return Matrix(((r[0][0], r[1][0], r[2][0], r[3][0]),
                   (r[0][1], r[1][1], r[2][1], r[3][1]),
                   (r[0][2], r[1][2], r[2][2], r[3][2]),
                   (0.0, 0.0, 0.0, 1.0)))


def _ortho(m):
    """Rigid part of a TM (PT stores bind poses in 8.8 fixed point, so they are
    a hair off orthonormal; Blender bones must be exactly rigid)."""
    loc, rot, _sc = m.decompose()
    rot.normalize()                 # decompose() leaves it un-normalised for skewed matrices
    return Matrix.LocRotScale(loc, rot, None)


def physique(node):
    """Per-vertex bone names of a skinned mesh, or None."""
    ph = find(node, '*PHYSIQUE')
    if ph is None:
        return None
    # as the game's ASE reader (smRead3d.cpp): line by line at any depth (3ds Max nests them in
    # *PHYSIQUE_VERTEXASSIGNMENT_LIST); a blended vertex takes the node listed first (number 0)
    out = {}
    blended = [None]

    def walk(n):
        for c in n[2] or ():
            key = c[0]
            if key == '*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE':
                p = c[1].split(None, 1)
                if len(p) == 2:
                    try:
                        out[int(p[0])] = p[1].strip().strip('"')
                    except ValueError:
                        pass
            elif key == '*PHYSIQUE_VERTEXASSIGNMENT_BLENDED_RIGIDTYPE':
                try:
                    blended[0] = int(c[1].split()[0])
                except (ValueError, IndexError):
                    blended[0] = None
            elif key == '*PHYSIQUE_VERTEXASSIGNMENT_NODE' and blended[0] is not None:
                p = c[1].split(None, 2)
                if len(p) == 3 and p[0] == '0':
                    out[blended[0]] = p[2].strip().strip('"')
            if c[2]:
                walk(c)
    walk(ph)
    return out


def pt_animation(root):
    """(skeleton, animation_file, [(name, start, end, loop)]) from *PT_ANIMATION."""
    blk = find(root, '*PT_ANIMATION')
    if blk is None:
        return None
    motions = []
    for c in blk[2] or ():
        if c[0] == '*PT_MOTION':
            s = c[1]
            q = s.split('"')
            if len(q) >= 3:
                nums = q[2].split()
                if len(nums) >= 2:
                    motions.append((q[1], int(nums[0]), int(nums[1]), len(nums) > 2 and nums[2] == '1'))
    return (unquote(val(blk, '*PT_SKELETON', '')), unquote(val(blk, '*PT_ANIMATION_FILE', '')), motions)


def separate_motion_file(root):
    """Name of the game's separate motion file of a monster (*PT_MOTION_FILE), or ''."""
    blk = find(root, '*PT_ANIMATION')
    return unquote(val(blk, '*PT_MOTION_FILE', '')) if blk is not None else ''


def is_character(root):
    """True for skinned characters/monsters and pure motion files."""
    if find(root, '*PT_ANIMATION') is not None:
        return True
    nodes = _nodes(root)
    if any(find(n, '*PHYSIQUE') is not None for n in nodes):
        return True
    animated = [n for n in nodes if find(n, '*TM_ANIMATION') is not None]
    return bool(animated) and all(_name(n).lower().startswith('bip') for n in animated)


def bone_nodes(root):
    """Nodes that are skeleton bones (everything that is not a skinned mesh or a
    rigid mesh attached to a bone)."""
    nodes = _nodes(root)
    used = set()
    for n in nodes:
        ph = physique(n)
        if ph:
            used.update(ph.values())
    by_name = {_name(n): n for n in nodes}
    bones = set()
    for n in nodes:
        nm = _name(n)
        if find(n, '*PHYSIQUE') is not None:
            continue
        if (n[0] == '*HELPEROBJECT' or nm in used or nm.lower().startswith('bip')
                or find(n, '*TM_ANIMATION') is not None and find(n, '*MESH') is None
                or find(n, '*MATERIAL_REF') is None):         # PT bones are meshes without a material
            bones.add(nm)
    # parents of bones are bones too
    for nm in list(bones):
        p = _parent(by_name[nm])
        while p and p in by_name and p not in bones:
            bones.add(p)
            p = _parent(by_name[p])
    return [n for n in nodes if _name(n) in bones]


# --------------------------------------------------------------------------- armature
def _rows12(node):
    """The NODE_TM rows exactly as written (Python doubles), for an exact export later."""
    tm = find(node, '*NODE_TM')
    if tm is None:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    out = []
    for k, d in (('*TM_ROW0', '1 0 0'), ('*TM_ROW1', '0 1 0'), ('*TM_ROW2', '0 0 1'), ('*TM_ROW3', '0 0 0')):
        out += (_floats(val(tm, k, d)) + [0.0, 0.0, 0.0])[:3]
    return out


def bind_from(root):
    """{bone: (world bind matrix, parent name, exact rows)} of every node in an ASE tree (a motions file)."""
    return {_name(n): (_world(n), _parent(n), _rows12(n)) for n in _nodes(root)}


def build_armature(context, coll, name, bones, root_empty, bind_override=None):
    """Armature whose rest pose is the bind pose of `bones` (ASE nodes); bones named in
    bind_override (world matrices) take their rest pose from there instead."""
    bind_override = bind_override or {}
    arm = bpy.data.armatures.new(name)
    arm.display_type = 'STICK'
    ob = bpy.data.objects.new(name, arm)
    ob.show_in_front = True
    coll.objects.link(ob)
    ob.parent = root_empty
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = Matrix.Identity(4)

    own = {_name(n): _ortho(_world(n)) for n in bones}
    own_parent = {_name(n): _parent(n) for n in bones}
    names = [_name(n) for n in bones]
    # bones in the override follow its hierarchy too (keys are relative to the parent, and
    # some costume files hang a bone off a different parent than the game skeleton does)
    parent = {nm: (bind_override[nm][1] if nm in bind_override and bind_override[nm][1] in own
                   else own_parent[nm]) for nm in names}
    world = {}

    def place(nm):
        # bones in the override take its rest pose; any other bone keeps its offset from its
        # parent, so extra costume bones (hair, tails) stay attached when the parent moves
        if nm in world:
            return world[nm]
        p = parent[nm]
        if nm in bind_override:
            world[nm] = _ortho(bind_override[nm][0])
        elif p in own and bind_override:
            world[nm] = place(p) @ (own[p].inverted() @ own[nm])
        else:
            world[nm] = own[nm]
        return world[nm]
    for nm in names:
        place(nm)
    heads = {nm: world[nm].translation for nm in names}
    children = {}
    for nm in names:
        p = parent[nm]
        if p in world:
            children.setdefault(p, []).append(nm)
    length = {}
    for nm in names:
        d = [(heads[c] - heads[nm]).length for c in children.get(nm, ())]
        d = [x for x in d if x > 0.05]
        length[nm] = min(d) if d else 0.0
    for nm in names:
        if length[nm] <= 0.0:
            p = parent[nm]
            length[nm] = max(0.3, 0.5 * length.get(p, 0.0) if p in length else 2.0)
    # weapon / effect attachment bones can have their only child far away: keep every
    # bone short relative to the whole skeleton so the rig stays readable
    if heads:
        lo = [min(h[i] for h in heads.values()) for i in range(3)]
        hi = [max(h[i] for h in heads.values()) for i in range(3)]
        cap = max(1.0, 0.12 * max(hi[i] - lo[i] for i in range(3)))
        for nm in names:
            length[nm] = min(length[nm], cap)
    # Blender keeps head and tail in 32-bit floats: a bone's direction is good to a float step of
    # its position (0.004 at the 40000 of a map prop) over its length, so far from the origin
    # bones are made long enough for 0.0003 rad
    for nm in names:
        length[nm] = max(length[nm], 5e-4 * max(abs(heads[nm][i]) for i in range(3)))
    flipped = [nm for nm in names if world[nm].col[0].xyz.normalized().y < -0.99]

    prev_active = context.view_layer.objects.active
    context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    ebs = arm.edit_bones
    for nm in names:
        eb = ebs.new(nm)
        eb.head = (0.0, 0.0, 0.0)
        eb.tail = (0.0, length[nm], 0.0)
        eb.matrix = world[nm] @ (AXIS_FLIP if nm in flipped else AXIS)
    for nm in names:
        p = parent[nm]
        if p in world:
            ebs[nm].parent = ebs[p]
            ebs[nm].use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    ob.select_set(False)
    context.view_layer.objects.active = prev_active
    ob['pt_bind'] = json.dumps({nm: [list(r) for r in world[nm]] for nm in names})
    ob['pt_axis_flip'] = json.dumps(sorted(flipped))
    # the rest pose exactly as written in the file, so an untouched bone exports back unchanged
    raw = {}
    own_raw = {_name(n): _rows12(n) for n in bones}
    for nm in names:
        if nm in bind_override:
            raw[nm] = bind_override[nm][2]
        elif not bind_override or parent[nm] not in own:
            raw[nm] = own_raw[nm]
    ob['pt_bind_raw'] = json.dumps(raw)
    return ob, world, parent


def skin_mesh(mesh_ob, arm_ob, assign):
    """Vertex groups (one bone per vertex) + Armature modifier."""
    groups = {}
    assign = dict(assign)
    dup = list(mesh_ob.get('ase_dup_src', []))
    for k in range(0, len(dup), 2):               # vertex copies made for doubled faces keep their bone
        if dup[k + 1] in assign:
            assign[dup[k]] = assign[dup[k + 1]]
    for vi, bn in assign.items():
        if bn:
            groups.setdefault(bn, []).append(vi)
    for bn, idx in groups.items():
        vg = mesh_ob.vertex_groups.get(bn) or mesh_ob.vertex_groups.new(name=bn)
        vg.add(idx, 1.0, 'REPLACE')
    mod = mesh_ob.modifiers.new('Armature', 'ARMATURE')
    mod.object = arm_ob
    mod.use_vertex_groups = True
    mod.use_deform_preserve_volume = False
    return assign


# --------------------------------------------------------------------------- animation
def _qmat_rows(ax, ay, az, ang):
    """Rotation of one ASE CONTROL_ROT_SAMPLE as the game builds it (row-vector form)."""
    h = ang * 0.5
    s = math.sin(h)
    x, y, z, w = ax * s, ay * s, az * s, math.cos(h)
    return Matrix(((1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
                   (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
                   (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y))))


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 0.0, 1.0)


def _qaxis(axis, ang):
    """(w, x, y, z) for a turn of `ang` radians about unit `axis`."""
    s = math.sin(0.5 * ang)
    return (math.cos(0.5 * ang), axis[0] * s, axis[1] * s, axis[2] * s)


def _qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def _qnorm(q):
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


class Track(object):
    """Keys of one node, evaluated in parent-relative (local) space."""

    def __init__(self, node):
        a = find(node, '*TM_ANIMATION')
        self.pos = []
        self.rot = []
        self.scl = []
        # what the game uses for a channel without keys (smRead3d.cpp): TM_POS / TM_ROTAXIS +
        # TM_ROTANGLE, which 3ds Max writes relative to the parent (the rows are world space,
        # rounded: a helper scaled to 0.017 is far off there).  Taken when the file has them that
        # way (a root node, or TM_POS away from TM_ROW3); see static().
        self._static = None
        tm = find(node, '*NODE_TM')
        if tm is not None and val(tm, '*TM_POS') is not None and val(tm, '*TM_ROTANGLE') is not None:
            tp = (_floats(val(tm, '*TM_POS', '0 0 0')) + [0.0] * 3)[:3]
            r3 = (_floats(val(tm, '*TM_ROW3', '0 0 0')) + [0.0] * 3)[:3]
            if not _parent(node) or max(abs(tp[i] - r3[i]) for i in range(3)) > 0.01:
                ax = (_floats(val(tm, '*TM_ROTAXIS', '0 0 1')) + [0.0] * 3)[:3]
                ang = (_floats(val(tm, '*TM_ROTANGLE', '0')) + [0.0])[0]
                self._static = (Vector(tp), Quaternion(_qnorm(_qaxis(_unit(ax), -ang))))
        if a is None:
            return
        # The keys the game's own ASE reader takes (smRead3d.cpp), whatever block they sit in:
        # sampled keys and 3ds Max TCB / Bezier keys alike, first 4 or 5 numbers (no tangents).
        q = (1.0, 0.0, 0.0, 0.0)
        for blk in a[2] or ():
            for c in blk[2] or ():
                tag = c[0]
                if tag in POS_KEYS:
                    f = _floats(c[1])
                    if len(f) >= 4:
                        self.pos.append((f[0], Vector(f[1:4])))
                elif tag in ROT_KEYS:
                    # Each key turns the previous orientation by `angle` about `axis`
                    # (3ds Max rotates clockwise, hence the minus).  In between two keys
                    # the game blends towards the key's turn (a slerp from a zero
                    # quaternion, smObj3d GetRotFrame), i.e. the short way round: a turn of
                    # 5.94 rad about -z (as 3ds Max writes a windmill) is 0.34 about +z.
                    # Accumulated in Python doubles: mathutils is 32-bit and a class
                    # skeleton chains ~10000 deltas.
                    f = _floats(c[1])
                    if len(f) >= 5:
                        axis = _unit(f[1:4])
                        ang = -math.remainder(f[4], 2.0 * math.pi)
                        q = _qnorm(_qmul(_qaxis(axis, ang), q))
                        self.rot.append((f[0], q, axis, ang))
                elif tag in SCALE_KEYS:
                    f = _floats(c[1])
                    if len(f) >= 4:
                        self.scl.append((f[0], Vector(f[1:4])))
        self._pt = [k[0] for k in self.pos]
        self._rt = [k[0] for k in self.rot]
        self._st = [k[0] for k in self.scl]

    def ticks(self, max_step=0.15):
        """Key times, plus in-between samples wherever one key turns more than
        `max_step` radians, so Blender's linear quaternion keys follow the
        game's turn exactly."""
        ts = set(k[0] for k in self.pos) | set(k[0] for k in self.rot) | set(k[0] for k in self.scl)
        for i in range(1, len(self.rot)):
            t0, t1, ang = self.rot[i - 1][0], self.rot[i][0], abs(self.rot[i][3])
            if ang > max_step and t1 - t0 > 1:
                n = int(min(math.ceil(ang / max_step), t1 - t0))
                # whole ticks: the exporter writes key times as ticks (a fast root moves ~0.08 a tick)
                ts.update(float(round(t0 + (t1 - t0) * j / float(n))) for j in range(1, n))
        return sorted(ts)

    def rotation(self, t):
        keys = self.rot
        i = bisect.bisect_right(self._rt, t) - 1
        if i < 0:
            return Quaternion(keys[0][1])
        if i >= len(keys) - 1:
            return Quaternion(keys[-1][1])
        t0, q0 = keys[i][0], keys[i][1]
        t1, _q1, axis, ang = keys[i + 1]
        if t1 <= t0 or t <= t0:
            return Quaternion(q0)
        return Quaternion(_qmul(_qaxis(axis, ang * (t - t0) / (t1 - t0)), q0))

    @staticmethod
    def _at(keys, times, t, lerp):
        i = bisect.bisect_right(times, t) - 1
        if i < 0:
            return keys[0][1]
        if i >= len(keys) - 1:
            return keys[-1][1]
        t0, a = keys[i]
        t1, b = keys[i + 1]
        if t1 <= t0:
            return b
        return lerp(a, b, (t - t0) / (t1 - t0))

    def static(self, rest):
        """(location, rotation) the game shows on channels without keys; rest = the local
        transform from the rows (used when the file has no parent-relative TM_POS / TM_ROTAXIS,
        and always for a mirrored node)."""
        loc, rot, _s = rest.decompose()
        rot.normalize()
        if self._static is not None and rest.to_3x3().determinant() > 0:
            return self._static[0].copy(), self._static[1].copy()
        return loc, rot

    def local(self, t, rest_loc, rest_rot, rest_scl):
        p = self._at(self.pos, self._pt, t, lambda a, b, f: a.lerp(b, f)) if self.pos else rest_loc
        r = self.rotation(t) if self.rot else rest_rot
        s = self._at(self.scl, self._st, t, lambda a, b, f: a.lerp(b, f)) if self.scl else rest_scl
        return Matrix.LocRotScale(p, r, s)


def _channelbag(ob, action):
    ad = ob.animation_data or ob.animation_data_create()
    ad.action = action
    if hasattr(action, 'slots'):
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot
        slot = ad.action_slot
        if slot is None:
            slot = action.slots.new('OBJECT', ob.name)
            ad.action_slot = slot
        return action_ensure_channelbag_for_slot(action, slot)
    return action                                   # Blender < 4.4: legacy action.fcurves


def raw_worlds(arm_ob):
    """{bone: bind world matrix exactly as written in the file (may be scaled / skewed)}."""
    out = {}
    for nm, f in json.loads(arm_ob.get('pt_bind_raw', '{}')).items():
        if len(f) >= 12 and all(math.isfinite(x) for x in f):
            out[nm] = Matrix(((f[0], f[3], f[6], f[9]), (f[1], f[4], f[7], f[10]),
                              (f[2], f[5], f[8], f[11]), (0.0, 0.0, 0.0, 1.0)))
    return out


def bind_maps(rigid, raw):
    """{bone: A = rigid rest @ written bind^-1} (armature space).

    The game skins a vertex on its bone's bind pose as written, which can be scaled or skewed
    (bones at 0.89 in many monsters, 8.8 fixed-point noise in all); Blender binds on the rigid
    rest pose.  With every skinned vertex moved once by A, Blender's skinning gives exactly the
    game's result at every frame:  bone world @ rest^-1 @ A @ v = bone world @ bind^-1 @ v.
    The exporter applies A^-1 to get the written bind-pose vertices back.  Bones whose two
    matrices agree are left out."""
    out = {}
    for nm, R in rigid.items():
        W = raw.get(nm)
        if W is None or abs(W.to_3x3().determinant()) < 1e-9:
            continue
        a = mul4(dbl4(R), inv4(dbl4(W)))                  # doubles: rigs can sit at map coordinates
        if any(abs(a[i][j] - (1.0 if i == j else 0.0)) > 1e-7 for i in range(3) for j in range(4)):
            out[nm] = a
    return out


def dbl4(m):
    """A mathutils Matrix (column-vector, 4x4) as nested Python doubles."""
    return [[float(m[i][j]) for j in range(4)] for i in range(4)]


def mul4(a, b):
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j] for j in range(4)]
            for i in range(4)]


def inv4(m):
    """Inverse of an affine 4x4 (last row 0 0 0 1), in doubles."""
    a, b, c = m[0][0], m[0][1], m[0][2]
    d, e, f = m[1][0], m[1][1], m[1][2]
    g, h, i = m[2][0], m[2][1], m[2][2]
    A, B, C = e * i - f * h, -(d * i - f * g), d * h - e * g
    det = a * A + b * B + c * C
    if abs(det) < 1e-300:
        return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    r = [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
         [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
         [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]]
    t = [m[0][3], m[1][3], m[2][3]]
    out = [r[k] + [-(r[k][0] * t[0] + r[k][1] * t[1] + r[k][2] * t[2])] for k in range(3)]
    return out + [[0.0, 0.0, 0.0, 1.0]]


def apply_bind_maps(mesh_ob, assign, maps, mesh_world, inverse=False):
    """Move every skinned vertex by its bone's bind map (or back, inverse=True).  mesh_world:
    the mesh's pivot as nested doubles (armature space); coordinates stay in mesh space."""
    if not maps:
        return 0
    minv = inv4(mesh_world)
    per = {}
    for nm, a in maps.items():
        per[nm] = mul4(minv, mul4(inv4(a) if inverse else a, mesh_world))
    me = mesh_ob.data
    co = [0.0] * (3 * len(me.vertices))
    me.vertices.foreach_get('co', co)
    moved = 0
    for vi, bn in assign.items():
        m = per.get(bn)
        if m is None or vi * 3 + 2 >= len(co):
            continue
        x, y, z = co[vi * 3], co[vi * 3 + 1], co[vi * 3 + 2]
        co[vi * 3] = m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3]
        co[vi * 3 + 1] = m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3]
        co[vi * 3 + 2] = m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]
        moved += 1
    me.vertices.foreach_set('co', co)
    me.update()
    return moved


def build_action_steps(arm_ob, world, parent, tracks, name):
    """Generator (progress 0..1): keys every bone that has a track.
    Pose basis = (bind local)^-1 @ animated local, in Blender bone axes."""
    action = bpy.data.actions.new(name)
    bag = _channelbag(arm_ob, action)
    todo = [nm for nm in world if nm in tracks and tracks[nm].ticks()]
    raw = raw_worlds(arm_ob)
    axes = bone_axes(arm_ob)
    last = 0.0
    for k, nm in enumerate(todo):
        tr = tracks[nm]
        p = parent.get(nm)
        rest_local = (world[p].inverted() @ world[nm]) if p in world else world[nm]
        rest_inv = rest_local.inverted()
        # channels without keys: the game uses the bone's own stored local transform (TM_POS /
        # TM_ROTAXIS, else the bind pose as written: Tm x parent->TmInvert), and no scale
        rb = raw.get(nm, world[nm])
        raw_local = (raw.get(p, world[p]).inverted_safe() @ rb) if p in world else rb
        r_loc, r_rot = tr.static(raw_local)
        r_scl = Vector((1.0, 1.0, 1.0))
        ticks = tr.ticks()
        last = max(last, ticks[-1])
        n = len(ticks)
        loc = [0.0] * (3 * n)
        rot = [0.0] * (4 * n)
        scl = [0.0] * (3 * n)
        prev = None
        for i, t in enumerate(ticks):
            # the bone's world is exactly the game's (the skinned vertices carry the difference
            # between the written bind pose and Blender's rigid rest pose, see bind_maps)
            ax = axes.get(nm, AXIS)
            basis = ax.inverted() @ rest_inv @ tr.local(t, r_loc, r_rot, r_scl) @ ax
            l, q, s = basis.decompose()
            if prev is not None and prev.dot(q) < 0.0:
                q.negate()
            prev = q
            loc[3 * i:3 * i + 3] = l
            rot[4 * i:4 * i + 4] = q
            scl[3 * i:3 * i + 3] = s
        frames = [t / TICKS for t in ticks]
        # Blender merges keys closer than 0.01 frame; the converter puts a "hold"
        # key 1 tick (1/160 frame) before every motion-piece boundary.
        for i in range(n - 2, -1, -1):
            if frames[i + 1] - frames[i] < 0.02:
                frames[i] = frames[i + 1] - 0.02
        grp = bag.groups.new(nm) if hasattr(bag, 'groups') else None
        for path, data, width in (('location', loc, 3), ('rotation_quaternion', rot, 4), ('scale', scl, 3)):
            dp = 'pose.bones["%s"].%s' % (nm.replace('"', '\\"'), path)
            for j in range(width):
                fc = bag.fcurves.new(dp, index=j)
                if grp is not None:
                    fc.group = grp
                kp = fc.keyframe_points
                kp.add(n)
                co = [0.0] * (2 * n)
                co[0::2] = frames
                co[1::2] = data[j::width]
                kp.foreach_set('co', co)
                kp.foreach_set('interpolation', [1] * n)      # LINEAR, like the game
                fc.update()
        yield (k + 1) / float(len(todo) or 1)
    action['pt_last_frame'] = last / TICKS
    return action


def build_object_action(ob, track, rest_local, name):
    """A rigid object's own *TM_ANIMATION (windmills, doors, chandeliers): linear location /
    quaternion / scale keys on the object, relative to its parent object (whose transform is
    its own ASE local transform, so object basis = ASE local)."""
    action = bpy.data.actions.new(name)
    bag = _channelbag(ob, action)
    ob.rotation_mode = 'QUATERNION'
    r_loc, r_rot, r_scl = rest_local.decompose()
    if rest_local.to_3x3().determinant() > 0:
        r_loc, r_rot = track.static(rest_local)        # channels without keys, as the game
    ticks = track.ticks()
    n = len(ticks)
    loc = [0.0] * (3 * n)
    rot = [0.0] * (4 * n)
    scl = [0.0] * (3 * n)
    prev = None
    for i, t in enumerate(ticks):
        l, q, s = track.local(t, r_loc, r_rot, r_scl).decompose()
        if prev is not None and prev.dot(q) < 0.0:
            q.negate()
        prev = q
        loc[3 * i:3 * i + 3] = l
        rot[4 * i:4 * i + 4] = q
        scl[3 * i:3 * i + 3] = s
    frames = [t / TICKS for t in ticks]
    for i in range(n - 2, -1, -1):                    # Blender merges keys closer than 0.01 frame
        if frames[i + 1] - frames[i] < 0.02:
            frames[i] = frames[i + 1] - 0.02
    for path, data, width in (('location', loc, 3), ('rotation_quaternion', rot, 4), ('scale', scl, 3)):
        for j in range(width):
            fc = bag.fcurves.new(path, index=j)
            kp = fc.keyframe_points
            kp.add(n)
            co = [0.0] * (2 * n)
            co[0::2] = frames
            co[1::2] = data[j::width]
            kp.foreach_set('co', co)
            kp.foreach_set('interpolation', [1] * n)      # LINEAR, like the game
            fc.update()
    action['pt_last_frame'] = ticks[-1] / TICKS if ticks else 0.0
    return action


def find_animation_file(ase_path, anim_file, extra_dirs=()):
    if not anim_file:
        return None
    for d in [os.path.dirname(os.path.abspath(ase_path))] + list(extra_dirs):
        p = os.path.join(d, anim_file)
        if os.path.isfile(p):
            return p
        try:
            for n in os.listdir(d):
                if n.lower() == anim_file.lower():
                    return os.path.join(d, n)
        except OSError:
            pass
    return None


# Player class skeletons: [C] + race(T/M) + sex(m/f) + part(b/h) + class letter
_PLAYER_RE = re.compile(r'^c?([tm])([mf])([bh])[-_]?m?([a-f])', re.I)
_CLASS = {('t', 'a'): 1, ('t', 'b'): 1, ('t', 'c'): 4, ('t', 'd'): 2, ('t', 'e'): 6, ('t', 'f'): 8,
          ('m', 'a'): 1, ('m', 'b'): 2, ('m', 'c'): 5, ('m', 'd'): 3, ('m', 'e'): 7}


def class_animation_name(ase_path):
    """'m8_motions.ase' for TfbF01.ASE / CtfbF12.ASE ..., else ''."""
    m = _PLAYER_RE.match(os.path.basename(ase_path))
    if not m:
        return ''
    c = _CLASS.get((m.group(1).lower(), m.group(4).lower()))
    return 'm%d_motions.ase' % c if c else ''


def animation_source(ase_path, anim_info, picked='', extra_dirs=()):
    """(path or None, name that was looked for) of the animation for a character
    whose own file has no keys:
      1) the file picked in the import options,
      2) the shared file a converted character names (*PT_ANIMATION_FILE),
      3) the class file worked out from the name, for original artist ASE files
         (TfbF01.ASE -> m8_motions.ase), next to the file or the picked file."""
    if picked and os.path.isfile(picked):
        return picked, picked
    dirs = list(extra_dirs) + ([os.path.dirname(picked)] if picked else [])
    wanted = anim_info[1] if anim_info and anim_info[1] else class_animation_name(ase_path)
    if not wanted:
        return None, ''
    return find_animation_file(ase_path, wanted, dirs), wanted


def tracks_from(root):
    out = {}
    for n in _nodes(root):
        if find(n, '*TM_ANIMATION') is not None:
            out[_name(n)] = Track(n)
    return out


def set_motions(context, arm_ob, motions, last_frame):
    """Timeline markers + the motion list shown in the PT Motions panel."""
    scn = context.scene
    scn.render.fps = 30
    scn.render.fps_base = 1.0
    scn.frame_start = 0
    scn.frame_end = max(1, int(math.ceil(last_frame)))
    arm_ob.pt_motions.clear()
    for nm, s, e, loop in motions:
        it = arm_ob.pt_motions.add()
        it.name = nm
        it.start = s
        it.end = e
        it.loop = loop
        scn.timeline_markers.new(nm, frame=s)
    arm_ob['pt_last_frame'] = scn.frame_end


# --------------------------------------------------------------------------- UI data
class PT_MotionItem(bpy.types.PropertyGroup):
    start: bpy.props.IntProperty(name='Start')
    end: bpy.props.IntProperty(name='End')
    loop: bpy.props.BoolProperty(name='Loop')


def _motion_selected(self, context):
    i = self.pt_motion_index
    if 0 <= i < len(self.pt_motions):
        m = self.pt_motions[i]
        scn = context.scene
        scn.frame_start = m.start
        scn.frame_end = max(m.start + 1, m.end)
        scn.frame_current = m.start


class PT_UL_motions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon='ACTION')
        row.label(text='%d - %d%s' % (item.start, item.end, bpy.app.translations.pgettext_iface('  loop') if item.loop else ''),
                  translate=False)


class PT_OT_all_motions(bpy.types.Operator):
    """Show the whole animation timeline again"""
    bl_idname = 'pt_ase.all_motions'
    bl_label = 'Whole Timeline'

    def execute(self, context):
        ob = context.active_object
        scn = context.scene
        scn.frame_start = 0
        scn.frame_end = int(ob.get('pt_last_frame', scn.frame_end)) if ob else scn.frame_end
        return {'FINISHED'}


class VIEW3D_PT_pt_motions(bpy.types.Panel):
    bl_label = 'PT Motions'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'PT'

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and (ob.type == 'ARMATURE' or (ob.parent and ob.parent.type == 'ARMATURE'))

    def draw(self, context):
        ob = context.active_object
        if ob.type != 'ARMATURE':
            ob = ob.parent
        lay = self.layout
        if not len(ob.pt_motions):
            lay.label(text='No motion list in this file')
        else:
            lay.label(text='Click a motion to play only that range:')
            lay.template_list('PT_UL_motions', '', ob, 'pt_motions', ob, 'pt_motion_index', rows=12)
        row = lay.row(align=True)
        row.operator('pt_ase.all_motions', icon='TIME')
        row.operator('screen.animation_play', text='Play', icon='PLAY')


CLASSES = (PT_MotionItem, PT_UL_motions, PT_OT_all_motions, VIEW3D_PT_pt_motions)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.pt_motions = bpy.props.CollectionProperty(type=PT_MotionItem)
    bpy.types.Object.pt_motion_index = bpy.props.IntProperty(default=-1, update=_motion_selected)


def unregister():
    del bpy.types.Object.pt_motion_index
    del bpy.types.Object.pt_motions
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
