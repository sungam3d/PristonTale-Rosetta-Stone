"""Re-run the Python checks on a Max suite run kept with PT_SUITE_KEEP=1 (no 3ds Max needed).

    python recheck.py <jobs.json> <out dir>      (the same arguments as run_max_suite.py, 1 worker)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from maxcheck import asecheck, check, read_dump          # noqa: E402

jobs_path, out = sys.argv[1:3]
jobs = json.load(open(jobs_path, encoding='utf-8'))
tmp = os.path.join(out, 'tmp')
for k in range(8):
    for i, j in enumerate(jobs):
        dump = os.path.join(tmp, 'dump_%d_%d.txt' % (k, i))
        exp = os.path.join(tmp, 'exp_%d_%d.ase' % (k, i))
        if not os.path.exists(dump):
            continue
        d = read_dump(dump)
        res = dict(ase=j['ase'], group=j['group'])
        try:
            check(j, asecheck.load(j['ase']), d, exp, res)
        except Exception as e:
            res['error'] = 'check: %s' % e
        keep = {x: res[x] for x in ('placement', 'pose_max', 'prop_anim', 'prop_export', 'rig_pose', 'error') if x in res}
        print('%-12s %-28s %s' % (j['group'], os.path.basename(j['ase'].replace('\\', '/'))[:28], json.dumps(keep)))
