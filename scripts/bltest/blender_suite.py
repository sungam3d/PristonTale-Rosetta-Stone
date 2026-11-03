"""Blender add-on test suite worker: import -> checks -> export -> compare -> re-import, per file.

  blender --background --factory-startup --python blender_suite.py -- <jobs.json> <results.jsonl> <tmp dir>

jobs.json: list of {"ase": path, "smd": path or "", "smb": path or "", "group": name}
Every result is one JSON line (written as soon as the file is done, so a crash loses nothing).
"""
import json
import math
import os
import sys
import time
import traceback

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'blender'))
import io_scene_pt_ase                                     # noqa: E402
import asecheck                                            # noqa: E402
from checks import anim_file_for, animated_names, node_rig, prop_anim_compare, rig_compare   # noqa: E402

try:
    io_scene_pt_ase.register()
except ValueError:
    pass                                                   # already registered (imported as a module)
tmp = os.path.join(HERE, '..', '..', 'work', 'bltest', 'tmp')


def purge():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions, bpy.data.armatures,
                 bpy.data.lights, bpy.data.node_groups, bpy.data.cameras):
        ids = list(coll)
        if ids:
            bpy.data.batch_remove(ids)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    sc = bpy.context.scene
    sc.timeline_markers.clear()
    sc.frame_start, sc.frame_end = 1, 250
    sc.frame_set(1)


def unhide_all():
    for c in bpy.data.collections:
        c.hide_viewport = False
        c.hide_render = False
    for lc in bpy.context.view_layer.layer_collection.children:
        lc.exclude = False
        lc.hide_viewport = False
    for o in bpy.data.objects:
        o.hide_set(False)
        o.hide_viewport = False
    bpy.context.view_layer.update()


def root_scale():
    for o in bpy.data.objects:
        if o.get('pt_ase_root'):
            return o.matrix_world.to_scale()[0]
    return 1.0


def world_coords(ob, depsgraph, scale):
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    ev.to_mesh_clear()
    co = co.reshape(-1, 3)
    M = np.array(ob.matrix_world)
    return (co @ M[:3, :3].T + M[:3, 3]) / scale


def by_ase_name():
    """{(ASE name, n-th object of that name): Blender object}, from the importer's tags."""
    obs = sorted((o for o in bpy.data.objects if 'ase_name' in o), key=lambda o: o.get('ase_index', 0))
    out, nth = {}, {}
    for o in obs:
        k = nth.get(o['ase_name'], 0)
        nth[o['ase_name']] = k + 1
        out[(o['ase_name'], k)] = o
    return out


def placement_check(src, res):
    """Static objects (no bones, no own animation): drawn exactly where the ASE puts them."""
    scale = root_scale()
    dg = bpy.context.evaluated_depsgraph_get()
    char = asecheck.is_char(src)
    worst, n, skipped = 0.0, 0, 0
    names = {}
    for o in src.objects:
        names[o.name] = names.get(o.name, 0) + 1
    res['dup_names'] = sorted(k for k, v in names.items() if v > 1)[:5]
    objs = by_ase_name()
    moving = animated_names(src)
    nth = {}
    for o in src.objects:
        if o.kind not in ('*GEOMOBJECT', '*LIGHTOBJECT') or not asecheck.is_mesh(o, char):
            continue
        k = nth.get(o.name, 0)
        nth[o.name] = k + 1
        if o.physique or o.name in moving:
            skipped += 1
            continue
        ob = objs.get((o.name, k))
        if ob is None or ob.type != 'MESH':
            res.setdefault('not_found', []).append(o.name)
            continue
        w = world_coords(ob, dg, scale)
        if len(w) < len(o.verts):
            res.setdefault('vertex_count', []).append((o.name, len(o.verts), len(w)))
            continue
        # only vertices used by faces (unused ones are dropped by nobody, but keep it simple)
        d = np.abs(w[:len(o.verts)] - np.array(o.verts)).max() if o.verts else 0.0
        worst = max(worst, float(d))
        n += 1
    res['placement'] = worst
    res['placement_objects'] = n


