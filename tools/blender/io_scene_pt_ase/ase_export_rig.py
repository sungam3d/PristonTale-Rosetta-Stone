"""Skeleton, skinning and animation export (characters and monsters) for the PT ASE exporter.

What the game's own ASE -> SMD/SMB builder reads (checked against the developers' files and
the .smd/.smb the game built from them):
  * meshes WITH a material  -> the model (.smd); a *PHYSIQUE block gives every vertex its bone
  * meshes WITHOUT a material -> the skeleton (.smb), with their *TM_ANIMATION
  * helper objects            -> ignored
So a skinned model is written as:
  * the mesh in its REST pose (the Armature modifier switched off), with *PHYSIQUE
    (one bone per vertex: the vertex group with the largest weight - the game is rigid)
  * every bone as a small material-less mesh at its rest transform
  * the bone animation (monsters; player armour takes it from the game's class .smb)
    in 3ds Max's ASE convention: position relative to the parent, rotation as a turn from
    the previous key (axis + angle, first key absolute), scale.
"""

import json
import math

import bpy
from mathutils import Matrix, Quaternion

from .ase_anim import bind_maps, bone_axes, inv4, raw_worlds


def _f4(x):
    s = '%.4f' % x
    return '0.0000' if s == '-0.0000' else s


def _f(x):
    """Same as the converter: up to 8 decimals, at least 4."""
    s = ('%.8f' % x).rstrip('0')
    if s.endswith('.'):
        s += '0000'
    elif len(s) - s.index('.') < 5:
        s += '0' * (5 - (len(s) - s.index('.')))
    return '0.0000' if s == '-0.0000' else s


def _f6(x):
    s = '%.6f' % x
    return '0.000000' if s == '-0.000000' else s


def _f9(x):
    s = '%.9f' % x
    return '0.000000000' if s == '-0.000000000' else s


def _q(s):
    return '"%s"' % str(s).replace('"', "'")


def armature_of(ob):
    """The Armature object deforming a mesh (modifier first, then parent), or None."""
    for m in ob.modifiers:
        if m.type == 'ARMATURE' and m.object is not None and m.object.type == 'ARMATURE':
            return m.object
    if ob.parent is not None and ob.parent.type == 'ARMATURE' and ob.vertex_groups:
        return ob.parent
    return None


class RestPose(object):
    """Context manager: the mesh evaluated without its Armature modifiers (rest pose)."""

    def __init__(self, ob):
        self.ob = ob
        self.mods = [m for m in ob.modifiers if m.type == 'ARMATURE' and m.show_viewport]

    def __enter__(self):
        for m in self.mods:
            m.show_viewport = False
        bpy.context.view_layer.update()
        return self

    def __exit__(self, *a):
        for m in self.mods:
            m.show_viewport = True
        bpy.context.view_layer.update()


def physique(ob, me, bone_names):
    """Bone name per vertex of `me` (strongest vertex group that is a bone), '' if none."""
    groups = {g.index: g.name for g in ob.vertex_groups if g.name in bone_names}
    out = []
    unassigned = 0
    for v in me.vertices:
        best, w = '', 0.0
        for g in v.groups:
            nm = groups.get(g.group)
            if nm is not None and g.weight > w:
                best, w = nm, g.weight
        if not best:
            unassigned += 1
        out.append(best)
    return out, unassigned


def _same_rest(m, ref):
    """A bone still at its imported rest pose: rotation within 2e-3, position within 2e-3 plus
    the 32-bit float step of where it is (map props sit ~40000 units out: 0.004 steps)."""
    for i in range(3):
        for j in range(3):
            if abs(m[i][j] - ref[i][j]) >= 2e-3:
                return False
        if abs(m[i][3] - ref[i][3]) >= 2e-3 + 4e-7 * abs(ref[i][3]):
            return False
    return True


def unbind_maps(arm):
    """{bone: A^-1} (nested doubles, armature space): undoes the importer's bind maps on the
    skinned vertices (ase_anim.bind_maps), for bones still at their imported rest pose."""
    bind = json.loads(arm.get('pt_bind', '{}'))
    axes = bone_axes(arm)
    rigid = {}
    for b in arm.data.bones:
        if b.name in bind:
            ref = Matrix(bind[b.name])
            if _same_rest(b.matrix_local @ axes[b.name].inverted(), ref):
                rigid[b.name] = ref
    return {nm: inv4(a) for nm, a in bind_maps(rigid, raw_worlds(arm)).items()}


