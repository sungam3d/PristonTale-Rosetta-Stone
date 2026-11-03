"""Build the job lists for blender_suite.py.

  python make_jobs.py <corpus dir> <game dir> <out dir> [--sample N]

Converted files get their source .smd and the skeleton the converter picks (for the pose check
against the game's maths). Original developer ASE files are added as they are.
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from smdanim.smdfile import Model, SMDError, file_kind   # noqa: E402
from smdanim import motion                                # noqa: E402

corpus, game, outdir = sys.argv[1:4]
sample = None
if '--sample' in sys.argv:
    sample = int(sys.argv[sys.argv.index('--sample') + 1])
ORIGINALS = [('orig_map', r'X:\Projects\PT-World-Map\reference\orig2012'),
             ('orig_char', r'X:\Projects\SMD-ANIM\Martial Artist ASE'),
             ('orig_assets', r'X:\Pristontale Exercitus\PT-Assets\Field\ase')]

jobs = {}
for d, _s, fs in os.walk(corpus):
    for f in fs:
        if not f.lower().endswith('.ase'):
            continue
        p = os.path.join(d, f)
        rel = os.path.relpath(p, corpus)
        low = rel.lower().replace('\\', '/')
        smd = os.path.join(game, os.path.splitext(rel)[0] + '.smd')
        job = dict(ase=p, smd='', smb='')
        if f.lower().endswith('_motions.ase'):
            group = 'class_motions'
        elif low.startswith('field/'):
            kind = file_kind(smd) if os.path.isfile(smd) else ''
            group = 'map' if kind == 'stage' else 'map_object'
        elif low.startswith('char/monster/'):
            group = 'monster'
        elif low.startswith('char/npc/'):
            group = 'npc'
        elif low.startswith('char/tmabcd/'):
            group = 'armour'
        elif low.startswith('image/'):
            group = 'item'
        else:
            group = 'other'
        job['group'] = group
        if os.path.isfile(smd) and group not in ('map', 'class_motions'):
            try:
                m = Model(smd)
                bones = sorted(set(bn for o in m.objects if o.physique for bn in o.physique if bn))
                if bones:
                    rig = motion.find_rig(smd, bones)
                    if rig.smb:
                        job['smd'], job['smb'] = smd, rig.smb
            except (SMDError, Exception):
                pass
        jobs.setdefault(group, []).append(job)
for group, root in ORIGINALS:
    for d, _s, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith('.ase'):
                jobs.setdefault(group, []).append(dict(ase=os.path.join(d, f), smd='', smb='', group=group))

os.makedirs(outdir, exist_ok=True)
random.seed(7)
allj = []
for g, js in sorted(jobs.items()):
    js.sort(key=lambda j: j['ase'].lower())
    if sample and len(js) > sample:
        js = random.sample(js, sample)
    print('%-14s %5d files (%d with game skeleton)' % (g, len(js), sum(1 for j in js if j['smb'])))
    allj += js
json.dump(allj, open(os.path.join(outdir, 'all_jobs.json'), 'w'), indent=0)
print('total', len(allj))
