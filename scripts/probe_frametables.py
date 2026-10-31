"""Dump the per-object key-range tables that follow the key counts in the smOBJ3D header."""
import struct, sys
path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD\m1.smb'
want = sys.argv[2] if len(sys.argv) > 2 else 'Bip01 Pelvis'
b = open(path, 'rb').read()
I = lambda o: struct.unpack_from('<i', b, o)[0]
nobj = I(0x18); off = 0x22C + nobj * 40
for k in range(nobj):
    name = b[off + 172:off + 204].split(b'\0')[0].decode('latin-1')
    nV, nF, nT = I(off + 84), I(off + 80), I(off + 92)
    nR, nP, nS = I(off + 684), I(off + 688), I(off + 692)
    if name == want:
        print(name, 'rot', nR, 'pos', nP, 'scale', nS, 'int at 696:', I(off + 696), I(off + 700))
        for base in (696, 700):
            print('-- tables from', base)
            for t, label in enumerate(('A', 'B', 'C')):
                ents = [struct.unpack_from('<4i', b, off + base + 512 * t + 16 * i) for i in range(32)]
                print(label, [e for e in ents[:20]])
        break
    p = off + 2236 + nV * 24 + nF * 36 + nT * 32 + nR * 20 + nP * 16 + nS * 16 + nR * 64
    off = p + (nV * 32 if I(off + 16) else 0)
