"""Run max_bone_test.ms in 3dsmaxbatch and compare every bone's world transform with the game.

    python max_bone_compare.py <ase> <smb> frame ... [--anim FILE] [--top N]
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game_pose import world_of                 # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim.smdfile import Model              # noqa: E402

args = sys.argv[1:]
animf, top = '', 8
if '--anim' in args:
    i = args.index('--anim')
    animf = args[i + 1]
    del args[i:i + 2]
if '--top' in args:
    i = args.index('--top')
    top = int(args[i + 1])
    del args[i:i + 2]
ase, smb = args[:2]
frames = [float(f) for f in args[2:]] or [0]
tmp = tempfile.gettempdir()
outp = os.path.join(tmp, 'pt_max_bones.txt')
log = os.path.join(tmp, 'pt_max_blog.txt')
with open(os.path.join(tmp, 'pt_max_bjob.txt'), 'w') as f:
    f.write('%s\n%s\n#(%s)\n#animated\n%s\n' % (ase, outp, ','.join(str(x) for x in frames), animf))
for p in (outp, log):
    if os.path.exists(p):
        os.remove(p)
subprocess.run([r'C:\Program Files\Autodesk\3ds Max 2020\3dsmaxbatch.exe',
                r'X:\Projects\SMD-ANIM\scripts\max_bone_test.ms', '-listenerlog', log],
               capture_output=True, timeout=1800)
for line in open(log, encoding='utf-8', errors='replace'):
    if any(k in line for k in ('BONES', 'rror', 'PT ASE', 'DONE')):
        print('  max:', line.rstrip()[:300])
got, cur = {}, None
if os.path.exists(outp):
    for line in open(outp, encoding='utf-8', errors='replace'):
        if line.startswith('FRAME'):
            cur = float(line.split()[1])
            got[cur] = {}
        elif '|' in line:
            nm, v = line.rstrip('\n').rsplit('|', 1)
            got[cur][nm] = np.array([float(x) for x in v.split()]).reshape(4, 3)
skel = Model(smb)
for fr in frames:
    if fr not in got:
        print('frame %g: no data' % fr)
        continue
    w = world_of(skel, fr * 160.0)
    errs = []
    for nm, m in got[fr].items():
        if nm in w:
            R, p = w[nm]
            errs.append((float(np.linalg.norm(m[3] - p)), float(np.abs(m[:3] - R).max()), nm))
    errs.sort(reverse=True)
    print('frame %g: %d bones, worst pos %.4f, worst rows %.4f' % (fr, len(errs), errs[0][0] if errs else 0,
                                                                  max([e[1] for e in errs] or [0])))
    for e in errs[:top]:
        print('    %-28s pos %.4f rows %.4f' % (e[2], e[0], e[1]))
