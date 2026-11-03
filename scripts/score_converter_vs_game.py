"""Convert skinned models and pose each converted ASE (ase_pose.py, how ASE readers see it)
against the game's own maths (game_pose.py) at a few frames inside its motions.

  python scripts/score_converter_vs_game.py <char folder> [--sample N] [--out file.tsv]
"""
import os
import random
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import ase_pose                                     # noqa: E402
import game_pose                                    # noqa: E402
from smdanim.smdfile import Model                   # noqa: E402
from smdanim.convert import Options, convert_file   # noqa: E402
from smdanim import convert                         # noqa: E402

args = sys.argv[1:]
if '--nofill' in args:                              # score the converter without _fill_static
    args.remove('--nofill')
    convert._fill_static = lambda o, pos, rot, scl: (pos, rot, scl)
sample = int(args[args.index('--sample') + 1]) if '--sample' in args else None
outp = args[args.index('--out') + 1] if '--out' in args else None
files = []
for d, _s, fs in os.walk(args[0]):
    for f in fs:
        if f.lower().endswith('.smd'):
            files.append(os.path.join(d, f))
files.sort()
random.seed(3)
if sample and len(files) > sample:
    files = random.sample(files, sample)
tmp = tempfile.mkdtemp()
rows = []
for f in files:
    out = os.path.join(tmp, 'x.ase')
    try:
        sc = convert_file(f, out, Options(animation='embed'))
    except Exception as e:
        continue
    rig = getattr(sc, 'rig', None)
    if rig is None or not rig.smb or sc.anim_mode != 'embed' or not sc.motions:
        continue
    try:
        r = ase_pose.Rig(out)
        skel, mesh = Model(rig.smb), Model(f)
    except Exception:
        continue
    from smdanim.aseparse import val, unquote
    ase_meshes = [unquote(val(g, '*NODE_NAME', '')) for g in r.meshes]
    by_mesh = {}
    for o in mesh.objects:
        if o.physique:
            by_mesh.setdefault(o.name, []).append(o)
    frames = sorted({int(m.start + (m.end - m.start) * k) for m in sc.motions[:6] for k in (0.1, 0.5, 0.9)})[:12]
    worst = med = 0.0
    for fr in frames:
        tick = fr * 160.0
        gw = game_pose.world_of(skel, tick)
        a = r.pose(tick)
        exp = []
        nth = {}
        for nm in ase_meshes:                       # the meshes the ASE has, in its order
            k = nth.get(nm, 0)
            nth[nm] = k + 1
            lst = by_mesh.get(nm, [])
            o = lst[k] if k < len(lst) else None
            if o is None:
                exp = []
                break
            for lv, bn in zip(o.local_verts, o.physique):
                exp.append(np.array(lv) @ gw[bn][0] + gw[bn][1] if bn in gw else [np.nan] * 3)
        exp = np.array(exp)
        n = min(len(a), len(exp))
        if not n:
            continue
        d = np.sqrt(((a[:n] - exp[:n]) ** 2).sum(1))
        d = d[~np.isnan(d)]
        if len(d):
            worst = max(worst, float(d.max()))
            med = max(med, float(np.median(d)))
    rows.append((worst, med, os.path.relpath(f, args[0])))
rows.sort(reverse=True)
for w, m, n in rows[:15]:
    print('max %8.3f  median %7.4f  %s' % (w, m, n))
ws = np.array([r[0] for r in rows])
print('files %d   max > 0.5: %d   > 0.1: %d   median of max %.4f' % (len(rows), (ws > 0.5).sum(), (ws > 0.1).sum(),
                                                                       np.median(ws) if len(ws) else 0))
if outp:
    with open(outp, 'w') as fh:
        for w, m, n in rows:
            fh.write('%.5f\t%.5f\t%s\n' % (w, m, n))
