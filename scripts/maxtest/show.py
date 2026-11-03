"""Print the 3ds Max suite results, one line per file.   python show.py <results.jsonl> [--fails]"""
import json
import os
import sys

KEYS = ('placement', 'pose_max', 'prop_anim', 'prop_export', 'rig_pose', 'skin_same', 'cmp', 'reimport',
        'error', 'not_found', 'vertex_count', 'pose_count', 't_import')
LIMITS = dict(placement=0.02, pose_max=0.5, prop_anim=0.05, prop_export=0.05, rig_pose=0.01)


def problems(r):
    p = [k for k, lim in LIMITS.items() if r.get(k, 0) > lim]
    c = r.get('cmp', {})
    p += ['cmp.' + k for k in c if k not in ('objects', 'faces', 'pos', 'uv', 'col', 'mat_examples')]
    # (3ds Max stores vertices and UVs as 32-bit floats: 0.0078 steps at map coordinates ~70000)
    for k, lim in (('pos', 0.02), ('uv', 5e-4), ('col', 1e-3)):
        if c.get(k, 0) > lim:
            p.append('cmp.' + k)
    s = r.get('skin_same')
    if s and s[0] != s[1]:
        p.append('skin')
    ri = r.get('reimport')
    if ri and (ri[0] != ri[1] or ri[2] != ri[3] or ri[4] != ri[5]):
        p.append('reimport')
    for k in ('error', 'not_found', 'vertex_count', 'pose_count'):
        if k in r:
            p.append(k)
    return p


rows = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
fails = '--fails' in sys.argv
for r in rows:
    p = problems(r)
    if fails and not p:
        continue
    keep = {k: r[k] for k in KEYS if k in r}
    print('%-11s %-32s %s %s' % (r['group'], os.path.basename(r['ase'].replace('\\', '/'))[:32],
                                 ','.join(p) or 'ok', json.dumps(keep)[:500]))
print('%d files, %d with problems' % (len(rows), sum(1 for r in rows if problems(r))))