def write_physique(w, names):
    assigned = [(i, n) for i, n in enumerate(names) if n]
    w('\t*PHYSIQUE {')
    w('\t\t*PHYSIQUE_NUMVERTEXASSIGNMENT\t%d' % len(assigned))
    for i, n in assigned:
        w('\t\t*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE %d\t%s' % (i, _q(n)))
    w('\t}')


# --------------------------------------------------------------------------- bones
def _ordered(bones):
    """Parents before children."""
    out, seen = [], set()

    def add(b):
        if b.name in seen:
            return
        if b.parent is not None:
            add(b.parent)
        seen.add(b.name)
        out.append(b)
    for b in bones:
        add(b)
    return out


def _rows_of(m):
    """ASE rows (row vectors) of a column-vector matrix, as 12 floats."""
    return [m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2],
            m[0][3], m[1][3], m[2][3]]


def bone_rest_rows(arm, space):
    """{bone: 12 ASE rows} of the rest pose in game units.  Bones nobody has touched since
    the import are written with the exact numbers of the original file."""
    sa = space @ arm.matrix_world
    raw = json.loads(arm.get('pt_bind_raw', '{}'))
    bind = json.loads(arm.get('pt_bind', '{}'))
    untouched_object = all(abs(sa[i][j] - (1.0 if i == j else 0.0)) < 1e-5 for i in range(4) for j in range(4))
    axes = bone_axes(arm)
    out = {}
    for b in arm.data.bones:
        ax = axes[b.name]
        W = sa @ b.matrix_local @ ax.inverted()
        rows = _rows_of(W)
        if untouched_object and b.name in raw and b.name in bind:
            if _same_rest(b.matrix_local, Matrix(bind[b.name]) @ ax):
                rows = raw[b.name]
        out[b.name] = rows
    return out