def pose_check(job, src, res):
    """Converted characters/monsters: Blender's animated mesh vs the game's own maths."""
    import game_pose
    in_ase = {o.name for o in src.objects}
    from smdanim.smdfile import Model
    arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
    if arm is None or not job.get('smd') or not job.get('smb'):
        return
    frames = [0]
    mots = list(arm.pt_motions) if hasattr(arm, 'pt_motions') else []
    for m in mots[:: max(1, len(mots) // 3)][:3]:
        frames.append(int(m.start + (m.end - m.start) * 0.4))
    skel, mesh = Model(job['smb']), Model(job['smd'])
    scale = root_scale()
    worst, med = 0.0, 0.0
    for fr in frames:
        bpy.context.scene.frame_set(fr)
        dg = bpy.context.evaluated_depsgraph_get()
        tick = fr * 160.0
        world = game_pose.world_of(skel, tick)
        errs = []
        objs = by_ase_name()
        nth = {}
        for o in mesh.objects:
            if not o.physique:
                continue
            if o.name not in in_ase:
                continue                    # a lower detail level the converter leaves out
            k = nth.get(o.name, 0)
            nth[o.name] = k + 1
            ob = objs.get((o.name, k))
            if ob is None:
                if fr == frames[0]:
                    res.setdefault('pose_missing', []).append(o.name)
                continue
            exp = np.array([np.array(lv) @ world[bn][0] + world[bn][1] if bn in world else [np.nan] * 3
                            for lv, bn in zip(o.local_verts, o.physique)])
            got = world_coords(ob, dg, scale)[:len(exp)]
            ok = ~np.isnan(exp).any(1)
            if len(got) == len(exp):
                errs.append(np.sqrt(((got[ok] - exp[ok]) ** 2).sum(1)))
        if errs:
            e = np.concatenate(errs)
            worst = max(worst, float(e.max()))
            med = max(med, float(np.median(e)))
    res['pose_frames'] = frames
    res['pose_max'] = worst
    res['pose_median'] = med


def prop_anim_check(src, res):
    """Map props with their own keys: Blender's moving objects vs the ASE's animation."""
    char = asecheck.is_char(src)
    # map props, or rigid parts of a character riding on a bone
    animated = [o for o in src.objects if o.anim and asecheck.is_mesh(o, char) and not o.physique
                and (not char or o.mref is not None)]
    if not animated:
        return
    names = {}
    for o in src.objects:
        names[o.name] = names.get(o.name, 0) + 1
    rig = node_rig(src.path)
    last = max([k[0] for b in rig.bones.values() for k in b.pos + b.rot + b.scl] or [0])
    objs = by_ase_name()
    scale = root_scale()
    worst = 0.0
    for t in np.linspace(0, last, 6, endpoint=False):
        bpy.context.scene.frame_set(int(t // 160), subframe=(t % 160) / 160.0)
        dg = bpy.context.evaluated_depsgraph_get()
        for o in animated:
            if names[o.name] > 1:
                continue
            ob = objs.get((o.name, 0))
            if ob is None or o.name not in rig.bones:
                continue
            b = rig.bones[o.name]
            R, p = rig.pose_bone(o.name, float(t))
            v = np.array(o.verts)
            exp = (v - b.t) @ np.linalg.inv(b.R) @ R + p
            got = world_coords(ob, dg, scale)[:len(v)]
            worst = max(worst, float(np.abs(got - exp).max()))
    res['prop_anim'] = worst
    res['prop_animated'] = len(animated)


def export_all(path):
    unhide_all()
    for o in bpy.context.view_layer.objects:
        o.select_set(o.type in ('MESH', 'ARMATURE', 'LIGHT'))
    return bpy.ops.export_scene.pt_ase(filepath=path, copy_textures=False)


def count_scene():
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    return dict(meshes=len(meshes), faces=sum(len(o.data.polygons) for o in meshes),
                armatures=sum(1 for o in bpy.data.objects if o.type == 'ARMATURE'),
                bones=sum(len(o.data.bones) for o in bpy.data.objects if o.type == 'ARMATURE'))


def run(job):
    res = dict(ase=job['ase'], group=job.get('group', ''))
    t = time.time()
    purge()
    stage = 'load'
    try:
        src = asecheck.load(job['ase'])
        stage = 'import'
        r = bpy.ops.import_scene.pt_ase(filepath=job['ase'])
        res['import'] = list(r)
        res['t_import'] = round(time.time() - t, 2)
        res.update(count_scene())
        arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
        res['motions'] = len(arm.pt_motions) if arm is not None and hasattr(arm, 'pt_motions') else 0
        res['anim_source'] = arm.get('pt_anim_source', '') if arm is not None else ''
        res['images'] = len(bpy.data.images)
        res['textures_missing'] = sum(1 for i in bpy.data.images if i.get('pt_missing'))
        res['images_missing'] = sum(1 for i in bpy.data.images if i.source == 'FILE' and not i.get('pt_missing')
                                    and not os.path.isfile(bpy.path.abspath(i.filepath)))
        stage = 'placement'
        unhide_all()
        placement_check(src, res)
        stage = 'pose'
        pose_check(job, src, res)
        stage = 'prop_anim'
        prop_anim_check(src, res)
        bpy.context.scene.frame_set(1)
        stage = 'export'
        exp = os.path.join(tmp, 'exp_%d.ase' % os.getpid())
        t2 = time.time()
        r = export_all(exp)
        res['export'] = list(r)
        res['t_export'] = round(time.time() - t2, 2)
        stage = 'compare'
        dst = asecheck.load(exp)
        c = asecheck.compare(src, dst)
        res['cmp'] = {k: v for k, v in c.items() if v not in ([], 0, 0.0)}
        rigid = [o.name for o in src.objects if o.anim and asecheck.is_mesh(o, True) and not o.physique
                 and o.mref is not None]
        if not asecheck.is_char(src) and any(o.anim for o in src.objects):
            stage = 'prop_export'
            prop_anim_compare(job['ase'], exp, res)
        elif asecheck.is_char(src) and rigid:
            stage = 'prop_export'
            prop_anim_compare(job['ase'], exp, res, names=set(rigid))
        if asecheck.is_char(src) and any(o.physique for o in dst.objects):
            stage = 'rig'
            anim = anim_file_for(job['ase'], src)
            if anim is None and any(o.anim for o in src.objects) and not any(o.anim for o in dst.objects):
                anim = job['ase']           # animation left to the game's motion file: same keys on both sides
                res['rig_anim'] = 'from original'
            rig_compare(job['ase'], exp, anim, res)
        stage = 'reimport'
        before = count_scene()
        purge()
        t3 = time.time()
        r = bpy.ops.import_scene.pt_ase(filepath=exp)
        res['t_reimport'] = round(time.time() - t3, 2)
        after = count_scene()
        res['reimport'] = [before['meshes'], after['meshes'], before['faces'], after['faces'],
                           before['bones'], after['bones']]
        if not os.environ.get('PT_SUITE_KEEP'):
            os.remove(exp)
    except Exception as e:
        res['error'] = '%s: %s' % (stage, e)
        res['trace'] = traceback.format_exc()[-1500:]
    res['t_total'] = round(time.time() - t, 2)
    return res


def main(argv):
    global tmp
    jobs = json.load(open(argv[0], encoding='utf-8'))
    tmp = argv[2]
    os.makedirs(tmp, exist_ok=True)
    done = set()
    if os.path.exists(argv[1]):
        for line in open(argv[1], encoding='utf-8'):
            try:
                done.add(json.loads(line)['ase'])
            except Exception:
                pass
    out = open(argv[1], 'a', encoding='utf-8')
    for job in jobs:
        if job['ase'] in done:
            continue
        r = run(job)
        out.write(json.dumps(r) + '\n')
        out.flush()
    print('SUITE DONE')


if __name__ == '__main__' and '--' in sys.argv and not os.environ.get('PT_SUITE_IMPORT'):
    main(sys.argv[sys.argv.index('--') + 1:])
