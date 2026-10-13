"""Survey character / monster SMD + SMB files with the current PT model reader."""
import os, sys, glob, collections, traceback
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model, file_kind, SMDError

ROOT = r'X:\Projects\PT-World-Map\char\char'
stats = collections.Counter()
problems = []
rows = []
for sub in ('monster', 'tmABCD'):
    for p in sorted(glob.glob(os.path.join(ROOT, sub, '**', '*.smd'), recursive=True)):
        rel = os.path.relpath(p, ROOT)
        try:
            k = file_kind(p)
        except OSError as e:
            stats[sub + ' unreadable'] += 1
            continue
        if k != 'model':
            stats[sub + ' kind=' + str(k)] += 1
            problems.append((rel, 'header: ' + str(k)))
            continue
        try:
            m = Model(p)
        except Exception as e:
            stats[sub + ' PARSE FAIL'] += 1
            problems.append((rel, 'parse: %s' % e))
            continue
        phys = [o for o in m.objects if o.physique]
        bones_needed = set(b for o in phys for b in o.physique)
        smb = os.path.splitext(p)[0] + '.smb'
        status = 'static'
        if phys:
            if os.path.isfile(smb):
                try:
                    b = Model(smb)
                    have = set(o.name for o in b.objects)
                    miss = bones_needed - have
                    status = 'skinned, own .smb OK' if not miss else 'skinned, own .smb MISSING %d bones' % len(miss)
                    if miss:
                        problems.append((rel, 'bones not in %s: %s' % (os.path.basename(smb), sorted(miss)[:5])))
                except Exception as e:
                    status = 'skinned, .smb PARSE FAIL'
                    problems.append((os.path.relpath(smb, ROOT), 'parse: %s' % e))
            else:
                status = 'skinned, no matching .smb'
        stats[sub + ' ' + status] += 1
        rows.append((rel, len(m.objects), len(phys), len(bones_needed), status))

for k, v in sorted(stats.items()):
    print('%5d  %s' % (v, k))
print('\nproblems (first 25):')
for r in problems[:25]:
    print('  ', r)
