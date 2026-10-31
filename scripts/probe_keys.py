"""Probe .smb animation key semantics using the cached TmPrevRot matrices."""
import os, sys, struct, glob
import numpy as np


def qmat(x, y, z, w):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])


def bones(path):
    b = open(path, 'rb').read()
    I = lambda o: struct.unpack_from('<i', b, o)[0]
    nobj = I(0x18)
    off = 0x22C + nobj * 40
    for k in range(nobj):
        name = b[off + 172:off + 204].split(b'\0')[0].decode('latin-1')
        nV, nF, nT = I(off + 84), I(off + 80), I(off + 92)
        nR, nP, nS = I(off + 684), I(off + 688), I(off + 692)
        p = off + 2236 + nV * 24 + nF * 36 + nT * 32
        rot = [struct.unpack_from('<i4f', b, p + 20 * i) for i in range(nR)]
        p += nR * 20 + nP * 16 + nS * 16
        prev = [np.array(struct.unpack_from('<16f', b, p + 64 * i)).reshape(4, 4)[:3, :3] for i in range(nR)]
        p += nR * 64
        yield name, rot, prev
        off = p


cands = {'absolute q_i': [], 'accumulate q0*q1*..*qi': [], 'accumulate qi*..*q1*q0': []}
for path in [r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\monster\Tees\Tees.smb',
             r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD\m1.smb']:
    for name, rot, prev in bones(path):
        accL = np.eye(3)
        accR = np.eye(3)
        for (t, x, y, z, w), P in zip(rot, prev):
            q = qmat(x, y, z, w)
            accL = accL @ q
            accR = q @ accR
            cands['absolute q_i'].append(np.abs(P - q.T).max())
            cands['accumulate q0*q1*..*qi'].append(np.abs(P - accL.T).max())
            cands['accumulate qi*..*q1*q0'].append(np.abs(P - accR.T).max())
for k, v in cands.items():
    v = np.array(v)
    print('%-28s keys %6d  max err %.5f  share < 1e-3: %.3f' % (k, len(v), v.max(), (v < 1e-3).mean()))
