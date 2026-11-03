"""Checks shared by the Blender and the 3ds Max test suites (plain Python, no bpy / MAXScript)."""
import os

import numpy as np


def node_rig(path):
    """ase_pose evaluation of every node of a file (meshes too), for rigid prop animation."""
    from ase_pose import Rig, Bone
    from smdanim.aseparse import parse_ase, find_all

    class Nodes(Rig):
        def __init__(self, p):
            self.bones = {}
            root = parse_ase(p)
            for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
                b = Bone(g)
                self.bones.setdefault(b.name, b)
            self.meshes, self.verts, self.vbone = [], [], []
    return Nodes(path)


def animated_names(src):
    """Nodes that move: own keys, or a parent that moves."""
    par = {o.name: o.parent for o in src.objects}
    keyed = {o.name for o in src.objects if o.anim}
    out = set()
    for o in src.objects:
        n, seen = o.name, 0
        while n and seen < 200:
            if n in keyed:
                out.add(o.name)
                break
            n, seen = par.get(n, ''), seen + 1
    return out


def prop_anim_compare(orig, exported, res, names=None):
    """Every animated node's (or only `names`') world transform over the timeline, original vs
    exported."""
    a, b = node_rig(orig), node_rig(exported)
    last = max([k[0] for bo in a.bones.values() for k in bo.pos + bo.rot + bo.scl] or [0])
    worst = 0.0
    lost = [n for n, bo in a.bones.items() if (bo.pos or bo.rot) and n in b.bones and not (b.bones[n].pos or b.bones[n].rot)]
    for t in np.linspace(0, last, 9, endpoint=False):
        for n, bo in a.bones.items():
            if not (bo.pos or bo.rot) or n not in b.bones or (names is not None and n not in names):
                continue
            Ra, pa = a.pose_bone(n, float(t))
            Rb, pb = b.pose_bone(n, float(t))
            worst = max(worst, float(np.linalg.norm(pa - pb)), float(np.abs(Ra - Rb).max()) * 10.0)
    res['prop_export'] = worst
    if lost:
        res['prop_lost'] = lost[:5]


def anim_file_for(src_path, sc):
    """The shared class animation a converted player armour names (for comparing poses)."""
    for k, v in sc.pt_animation or []:
        if k == '*PT_ANIMATION_FILE':
            p = os.path.join(os.path.dirname(src_path), v.strip().strip('"'))
            if os.path.isfile(p):
                return p
    return None


def rig_compare(orig, exported, anim, res):
    from ase_pose import Rig
    a, b = Rig(orig, anim), Rig(exported, anim)
    common = set(a.bones) & set(b.bones)
    res['rig_bones'] = [len(a.bones), len(b.bones), len(common)]
    res['bone_rest'] = float(max([np.abs(a.bones[n].R - b.bones[n].R).max() + np.abs(a.bones[n].t - b.bones[n].t).max()
                                  for n in common] or [0.0]))
    # skinned meshes paired by name (a name used twice: in order); vertex by vertex, or face corner
    # by face corner where the counts differ (Blender gives doubled faces their own vertices)
    ia, ib, unpaired = [], [], []
    by, nth = {}, {}
    for p in b.parts:
        by.setdefault(p[0], []).append(p)
    for name, s, n, corners in a.parts:
        k = nth.get(name, 0)
        nth[name] = k + 1
        lst = by.get(name, [])
        if k >= len(lst):
            unpaired.append(name)
            continue
        _nb, sb, mb, cb = lst[k]
        if n == mb:
            ia += range(s, s + n)
            ib += range(sb, sb + mb)
        elif len(corners) == len(cb):
            ia += corners
            ib += cb
        else:
            unpaired.append(name)
    if unpaired:
        res['skin_unpaired'] = unpaired[:5]
    res['skin_same'] = [int(sum(a.vbone[x] == b.vbone[y] for x, y in zip(ia, ib))), len(ia)]
    last = max([k[0] for r in (a, b) for bo in r.bones.values() for k in bo.pos + bo.rot] or [0])
    # not the very last tick: the game never shows a channel's last key (from it on, the stored
    # pose), and some files carry junk there (Grangium: a bone scaled to 0, its child to 62)
    ticks = sorted(set([0] + [int(last * (i + 0.37) / 6) for i in range(6)]))
    worst = 0.0
    for t in ticks:
        pa, pb = a.pose(t)[ia], b.pose(t)[ib]
        n = min(len(pa), len(pb))
        if n:
            worst = max(worst, float(np.sqrt(((pa[:n] - pb[:n]) ** 2).sum(1)).max()))
    res['rig_pose'] = worst
