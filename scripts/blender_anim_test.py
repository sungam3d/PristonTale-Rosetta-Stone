"""Blender headless test: import a converted character and compare the skinned,
animated mesh against the game's own math at a few frames.

  blender --background --factory-startup --python blender_anim_test.py -- <ase> <smd> <smb> frame ...
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402
from smdanim.smdfile import Model                          # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
ase, smd, smb = args[:3]
frames = [float(f) for f in args[3:]] or [0.0]
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

r = ase_import.import_ase(bpy.context, ase, ase_import.ImportOptions(scale=1.0))
arm = r['armature']
print('imported: bones %d, objects %d, %.1fs, missing tex %s, missing anim %r'
      % (r['bones'], r['objects'], r['seconds'], r['missing'], r['missing_animation']))
act = arm.animation_data.action if arm and arm.animation_data else None
print('action:', act and act.name, 'motions:', len(arm.pt_motions), 'scene frames', bpy.context.scene.frame_start,
      bpy.context.scene.frame_end)


# ---- game math ------------------------------------------------------------------------------
def qmat_rows(x, y, z, w):
    return Matrix(((1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
                   (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
                   (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y))))


def piece_range(o, which, tick):
    """Key index range the game searches at `tick` (only the playing piece's keys)."""
    for s, e, idx, n in (o.frames[which] if o.frames and o.frames[which] else []):
        if e > s and s <= tick < e:
            return idx, idx + n
    return 0, [o.rot_keys, o.pos_keys, o.scale_keys][which].__len__()


def bone_local(o, tick):
    """(rows 3x3 incl. scale, translation) as the game evaluates it:
    keys of the current piece only, cached rotation at the previous key
    turned by the given fraction of the next key's delta, linear positions,
    static transform when the piece has no keys."""
    lo, hi = piece_range(o, 0, tick)
    if hi > lo:
        acc = [(o.rot_keys[k][0], np.array(o.prev_rot[k], dtype=float).reshape(4, 4)[:3, :3])
               for k in range(lo, hi)]
        i = max([k for k, (t, _q) in enumerate(acc) if t <= tick] or [0])
        R = acc[i][1]
        if i + 1 < len(acc) and acc[i][0] <= tick < acc[i + 1][0]:
            # turn by the given fraction of the next key's delta (raw .smb quaternion)
            f = (tick - acc[i][0]) / float(acc[i + 1][0] - acc[i][0])
            _t, x, y, z, w = o.rot_keys[lo + i + 1]
            if w < 0.0:                                   # shortest way round
                x, y, z, w = -x, -y, -z, -w
            ang = 2.0 * math.acos(max(-1.0, min(1.0, w)))
            s = math.sqrt(max(0.0, 1.0 - w * w))
            if s > 1e-9:
                h = 0.5 * ang * f
                k = math.sin(h) / s
                R = R @ np.array(qmat_rows(x * k, y * k, z * k, math.cos(h))).T
    else:
        x, y, z, w = o.quat
        R = np.array(qmat_rows(x, y, z, w)).T

    def interp(which, keys, default):
        lo, hi = piece_range(o, which, tick)
        keys = keys[lo:hi]
        if not keys:
            return np.array(default, dtype=float)
        i = max([k for k, kk in enumerate(keys) if kk[0] <= tick] or [0])
        a = np.array(keys[i][1:4], dtype=float)
        if i + 1 < len(keys) and keys[i][0] <= tick:
            b = np.array(keys[i + 1][1:4], dtype=float)
            f = (tick - keys[i][0]) / float(keys[i + 1][0] - keys[i][0])
            return a + (b - a) * f
        return a
    p = interp(1, o.pos_keys, o.pos)
    s = interp(2, o.scale_keys, o.scale)
    return np.diag(s) @ R, p


skel = Model(smb)
mesh = Model(smd)
mesh_ob = next(o for o in bpy.data.objects if o.type == 'MESH' and o.find_armature())
for fr in frames:
    tick = fr * 160.0
    world = {}
    for b in skel.objects:
        R, p = bone_local(b, tick)
        if b.parent in world:
            PR, Pp = world[b.parent]
            R, p = R @ PR, p @ PR + Pp
        world[b.name] = (R, p)
    bpy.context.scene.frame_set(int(fr))
    dg = bpy.context.evaluated_depsgraph_get()
    exp = []
    got = []
    for o in mesh.objects:                  # every skinned mesh, matched by name
        if not o.physique or o.name not in bpy.data.objects:
            continue
        for lv, bn in zip(o.local_verts, o.physique):
            R, p = world[bn]
            exp.append(Vector(np.array(lv) @ R + p))
        ob = bpy.data.objects[o.name]
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        got += [ob.matrix_world @ v.co for v in me.vertices][:len(o.local_verts)]
        ev.to_mesh_clear()
    err = sorted((a - b).length for a, b in zip(got, exp))
    print('frame %6.0f: vertices %d, error median %.4f  99%% %.4f  max %.4f   (body height %.1f)'
          % (fr, len(err), err[len(err) // 2], err[int(len(err) * 0.99)], err[-1],
             max(v.z for v in exp) - min(v.z for v in exp)))

# ---- per-bone diagnosis at the last frame ------------------------------------------------------
if os.environ.get('PT_DIAG'):
    from io_scene_pt_ase.ase_anim import AXIS_INV
    fr = frames[-1]
    tick = fr * 160.0
    bpy.context.scene.frame_set(int(fr))
    world = {}
    for b in skel.objects:
        R, p = bone_local(b, tick)
        if b.parent in world:
            PR, Pp = world[b.parent]
            R, p = R @ PR, p @ PR + Pp
        world[b.name] = (R, p)
    rows = []
    for b in skel.objects:
        pb = arm.pose.bones.get(b.name)
        if pb is None:
            continue
        W = pb.matrix @ AXIS_INV
        R, p = world[b.name]
        er = max(abs(W[i][j] - R[j][i]) for i in range(3) for j in range(3))
        ep = (W.translation - Vector(p)).length
        rows.append((ep, er, b.name, len(b.rot_keys), len(b.pos_keys)))
    rows.sort(reverse=True)
    for r_ in rows[:8]:
        print('   pos err %.4f rot err %.4f  %-22s rotkeys %d poskeys %d' % r_)
    b = next(o for o in skel.objects if o.name == rows[0][2])
    near = [k for k in b.rot_keys if abs(k[0] - tick) < 800]
    print('   rot keys near tick', tick, [(k[0]) for k in near])
    near = [k for k in b.pos_keys if abs(k[0] - tick) < 800]
    print('   pos keys near', [(k[0]) for k in near])
