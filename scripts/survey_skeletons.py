import os, sys, glob, collections
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
ROOT = r'X:\Projects\PT-World-Map\char\char'
skel = {}
for p in sorted(glob.glob(os.path.join(ROOT, 'tmABCD', '*.smb'))):
    try:
        m = Model(p)
        keys = sum(len(o.rot_keys) for o in m.objects)
        skel[os.path.basename(p)] = (set(o.name for o in m.objects), len(m.objects), m.last_frame_ticks() // 160, keys)
    except Exception as e:
        print('SMB FAIL', p, e)
for n in sorted(skel):
    s = skel[n]
    print('%-18s bones %3d  frames %6d' % (n, s[1], s[2]))
match = collections.Counter(); none = []
for p in sorted(glob.glob(os.path.join(ROOT, 'tmABCD', '*.smd'))):
    m = Model(p)
    need = set(b for o in m.objects if o.physique for b in o.physique)
    ok = [n for n in ('m1.smb','m2.smb','m3.smb','m4.smb','m5.smb','m6.smb','m7.smb','m8.smb') if n in skel and need <= skel[n][0]]
    match[tuple(ok) if ok else ('NONE',)] += 1
    if not ok and len(none) < 8: none.append((os.path.basename(p), sorted(need)[:6]))
print()
for k, v in match.most_common(): print('%4d meshes fit skeleton(s): %s' % (v, ', '.join(k)))
print(none)
mons_missing = [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT,'monster','**','*.smd'), recursive=True)
                if not os.path.isfile(os.path.splitext(p)[0]+'.smb')]
print('monster smd without same-name smb:', mons_missing)
