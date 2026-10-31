"""How do monsters split model and animation?  For every client .inx: model file vs motion
file, and how many glued motion pieces the motion .smb has."""
import collections
import os
import sys

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.motion import read_inx, smb_segments          # noqa: E402

ROOT = r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\monster'
kinds = collections.Counter()
examples = collections.defaultdict(list)
for d, _s, files in os.walk(ROOT):
    for n in files:
        if not n.lower().endswith('.inx'):
            continue
        mi = read_inx(os.path.join(d, n))
        model = os.path.splitext(os.path.basename(mi.model_file.replace('\\', '/')))[0]
        motion = os.path.splitext(os.path.basename(mi.motion_file.replace('\\', '/')))[0]
        smb = next((os.path.join(d, f) for f in files if f.lower() == motion.lower() + '.smb'), None)
        pieces = [s for s in smb_segments(smb) if s[1] > s[0]] if smb else []
        same = model.lower() == motion.lower()
        key = ('model = motion file' if same else 'separate motion file', 'pieces %d' % len(pieces) if smb else 'no .smb')
        kinds[key] += 1
        if len(examples[key]) < 4:
            examples[key].append('%s (%s / %s)' % (n, model, motion))
for k, v in kinds.most_common():
    print('%-24s %-10s %4d   e.g. %s' % (k[0], k[1], v, ', '.join(examples[k])))
