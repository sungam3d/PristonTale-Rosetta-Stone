"""Does each glued piece of m1.smb equal its standalone M1-motionN.smb (time-shifted)?"""
import os, sys
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
from smdanim.motion import smb_segments, read_inx

G = r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD'
big = Model(os.path.join(G, 'm1.smb'))
seg = smb_segments(os.path.join(G, 'm1.smb'))
bb = {o.name: o for o in big.objects}
pieces = ['tmbA01', 'M1-motion2', 'M1-motion1', 'M1-motion3', 'M1-motion4', 'M1-motion5', 'M1-motion5', 'M1-motion6',
          'M1-motion7', 'M1-motion5', 'M1-motion9', 'M1-motion12', 'M1-motion8', 'M1-motion10', 'M1-motion13',
          'M1-motion7', 'M1-motion11', 'M1-motion14']
for k, (name, (s, e)) in enumerate(zip(pieces, seg)):
    p = os.path.join(G, name + '.smb')
    if not os.path.isfile(p):
        print(k, name, 'no file', s // 160, e // 160)
        continue
    m = Model(p)
    o = next(x for x in m.objects if x.name == 'Bip01 Pelvis')
    B = bb['Bip01 Pelvis']
    first = o.rot_keys[0][0] if o.rot_keys else None
    sub = [kk for kk in B.rot_keys if s <= kk[0] <= e]
    shift = [(t - s) for t, *_ in sub[:3]]
    same = sum(1 for a, b in zip(o.rot_keys[1:], sub[1:]) if max(abs(x - y) for x, y in zip(a[1:], b[1:])) < 1e-5)
    print('%2d %-12s seg %6d-%6d (%5d frames) own keys %4d first %s | glued keys %4d first offs %s | equal %d'
          % (k, name, s // 160, e // 160, (e - s) // 160, len(o.rot_keys), first, len(sub), shift, same))
