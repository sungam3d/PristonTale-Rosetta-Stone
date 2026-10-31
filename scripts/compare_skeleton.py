"""Bones of an original artist ASE vs a game class skeleton (.smb): names and bind pose.

    python compare_skeleton.py <file.ASE> <class.smb>
"""
import sys

import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.convert import _model_world                                # noqa: E402
from smdanim.smdfile import Model                                       # noqa: E402

ase, smb = sys.argv[1:3]
root = parse_ase(ase)
tms = {}
for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
    if find(g, '*PHYSIQUE') is not None:
        continue
    tm = find(g, '*NODE_TM')
    tms[unquote(val(g, '*NODE_NAME'))] = np.array([float(x) for k in ('*TM_ROW0', '*TM_ROW1', '*TM_ROW2', '*TM_ROW3')
                                                    for x in val(tm, k).split()])
skel = {o.name: _model_world(o) for o in Model(smb).objects}
common = sorted(set(tms) & set(skel))
print('ASE bones %d, skeleton bones %d, common %d' % (len(tms), len(skel), len(common)))
print('only in ASE:', sorted(set(tms) - set(skel)))
print('only in skeleton:', sorted(set(skel) - set(tms)))
errs = []
for n in common:
    rows, t = skel[n]
    mine = np.array([v for r in rows for v in r] + list(t))
    errs.append((np.abs(mine - tms[n]).max(), n))
errs.sort(reverse=True)
print('bind pose difference: median %.4f, worst %s' % (np.median([e for e, _ in errs]), errs[:5]))
