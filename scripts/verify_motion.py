"""Compare .smb animation keys with the original 3ds Max ASE animation samples."""
import math, os, sys
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
from smdanim.aseparse import parse_ase, find, find_all, val, unquote

base = sys.argv[1] if len(sys.argv) > 1 else r'X:\Projects\PT-World-Map\char\char\tmABCD\M1-motion1'
smb = Model(base + '.smb')
ase = parse_ase(base + '.ASE')
anim = {}
for g in find_all(ase, '*GEOMOBJECT') + find_all(ase, '*HELPEROBJECT'):
    a = find(g, '*TM_ANIMATION')
    if a is None:
        continue
    rot = find(a, '*CONTROL_ROT_TRACK')
    pos = find(a, '*CONTROL_POS_TRACK')
    anim[unquote(val(g, '*NODE_NAME'))] = (
        [[float(x) for x in c[1].split()] for c in (rot[2] if rot else [])],
        [[float(x) for x in c[1].split()] for c in (pos[2] if pos else [])])

rot_n = pos_n = 0
rot_err = pos_err = 0.0
count_mismatch = []
for o in smb.objects:
    if o.name not in anim:
        continue
    ar, ap = anim[o.name]
    if len(ar) != len(o.rot_keys) or len(ap) != len(o.pos_keys):
        count_mismatch.append((o.name, len(ar), len(o.rot_keys), len(ap), len(o.pos_keys)))
    for (t, x, y, z, w), s in zip(o.rot_keys, ar):
        # ASE sample: tick, axis xyz, angle;  quaternion = axis * sin(angle/2), cos(angle/2)
        tick, ax, ay, az, ang = s
        h = ang / 2
        q = (ax * math.sin(h), ay * math.sin(h), az * math.sin(h), math.cos(h))
        e = min(max(abs(a - b) for a, b in zip((x, y, z, w), q)),
                max(abs(a + b) for a, b in zip((x, y, z, w), q)))      # q and -q are the same rotation
        rot_err = max(rot_err, e if t == tick else 9)
        rot_n += 1
    for (t, x, y, z), s in zip(o.pos_keys, ap):
        pos_err = max(pos_err, max(abs(x - s[1]), abs(y - s[2]), abs(z - s[3])) if t == s[0] else 9)
        pos_n += 1
print('%s: bones %d, animated in ASE %d' % (os.path.basename(base), len(smb.objects), len(anim)))
print('  rotation keys compared %d, max quaternion difference %.5f' % (rot_n, rot_err))
print('  position keys compared %d, max difference %.5f' % (pos_n, pos_err))
print('  key-count mismatches:', count_mismatch[:5])
