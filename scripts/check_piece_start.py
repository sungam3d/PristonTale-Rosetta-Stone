"""First key of a glued piece: absolute (as in the standalone file) or a delta?  And TmPrevRot there."""
import os, sys, struct
import numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.smdfile import Model
G = r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD'

def qmat(x, y, z, w):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])

def prevrot(path, bone):
    b = open(path, 'rb').read()
    I = lambda o: struct.unpack_from('<i', b, o)[0]
    nobj = I(0x18); off = 0x22C + nobj * 40
    for k in range(nobj):
        name = b[off + 172:off + 204].split(b'\0')[0].decode('latin-1')
        nV, nF, nT = I(off + 84), I(off + 80), I(off + 92)
        nR, nP, nS = I(off + 684), I(off + 688), I(off + 692)
        p = off + 2236 + nV * 24 + nF * 36 + nT * 32
        rot = [struct.unpack_from('<i4f', b, p + 20 * i) for i in range(nR)]
        p += nR * 20 + nP * 16 + nS * 16
        prev = [np.array(struct.unpack_from('<16f', b, p + 64 * i)).reshape(4, 4)[:3, :3] for i in range(nR)]
        p += nR * 64
        if name == bone:
            return rot, prev
        off = p + (nV * 32 if I(off + 16) else 0)

for bone in ('Bip01 Pelvis', 'Bip01 Spine', 'Bip01 L Thigh'):
    rot, prev = prevrot(os.path.join(G, 'm1.smb'), bone)
    own, ownprev = prevrot(os.path.join(G, 'M1-motion1.smb'), bone)
    i = next(k for k, r in enumerate(rot) if r[0] >= 55040)
    print(bone, 'glued key at piece start', np.round(rot[i], 4), ' standalone first', np.round(own[0], 4))
    print('   glued TmPrevRot there\n', np.round(prev[i], 4), '\n   standalone TmPrevRot[0]\n', np.round(ownprev[0], 4))
    acc = prev[i - 1] @ qmat(*rot[i][1:]).T
    print('   straight accumulation matches glued prev:', np.abs(acc - prev[i]).max().round(5),
          '| reset (qmat(first).T) matches:', np.abs(qmat(*rot[i][1:]).T - prev[i]).max().round(5))
