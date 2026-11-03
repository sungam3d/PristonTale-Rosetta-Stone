"""Summarise blender_suite.py results.

  python report.py <results.jsonl> [...] [--each] [--fails]
"""
import collections
import json
import os
import sys

files = [a for a in sys.argv[1:] if not a.startswith('--')]
each = '--each' in sys.argv
only_fails = '--fails' in sys.argv

# what counts as a problem
LIMITS = dict(placement=0.01, pose_median=0.1, pose_max=1.0, bone_rest=0.003, rig_pose=0.05,
              prop_anim=0.05, prop_export=0.05)


def problems(r):
    p = []
    if r.get('error'):
        p.append('ERROR ' + r['error'][:160])
        return p
    for k, lim in LIMITS.items():
        v = r.get(k)
        if v is not None and v == v and v > lim:
            p.append('%s %.4f' % (k, v))
    c = r.get('cmp', {})
    if c.get('pos', 0) > 0.01:
        p.append('export pos %.4f' % c['pos'])
    if c.get('uv', 0) > 0.0005:
        p.append('export uv %.5f' % c['uv'])
    if c.get('col', 0) > 0.0006:
        p.append('export colour %.4f' % c['col'])
    for k in ('missing', 'extra', 'face_count', 'parent_diff'):
        if c.get(k):
            p.append('export %s %s' % (k, str(c[k])[:120]))
    for k in ('uv_missing', 'col_missing', 'mat_diff', 'winding'):
        if c.get(k):
            p.append('export %s %d' % (k, c[k]))
    if c.get('mat_examples'):
        p.append('mat e.g. %s' % str(c['mat_examples'][0])[:200])
    if r.get('skin_same') and r['skin_same'][0] != r['skin_same'][1]:
        p.append('skin %d/%d' % tuple(r['skin_same']))
    if r.get('rig_bones') and len(set(r['rig_bones'])) > 1:
        p.append('bones %s' % r['rig_bones'])
    ri = r.get('reimport')
    if ri and (ri[0] != ri[1] or ri[2] != ri[3] or ri[4] != ri[5]):
        p.append('reimport meshes %d->%d faces %d->%d bones %d->%d' % tuple(ri))
    for k in ('not_found', 'vertex_count', 'pose_missing', 'prop_lost'):
        if r.get(k):
            p.append('%s %s' % (k, str(r[k])[:100]))
    if r.get('images_missing'):
        p.append('images missing %d' % r['images_missing'])
    return p


rows = []
for f in files:
    for line in open(f, encoding='utf-8'):
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
by = collections.defaultdict(list)
for r in rows:
    by[r.get('group', '')].append(r)
print('%-14s %6s %6s %8s %8s %9s %9s %8s' % ('group', 'files', 'fails', 'import s', 'total s', 'pose med', 'pose max', 'rigpose'))
for g, rs in sorted(by.items()):
    nf = sum(1 for r in rs if problems(r))
    imp = [r.get('t_import', 0) for r in rs if 't_import' in r]
    tot = [r.get('t_total', 0) for r in rs]
    pm = [r['pose_median'] for r in rs if r.get('pose_median') is not None]
    px = [r['pose_max'] for r in rs if r.get('pose_max') is not None]
    rp = [r['rig_pose'] for r in rs if r.get('rig_pose') is not None]
    print('%-14s %6d %6d %8.1f %8.1f %9s %9s %8s' % (
        g, len(rs), nf, max(imp or [0]), sum(tot) / max(1, len(tot)),
        '%.4f' % max(pm) if pm else '-', '%.3f' % max(px) if px else '-', '%.4f' % max(rp) if rp else '-'))
kinds = collections.Counter()
for r in rows:
    for p in problems(r):
        kinds[p.split(' ')[0] + ' ' + (p.split(' ')[1] if p.startswith(('export', 'ERROR')) else '')] += 1
print('\nproblem kinds:', dict(kinds))
for r in rows:
    p = problems(r)
    if each or (p and only_fails) or (p and not only_fails and len(rows) < 80):
        print('%-12s %-40s %s' % (r.get('group'), os.path.basename(r['ase'])[:40], '; '.join(p) if p else 'ok'))
