"""Check the ASE -> model SMD/SMB encoder against the game's own builds (reference\\orig2012: NAME.ase
with the game's NAME.smd, and NAME.smb when the .ase has "Bip" bones).  Object by object, field by field.

    python check_ase2model.py <tree> <smd2ase.exe> <work folder> [name filter]
"""
import os
import struct
import subprocess
import sys

H = 0x22C
FIELDS = [('maxZ', 44), ('maxY', 52), ('maxX', 60), ('dBound', 68), ('Bound', 72), ('MaxVertex', 76), ('MaxFace', 80),
          ('nVertex', 84), ('nFace', 88), ('nTexLink', 92), ('rotN', 684), ('posN', 688), ('sclN', 692)]


def model(path):
    b = open(path, 'rb').read()
    if not b.startswith(b'SMD Model'):
        return None
    nobj, nmat = struct.unpack_from('<2i', b, 24)
    tmfc = struct.unpack_from('<i', b, 40)[0]
    o = H + 40 * nobj
    mats = []
    if nmat:
        o += 88
        for m in range(nmat):
            raw = bytearray(b[o:o + 320]); o += 320
            names = []
            if struct.unpack_from('<I', raw, 0)[0]:
                n = struct.unpack_from('<i', b, o)[0]
                names = [x.lower() for x in b[o + 4:o + 4 + n].split(b'\0')[:-1]]
                names = [x.rstrip(bytes([0xCC])) for x in names[0::2]]   # (Name only: NameA is the shared
                                                                         #  texture record of the first loader)
                o += 4 + n
            for k in list(range(8, 40, 4)) + list(range(176, 304, 4)):
                struct.pack_into('<I', raw, k, 1 if struct.unpack_from('<I', raw, k)[0] else 0)
            mats.append((bytes(raw[:320]), names))
    objs = []
    for k in range(nobj):
        s = b[o:o + 2236]
        d = {n: struct.unpack_from('<i', s, off)[0] for n, off in FIELDS}
        d['name'] = s[172:204].split(b'\0')[0]
        d['parent'] = s[204:236].split(b'\0')[0]
        d['Tm'] = struct.unpack_from('<16i', s, 240)
        d['TmInv'] = struct.unpack_from('<16i', s, 304)
        d['TmRotate'] = struct.unpack_from('<16i', s, 432)
        d['q'] = struct.unpack_from('<4f', s, 628)
        d['s'] = struct.unpack_from('<3i', s, 644)
        d['p'] = struct.unpack_from('<3i', s, 656)
        phys = struct.unpack_from('<I', s, 16)[0] != 0
        tlbase = struct.unpack_from('<I', s, 12)[0]
        nv, nf, nt = d['nVertex'], d['nFace'], d['nTexLink']
        p = o + 2236
        d['verts'] = [struct.unpack_from('<6i', b, p + 24 * i) for i in range(nv)]; p += 24 * nv
        faces = [struct.unpack_from('<4H24xI', b, p + 36 * i) for i in range(nf)]; p += 36 * nf
        tls = [(struct.unpack_from('<6f', b, p + 32 * i), struct.unpack_from('<I', b, p + 32 * i + 28)[0]) for i in range(nt)]; p += 32 * nt
        def chain(ptr):
            out = []
            while ptr and len(out) < 9:
                i = (ptr - tlbase) // 32
                if i < 0 or i >= nt:
                    break
                out.append(tls[i][0]); ptr = tls[i][1]
            return out
        d['faces'] = [f[:4] for f in faces]
        d['uv'] = [chain(f[4]) for f in faces]
        d['rot'] = [struct.unpack_from('<i4f', b, p + 20 * i) for i in range(d['rotN'])]; p += 20 * d['rotN']
        d['pos'] = [struct.unpack_from('<i3f', b, p + 16 * i) for i in range(d['posN'])]; p += 16 * d['posN']
        d['scl'] = [struct.unpack_from('<4i', b, p + 16 * i) for i in range(d['sclN'])]; p += 16 * d['sclN']
        d['prev'] = [struct.unpack_from('<16f', b, p + 64 * i) for i in range(d['rotN'])]; p += 64 * d['rotN']
        d['phys'] = None
        if phys:
            d['phys'] = [b[p + 32 * i:p + 32 * i + 32].split(b'\0')[0] for i in range(nv)]; p += 32 * nv
        objs.append(d)
        o = p
    return dict(mats=mats, objs=objs, tmfc=tmfc)


def close(a, b, tol):
    return len(a) == len(b) and all(abs(x - y) <= tol * max(1.0, abs(x)) for x, y in zip(a, b))


