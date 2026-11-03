"""Worst values per check over a suite run (3ds Max results.jsonl or Blender results_*.jsonl).

    python summary.py <results.jsonl> [...]
"""
import collections
import json
import os
import sys

rows = []
for p in sys.argv[1:]:
    rows += [json.loads(l) for l in open(p, encoding='utf-8')]
print('%d files: %s' % (len(rows), dict(collections.Counter(r['group'] for r in rows))))
for key in ('placement', 'pose_max', 'pose_median', 'prop_anim', 'prop_export', 'rig_pose', 'bone_rest'):
    vals = sorted(((r.get(key) or 0.0), os.path.basename(r['ase'].replace('\\', '/'))) for r in rows if key in r)
    if not vals:
        continue
    med = vals[len(vals) // 2][0]
    print('%-12s %4d files  median %.2g  worst: %s' % (key, len(vals), med,
          ', '.join('%s %.3g' % (n, v) for v, n in vals[-3:][::-1])))
pos = sorted(((r.get('cmp', {}).get('pos') or 0.0), os.path.basename(r['ase'].replace('\\', '/'))) for r in rows if 'cmp' in r)
print('export pos   %4d files  worst: %s' % (len(pos), ', '.join('%s %.3g' % (n, v) for v, n in pos[-3:][::-1])))
errors = [r for r in rows if 'error' in r]
print('errors: %d %s' % (len(errors), [os.path.basename(r['ase'].replace('\\', '/')) for r in errors][:5]))
times = [r['t_import'] for r in rows if 't_import' in r]
if times:
    print('import time  median %.1f s, worst %.1f s' % (sorted(times)[len(times) // 2], max(times)))
