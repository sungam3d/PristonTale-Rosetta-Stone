"""The 3ds Max suite's checks: a max_suite.ms dump against the file, the game and the export."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'bltest'))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import asecheck                                                          # noqa: E402
from checks import anim_file_for, animated_names, node_rig, prop_anim_compare, rig_compare   # noqa: E402


def read_dump(path):
    d = dict(meshes=[], poses={}, props={}, lines=[])
    if not os.path.exists(path):
        return d
    lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
    i = 0

    def verts():
        nonlocal i
        n = int(lines[i].split()[1])
        i += 1
        a = np.array([[float(x) for x in lines[i + k].split()] for k in range(n)]).reshape(-1, 3)
        i += n
        return a
    pose = None
    while i < len(lines):
        ln = lines[i]
        tag = ln.split(' ', 1)[0]
        rest = ln[len(tag) + 1:]
        i += 1
        if tag == 'MESH':
            kind, name = rest.split('|', 1)
            d['meshes'].append((kind, name, verts() if kind != 'skin' else None))
        elif tag == 'POSE':
            pose = int(float(rest))
            d['poses'][pose] = []
        elif tag == 'SKIN':
            d['poses'][pose].append((rest, verts()))
        elif tag == 'PROP':
            t, name = rest.split(' ', 1)
            d['props'].setdefault(float(t), []).append((name, verts()))
        elif tag in ('IMPORT', 'EXPORT', 'REIMPORT', 'RANGE', 'MOTIONS', 'BONES', 'ERROR', 'DONE'):
            d[tag] = rest
    return d


def rigid_animated(src):
    """Meshes with their own keys and no skin: map props, or rigid parts of a character."""
    char = asecheck.is_char(src)
    return [o for o in src.objects if o.anim and asecheck.is_mesh(o, char) and not o.physique
            and (not char or o.mref is not None)]


def prop_ticks(src):
    if not rigid_animated(src):
        return []
    rig = node_rig(src.path)
    last = max([k[0] for b in rig.bones.values() for k in b.pos + b.rot + b.scl] or [0])
    return [float(round(t)) for t in np.linspace(0, last, 6, endpoint=False)]      # (3ds Max time: whole ticks)


def check(job, src, d, exp, res):
    char = asecheck.is_char(src)
    moving = animated_names(src)
    # placement: static meshes at frame 0, exactly where the file puts them
    nth, got = {}, {}
    for kind, name, v in d['meshes']:
        k = nth.get(name, 0)
        nth[name] = k + 1
        got[(name, k)] = (kind, v)
    nth, worst, n = {}, 0.0, 0
    for o in src.objects:
        if o.kind != '*GEOMOBJECT' or not asecheck.is_mesh(o, char):
            continue
        k = nth.get(o.name, 0)
        nth[o.name] = k + 1
        if o.physique or o.name in moving or not o.faces:
            continue
        g = got.get((o.name, k))
        if g is None:
            res.setdefault('not_found', []).append(o.name)
            continue
        if g[1] is None or len(g[1]) < len(o.verts):
            res.setdefault('vertex_count', []).append(o.name)
            continue
        if o.verts:
            worst = max(worst, float(np.abs(g[1][:len(o.verts)] - np.array(o.verts)).max()))
        n += 1
    res['placement'] = worst
    res['placement_objects'] = n
    # skinned meshes vs the game's maths
    if d['poses'] and job.get('smd') and job.get('smb'):
        import game_pose
        pw, pm = 0.0, 0.0
        for fr, meshes in sorted(d['poses'].items()):
            names = [nm for nm, _v in meshes]
            want = game_pose.posed_vertices_for(job['smd'], job['smb'], fr, names)
            have = np.concatenate([v for _nm, v in meshes]) if meshes else np.zeros((0, 3))
            if len(want) != len(have):
                res['pose_count'] = [len(want), len(have)]
                continue
            ok = ~np.isnan(want).any(1)
            e = np.sqrt(((have[ok] - want[ok]) ** 2).sum(1))
            if len(e):
                pw, pm = max(pw, float(e.max())), max(pm, float(np.median(e)))
        res['pose_frames'] = sorted(d['poses'])
        res['pose_max'] = pw
        res['pose_median'] = pm
    # moving props vs the ASE's animation
    if d['props']:
        rig = node_rig(src.path)
        names = {}
        for o in src.objects:
            names[o.name] = names.get(o.name, 0) + 1
        by = {o.name: o for o in src.objects}
        pw = 0.0
        for t, lst in d['props'].items():
            for nm, v in lst:
                if names.get(nm, 0) != 1 or nm not in rig.bones:
                    continue
                o, b = by[nm], rig.bones[nm]
                R, p = rig.pose_bone(nm, t)
                wv = np.array(o.verts)
                if not len(wv) or len(v) < len(wv):
                    continue
                want = (wv - b.t) @ np.linalg.inv(b.R) @ R + p
                pw = max(pw, float(np.abs(v[:len(wv)] - want).max()))
        res['prop_anim'] = pw
    if not os.path.exists(exp):
        res['error'] = 'export: no file' + (' (%s)' % d['ERROR'] if 'ERROR' in d else '')
        return
    dst = asecheck.load(exp)
    c = asecheck.compare(src, dst, all_faces=True)
    res['cmp'] = {k: v for k, v in c.items() if v not in ([], 0, 0.0)}
    if not char and any(o.anim for o in src.objects):
        prop_anim_compare(job['ase'], exp, res)
    elif char and rigid_animated(src):
        prop_anim_compare(job['ase'], exp, res, names={o.name for o in rigid_animated(src)})
    if char and any(o.physique for o in dst.objects):
        anim = anim_file_for(job['ase'], src)
        if anim is None and any(o.anim for o in src.objects) and not any(o.anim for o in dst.objects):
            anim = job['ase']
            res['rig_anim'] = 'from original'
        rig_compare(job['ase'], exp, anim, res)
    if 'REIMPORT' in d:
        r = [int(x) for x in d['REIMPORT'].split()]
        res['reimport'] = r
