"""Run max_anim_test.ms in 3dsmaxbatch and compare the skinned vertices with the game math.

    python max_anim_compare.py <ase> <smd> <smb> frame ... [--tpose] [--anim FILE]
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game_pose import posed_vertices      # noqa: E402

args = sys.argv[1:]
pose, animf = '#animated', ''
nn = '--nn' in args                          # original artist files: vertex order differs from the game's
if nn:
    args.remove('--nn')
if '--tpose' in args:
    args.remove('--tpose')
    pose = '#tpose'
if '--anim' in args:
    i = args.index('--anim')
    animf = args[i + 1]
    del args[i:i + 2]
ase, smd, smb = args[:3]
frames = [int(f) for f in args[3:]] or [0]
tmp = tempfile.gettempdir()
outp = os.path.join(tmp, 'pt_max_verts.txt')
log = os.path.join(tmp, 'pt_max_log.txt')
with open(os.path.join(tmp, 'pt_max_job.txt'), 'w') as f:
    f.write('%s\n%s\n#(%s)\n%s\n%s\n' % (ase, outp, ','.join(str(x) for x in frames), pose, animf))
for p in (outp, log):
    if os.path.exists(p):
        os.remove(p)
subprocess.run([r'C:\Program Files\Autodesk\3ds Max 2020\3dsmaxbatch.exe',
                r'X:\Projects\SMD-ANIM\scripts\max_anim_test.ms', '-listenerlog', log],
               capture_output=True, timeout=1800)
for line in open(log, encoding='utf-8', errors='replace'):
    if any(k in line for k in ('IMPORT', 'SKINNED', 'MOTIONS', 'rror', 'PT ASE', 'DONE')):
        print('  max:', line.rstrip())
got = {}
cur = None
if os.path.exists(outp):
    for line in open(outp):
        if line.startswith('FRAME'):
            cur = int(float(line.split()[1]))
            got[cur] = []
        else:
            got[cur].append([float(v) for v in line.split()])
for fr in frames:
    if fr not in got:
        print('frame %d: no data' % fr)
        continue
    exp = posed_vertices(smd, smb, fr)
    g = np.array(got[fr])
    ok = ~np.isnan(exp).any(1)
    if len(g) == len(exp) and not nn:
        d = np.sqrt(((g[ok] - exp[ok]) ** 2).sum(1))
    else:                                   # original artist mesh: nearest neighbour
        e = exp[ok]
        d = np.concatenate([np.sqrt(((e[i:i + 400, None] - g[None]) ** 2).sum(-1)).min(1) for i in range(0, len(e), 400)])
    print('frame %6d: vertices %d, error median %.4f  99%% %.4f  max %.4f'
          % (fr, len(d), np.median(d), np.percentile(d, 99), d.max()))