def compare(g, o, bones=False):
    r = []
    if len(g['mats']) != len(o['mats']):
        r.append('materials %d vs %d' % (len(g['mats']), len(o['mats'])))
    else:
        bad = [i for i, (x, y) in enumerate(zip(g['mats'], o['mats'])) if x != y]
        if bad:
            x, y = g['mats'][bad[0]], o['mats'][bad[0]]
            offs = [k for k in range(0, 320, 4) if x[0][k:k + 4] != y[0][k:k + 4]]
            r.append('materials %d differ (#%d offsets %s names %s / %s)' % (len(bad), bad[0], offs[:6], x[1][:2], y[1][:2]))
    if len(g['objs']) != len(o['objs']):
        r.append('objects %d vs %d: %s / %s' % (len(g['objs']), len(o['objs']), [x['name'] for x in g['objs']][:6], [x['name'] for x in o['objs']][:6]))
        return r
    cnt = {}
    for a, b in zip(g['objs'], o['objs']):
        def bad(k, v=None):
            cnt.setdefault(k, [0, None])
            cnt[k][0] += 1
            if cnt[k][1] is None:
                cnt[k][1] = (a['name'], v)
        for n, _ in FIELDS:
            if bones and n == 'nTexLink':
                continue                      # (bone faces: whatever material the game read last)
            if a[n] != b[n]:
                bad(n, (a[n], b[n]))
        for n in ('name', 'parent', 'Tm', 'TmInv', 'TmRotate', 's', 'p'):
            if a[n] != b[n]:
                bad(n, (a[n], b[n]))
        if not close(a['q'], b['q'], 1e-6):
            bad('q', (a['q'], b['q']))
        if a['verts'] != b['verts']:
            pos = sum(1 for x, y in zip(a['verts'], b['verts']) if x[:3] != y[:3])
            nrm = sum(1 for x, y in zip(a['verts'], b['verts']) if max(abs(p - q) for p, q in zip(x[3:], y[3:])) > 1)
            if pos or nrm:
                ex = next((i for i, (x, y) in enumerate(zip(a['verts'], b['verts'])) if x != y), None)
                bad('verts', (pos, nrm, ex, a['verts'][ex] if ex is not None and ex < len(a['verts']) else None,
                              b['verts'][ex] if ex is not None and ex < len(b['verts']) else None))
        if [f[:3] if bones else f for f in a['faces']] != [f[:3] if bones else f for f in b['faces']]:
            bad('faces', next(((x, y) for x, y in zip(a['faces'], b['faces']) if x != y), None))
        if len(a['uv']) == len(b['uv']) and not bones:
            for x, y in zip(a['uv'], b['uv']):
                if len(x) != len(y) or any(not close(p, q, 3e-7) for p, q in zip(x, y)):
                    bad('uv', (x, y)); break
        for n, tol in (('rot', 3e-7), ('pos', 3e-7), ('prev', 3e-7)):
            if len(a[n]) != len(b[n]) or any(not close(x, y, tol) for x, y in zip(a[n], b[n])):
                ex = next(((x, y) for x, y in zip(a[n], b[n]) if not close(x, y, tol)), (len(a[n]), len(b[n])))
                bad(n, ex)
        if a['scl'] != b['scl']:
            bad('scl', next(((x, y) for x, y in zip(a['scl'], b['scl']) if x != y), (len(a['scl']), len(b['scl']))))
        if a['phys'] != b['phys']:
            bad('phys', (a['phys'][:3] if a['phys'] else None, b['phys'][:3] if b['phys'] else None))
    for k, (n, ex) in cnt.items():
        r.append('%s: %d objects, e.g. %s' % (k, n, str(ex)[:260]))
    return r


def texdir(m):
    for raw, names in m['mats']:
        for n in names:
            if b'\\' in n:
                return n[:n.rfind(b'\\') + 1].decode('latin1')
    return ''


def main():
    tree, exe, work = sys.argv[1:4]
    flt = sys.argv[4].lower() if len(sys.argv) > 4 else ''
    os.makedirs(work, exist_ok=True)
    total = exact = 0
    for dp, dn, fn in os.walk(tree):
        low = {f.lower(): f for f in fn}
        for f in sorted(fn):
            if not f.lower().endswith('.ase') or flt not in f.lower():
                continue
            base = f[:-4].lower()
            smd, smb = low.get(base + '.smd'), low.get(base + '.smb')
            if not smd:
                continue
            g = model(os.path.join(dp, smd))
            if g is None:
                continue
            gb = model(os.path.join(dp, smb)) if smb else None
            best = None
            for mode in ('new', 'old'):              # (normals: both forms among the shipped models)
                os_, ob = os.path.join(work, 'x.smd'), os.path.join(work, 'x.smb')
                for p in (os_, ob):
                    if os.path.exists(p):
                        os.remove(p)
                cmd = [exe, '--ase2model', os.path.join(dp, f), os_, ob if smb else '-', texdir(g), 'game']
                if mode == 'old':
                    cmd.append('oldnormals')
                r = subprocess.run(cmd, capture_output=True, text=True)
                if not os.path.exists(os_):
                    best = (mode, ['FAIL ' + r.stdout[-300:] + r.stderr[-600:]])
                    break
                probs = ['smd ' + x for x in compare(g, model(os_))]
                if gb is not None:
                    if os.path.exists(ob):
                        probs += ['smb ' + x for x in compare(gb, model(ob), True)]
                    else:
                        probs.append('smb not written')
                if best is None or len(probs) < len(best[1]):
                    best = (mode, probs)
            total += 1
            probs = best[1]
            if not probs:
                exact += 1
                print('EXACT', os.path.join(dp, f))
            else:
                print('DIFF ', os.path.join(dp, f))
                for x in probs:
                    print('        ' + x)
    print('%d of %d models exact' % (exact, total))


if __name__ == '__main__':
    main()