def _tm_axis_angle(r):
    """TM_ROTAXIS / TM_ROTANGLE / TM_SCALE exactly as the converter (and 3ds Max) write them."""
    rows = [r[0:3], r[3:6], r[6:9]]
    sc = [math.sqrt(x[0] * x[0] + x[1] * x[1] + x[2] * x[2]) or 1.0 for x in rows]
    R = [[rows[i][j] / sc[i] for j in range(3)] for i in range(3)]
    M = [[R[j][i] for j in range(3)] for i in range(3)]
    tr = M[0][0] + M[1][1] + M[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w_, x, y, z = 0.25 * s, (M[1][2] - M[2][1]) / s, (M[2][0] - M[0][2]) / s, (M[0][1] - M[1][0]) / s
    elif M[0][0] > M[1][1] and M[0][0] > M[2][2]:
        s = math.sqrt(1.0 + M[0][0] - M[1][1] - M[2][2]) * 2
        w_, x, y, z = (M[1][2] - M[2][1]) / s, 0.25 * s, (M[1][0] + M[0][1]) / s, (M[2][0] + M[0][2]) / s
    elif M[1][1] > M[2][2]:
        s = math.sqrt(1.0 + M[1][1] - M[0][0] - M[2][2]) * 2
        w_, x, y, z = (M[2][0] - M[0][2]) / s, (M[1][0] + M[0][1]) / s, 0.25 * s, (M[2][1] + M[1][2]) / s
    else:
        s = math.sqrt(1.0 + M[2][2] - M[0][0] - M[1][1]) * 2
        w_, x, y, z = (M[0][1] - M[1][0]) / s, (M[2][0] + M[0][2]) / s, (M[2][1] + M[1][2]) / s, 0.25 * s
    w_ = max(-1.0, min(1.0, w_))
    sn = math.sqrt(max(0.0, 1.0 - w_ * w_))
    if sn < 1e-7:
        return (0.0, 0.0, 0.0), 0.0, sc
    return (x / sn, y / sn, z / sn), 2.0 * math.acos(w_), sc


def _write_node_tm(w, name, r):
    axis, ang, sc = _tm_axis_angle(r)
    w('\t*NODE_TM {')
    w('\t\t*NODE_NAME %s' % _q(name))
    w('\t\t*INHERIT_POS 0 0 0')
    w('\t\t*INHERIT_ROT 0 0 0')
    w('\t\t*INHERIT_SCL 0 0 0')
    for k in range(3):
        w('\t\t*TM_ROW%d %s\t%s\t%s' % (k, _f4(r[k * 3]), _f4(r[k * 3 + 1]), _f4(r[k * 3 + 2])))
    w('\t\t*TM_ROW3 %s\t%s\t%s' % (_f(r[9]), _f(r[10]), _f(r[11])))
    w('\t\t*TM_POS %s\t%s\t%s' % (_f(r[9]), _f(r[10]), _f(r[11])))
    w('\t\t*TM_ROTAXIS %s\t%s\t%s' % (_f4(axis[0]), _f4(axis[1]), _f4(axis[2])))
    w('\t\t*TM_ROTANGLE %s' % _f4(ang))
    w('\t\t*TM_SCALE %s\t%s\t%s' % (_f4(sc[0]), _f4(sc[1]), _f4(sc[2])))
    w('\t\t*TM_SCALEAXIS 0.0000\t0.0000\t0.0000')
    w('\t\t*TM_SCALEAXISANG 0.0000')
    w('\t}')


def _qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def bone_tracks(arm, space, action):
    """{bone: (pos keys, rot keys, scale keys)} in ASE form from the armature's action."""
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    bag = None
    if hasattr(action, 'slots'):
        slot = arm.animation_data.action_slot if arm.animation_data else None
        bag = action_get_channelbag_for_slot(action, slot) if slot else None
    curves = list(bag.fcurves) if bag is not None else list(getattr(action, 'fcurves', []))
    by_bone = {}
    for fc in curves:
        p = fc.data_path
        if not p.startswith('pose.bones["'):
            continue
        name = p[len('pose.bones["'):p.index('"]')].replace('\\"', '"')
        prop = p[p.rindex('.') + 1:]
        by_bone.setdefault(name, {})[(prop, fc.array_index)] = fc
    sa = space @ arm.matrix_world
    # Rest pose per bone (3ds Max axes, armature space).  Untouched bones use the matrices the
    # importer built the animation from: Blender's own bone matrices lose a little precision
    # (bone roll), which adds up along long bone chains.
    bind = json.loads(arm.get('pt_bind', '{}'))
    axes = bone_axes(arm)
    rest = {}
    for b in arm.data.bones:
        W = b.matrix_local @ axes[b.name].inverted()
        if b.name in bind:
            ref = Matrix(bind[b.name])
            if _same_rest(W, ref):
                W = ref
        rest[b.name] = W
    out = {}
    for b in _ordered(arm.data.bones):
        fcs = by_bone.get(b.name)
        if not fcs:
            continue
        pb = arm.pose.bones[b.name]
        frames = sorted({round(k.co[0], 4) for fc in fcs.values() for k in fc.keyframe_points})
        # local 3ds Max transform = pre @ basis @ AX^-1, with W = rest pose in 3ds Max axes and
        # AX the bone's axes (bone_axes):  child: W_parent^-1 @ W @ AX   root: export space @ W @ AX
        Wb = rest[b.name]
        ax = axes[b.name]
        ax_inv = ax.inverted()
        pre = ((rest[b.parent.name].inverted() @ Wb) if b.parent else (sa @ Wb)) @ ax
        has_scale = any(k[0] == 'scale' for k in fcs)

        def ch(prop, i, default, f):
            fc = fcs.get((prop, i))
            return fc.evaluate(f) if fc is not None else default
        pos, rot, scl = [], [], []
        last = (1.0, 0.0, 0.0, 0.0)
        for f in frames:
            loc = [ch('location', i, pb.location[i], f) for i in range(3)]
            if pb.rotation_mode == 'QUATERNION':
                q = Quaternion([ch('rotation_quaternion', i, pb.rotation_quaternion[i], f) for i in range(4)])
            else:
                from mathutils import Euler
                q = Euler([ch('rotation_euler', i, pb.rotation_euler[i], f) for i in range(3)], pb.rotation_mode).to_quaternion()
            q.normalize()
            s = [ch('scale', i, pb.scale[i], f) for i in range(3)]
            basis = Matrix.LocRotScale(loc, q, s)
            L = pre @ basis @ ax_inv                          # local (parent-relative) 3ds Max transform
            t, lq, ls = L.decompose()
            tick = int(round(f * 160.0))
            pos.append((tick, t[0], t[1], t[2]))
            if has_scale:
                scl.append((tick, ls[0], ls[1], ls[2]))
            cur = (lq.w, lq.x, lq.y, lq.z)
            # ASE key = turn from the previous key:  d = q_prev * conj(q_cur)  (shortest way round)
            d = _qmul(last, (cur[0], -cur[1], -cur[2], -cur[3]))
            if d[0] < 0.0:
                d = (-d[0], -d[1], -d[2], -d[3])
            sn = math.sqrt(d[1] * d[1] + d[2] * d[2] + d[3] * d[3])
            if sn < 1e-12:
                rot.append((tick, 0.0, 0.0, 0.0, 0.0))
            else:
                rot.append((tick, d[1] / sn, d[2] / sn, d[3] / sn, 2.0 * math.atan2(sn, d[0])))
            last = cur
        out[b.name] = (pos, rot, scl)
    return out


def keys_from_locals(samples, with_scale):
    """[(tick, local Matrix in 3ds Max axes)] -> ASE (pos, rot, scale) keys: position relative to
    the parent, rotation as a turn from the previous key (first absolute), scale."""
    pos, rot, scl = [], [], []
    last = (1.0, 0.0, 0.0, 0.0)
    for tick, L in samples:
        t, lq, ls = L.decompose()
        pos.append((tick, t[0], t[1], t[2]))
        if with_scale:
            scl.append((tick, ls[0], ls[1], ls[2]))
        cur = (lq.w, lq.x, lq.y, lq.z)
        d = _qmul(last, (cur[0], -cur[1], -cur[2], -cur[3]))     # q_prev * conj(q_cur), shortest
        if d[0] < 0.0:
            d = (-d[0], -d[1], -d[2], -d[3])
        sn = math.sqrt(d[1] * d[1] + d[2] * d[2] + d[3] * d[3])
        if sn < 1e-12:
            rot.append((tick, 0.0, 0.0, 0.0, 0.0))
        else:
            rot.append((tick, d[1] / sn, d[2] / sn, d[3] / sn, 2.0 * math.atan2(sn, d[0])))
        last = cur
    return pos, rot, scl


def object_track(ob, local_of):
    """Keys of an object's own animation (its action's location / rotation / scale curves),
    sampled at every keyframe.  local_of(basis) -> the ASE local matrix.  None = no animation."""
    ad = ob.animation_data
    act = ad.action if ad else None
    if act is None:
        return None
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    bag = None
    if hasattr(act, 'slots'):
        slot = ad.action_slot
        bag = action_get_channelbag_for_slot(act, slot) if slot else None
    curves = list(bag.fcurves) if bag is not None else list(getattr(act, 'fcurves', []))
    fcs = {(fc.data_path, fc.array_index): fc for fc in curves
           if fc.data_path in ('location', 'rotation_quaternion', 'rotation_euler', 'scale')}
    if not fcs:
        return None
    frames = sorted({round(k.co[0], 4) for fc in fcs.values() for k in fc.keyframe_points})

    def ch(path, i, default, f):
        fc = fcs.get((path, i))
        return fc.evaluate(f) if fc is not None else default
    with_scale = any(p == 'scale' for p, _i in fcs)
    samples = []
    for f in frames:
        loc = [ch('location', i, ob.location[i], f) for i in range(3)]
        if ob.rotation_mode == 'QUATERNION':
            q = Quaternion([ch('rotation_quaternion', i, ob.rotation_quaternion[i], f) for i in range(4)])
        elif ob.rotation_mode == 'AXIS_ANGLE':
            aa = ob.rotation_axis_angle
            q = Quaternion(aa[1:], aa[0])
        else:
            from mathutils import Euler
            q = Euler([ch('rotation_euler', i, ob.rotation_euler[i], f) for i in range(3)], ob.rotation_mode).to_quaternion()
        q.normalize()
        s = [ch('scale', i, ob.scale[i], f) for i in range(3)]
        samples.append((int(round(f * 160.0)), local_of(Matrix.LocRotScale(loc, q, s))))
    return keys_from_locals(samples, with_scale)


def write_tm_animation(w, name, tr, ind='\t'):
    pos, rot, scl = tr
    i2, i3 = ind + '\t', ind + '\t\t'
    w('%s*TM_ANIMATION {' % ind)
    w('%s*NODE_NAME %s' % (i2, _q(name)))
    w('%s*CONTROL_POS_TRACK {' % i2)
    for t, px, py, pz in pos:
        w('%s*CONTROL_POS_SAMPLE %d\t%s\t%s\t%s' % (i3, t, _f6(px), _f6(py), _f6(pz)))
    w('%s}' % i2)
    w('%s*CONTROL_ROT_TRACK {' % i2)
    for t, ax, ay, az, ang in rot:
        w('%s*CONTROL_ROT_SAMPLE %d\t%s\t%s\t%s\t%s' % (i3, t, _f9(ax), _f9(ay), _f9(az), _f9(ang)))
    w('%s}' % i2)
    if scl:
        w('%s*CONTROL_SCALE_TRACK {' % i2)
        for t, sx, sy, sz in scl:
            w('%s*CONTROL_SCALE_SAMPLE %d\t%s\t%s\t%s\t0.0000\t0.0000\t0.0000\t0.0000'
              % (i3, t, _f6(sx), _f6(sy), _f6(sz)))
        w('%s}' % i2)
    w('%s}' % ind)


def write_bones(w, arm, space, tracks):
    rest = bone_rest_rows(arm, space)
    for b in _ordered(arm.data.bones):
        r = rest[b.name]
        x, y, z = r[9], r[10], r[11]
        rr = 0.5
        verts = [(x, y, z + rr), (x, y - rr, z), (x + rr, y, z), (x, y + rr, z), (x - rr, y, z), (x, y, z - rr)]
        faces = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1), (5, 4, 3), (5, 3, 2), (5, 2, 1), (5, 1, 4)]
        w('*GEOMOBJECT {')
        w('\t*NODE_NAME %s' % _q(b.name))
        if b.parent is not None:
            w('\t*NODE_PARENT %s' % _q(b.parent.name))
        _write_node_tm(w, b.name, r)
        w('\t*MESH {')
        w('\t\t*TIMEVALUE 0')
        w('\t\t*MESH_NUMVERTEX 6')
        w('\t\t*MESH_NUMFACES 8')
        w('\t\t*MESH_VERTEX_LIST {')
        for i, v in enumerate(verts):
            w('\t\t\t*MESH_VERTEX %5d\t%s\t%s\t%s' % (i, _f4(v[0]), _f4(v[1]), _f4(v[2])))
        w('\t\t}')
        w('\t\t*MESH_FACE_LIST {')
        for i, (a, c, d) in enumerate(faces):
            w('\t\t\t*MESH_FACE %5d:    A: %5d B: %5d C: %5d AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING 1 \t*MESH_MTLID 0'
              % (i, a, c, d))
        w('\t\t}')
        w('\t\t*MESH_NUMTVERTEX 0')
        w('\t}')
        w('\t*PROP_MOTIONBLUR 0')
        w('\t*PROP_CASTSHADOW 1')
        w('\t*PROP_RECVSHADOW 1')
        tr = tracks.get(b.name)
        if tr:
            write_tm_animation(w, b.name, tr)
        w('\t*WIREFRAME_COLOR 0.6510\t0.7922\t0.9412')
        w('}')
    return len(arm.data.bones)


def write_motions(w, arms, with_anim):
    motions = []
    for a in arms:
        if with_anim.get(a.name):
            motions += [(m.name, m.start, m.end, m.loop) for m in a.pt_motions]
    if not motions:
        return
    w('*PT_ANIMATION {')
    w('\t*PT_SKELETON %s' % _q(arms[0].name))
    for nm, s, e, loop in motions:
        w('\t*PT_MOTION %s\t%d\t%d\t%d' % (_q(nm), s, e, 1 if loop else 0))
    w('}')
