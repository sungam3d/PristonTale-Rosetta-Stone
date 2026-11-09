"""Check the ASE -> SMD map encoder against the game's own builds.

For every map in a folder tree that has both NAME.ase and the game's NAME.smd (reference\\orig2012),
the .ase is encoded with smd2ase --ase2smd (same lighting values and texture folder as the shipped
.smd) and the two files are compared section by section.

    python check_ase2smd.py <tree> <smd2ase.exe> <work folder> [name filter]
"""
import os
import struct
import subprocess
import sys

H = 0x22C


def stage(path):
    b = open(path, 'rb').read()
    if not b.startswith(b'SMD Stage'):
        return None
    S = H
    nv, nf, ntl, nl = struct.unpack_from('<4i', b, S + 0x40034)
    contrast, bright, lx, ly, lz = struct.unpack_from('<5i', b, S + 0x40048)
    area_size = struct.unpack_from('<i', b, S + 0x40060)[0]
    rect = struct.unpack_from('<4i', b, S + 0x40064)
    tlbase = struct.unpack_from('<I', b, S + 0x40020)[0]
    present = [struct.unpack_from('<I', b, S + 4 + 4 * i)[0] != 0 for i in range(65536)]
    G = S + 0x40074
    cnt = struct.unpack_from('<I', b, G + 8)[0]
    reform = struct.unpack_from('<i', b, G + 12)[0]
    o = G + 88
    mats = []
    for m in range(cnt):
        raw = bytearray(b[o:o + 320])
        o += 320
        names = []
        if struct.unpack_from('<I', raw, 0)[0]:
            n = struct.unpack_from('<i', b, o)[0]
            names = b[o + 4:o + 4 + n].split(b'\0')[:-1]
            o += 4 + n
        for k in range(8):                       # texture handle pointers
            struct.pack_into('<I', raw, 8 + 4 * k, 1 if struct.unpack_from('<I', raw, 8 + 4 * k)[0] else 0)
        for k in range(32):
            struct.pack_into('<I', raw, 176 + 4 * k, 1 if struct.unpack_from('<I', raw, 176 + 4 * k)[0] else 0)
        # (a name starting with byte 1: the game had loaded the texture, a run-time mark)
        mats.append((bytes(raw), [b'' if x.startswith(bytes([1])) else x.lower() for x in names]))
    V = o
    verts = [struct.unpack_from('<3i4h', b, V + 28 * i + 8) for i in range(nv)]
    F = V + 28 * nv
    faces = []
    for i in range(nf):
        a, bb, c, m, tl, nx, ny, nz, n3 = struct.unpack_from('<4HI4h', b, F + 28 * i + 8)
        faces.append((a, bb, c, m, -1 if tl == 0 else (tl - tlbase) // 32, nx, ny, nz))
    T = F + 28 * nf
    tls = []
    for i in range(ntl):
        uv = struct.unpack_from('<6f', b, T + 32 * i)
        nxt = struct.unpack_from('<I', b, T + 32 * i + 28)[0]
        tls.append((uv, -1 if nxt == 0 else (nxt - tlbase) // 32))
    L = T + 32 * ntl
    lights = [struct.unpack_from('<5i3h', b, L + 28 * i) for i in range(nl)]
    o = L + 28 * nl
    es = 4 if o + 8 <= len(b) and struct.unpack_from('<H', b, o + 6)[0] == 0 else 2   # (current clients: 32-bit)
    areas = []
    for i in range(65536):
        y, x = divmod(i, 256)
        if present[x * 256 + y]:
            sl = struct.unpack_from('<i', b, o)[0] if o + 4 <= len(b) else -1
            if sl <= 0 or o + 4 + es * sl > len(b):
                areas.append(((x, y), 'unreadable'))
                break
            areas.append(((x, y), struct.unpack_from('<%d%s' % (sl, 'I' if es == 4 else 'H'), b, o + 4)))
            o += 4 + es * sl
    return dict(nv=nv, nf=nf, ntl=ntl, nl=nl, light=(contrast, bright, lx, ly, lz), area_size=area_size,
                rect=rect, reform=reform, mats=mats, verts=verts, faces=faces, tls=tls, lights=lights, areas=areas,
                tail=len(b) - o)


def chains(s):
    out = []
    for f in s['faces']:
        c = []
        t = f[4]
        while t >= 0 and len(c) < 9:
            c.append(s['tls'][t][0])
            t = s['tls'][t][1]
        out.append(c)
    return out


def texdir(s):
    for raw, names in s['mats']:
        for n in names:
            if b'\\' in n:
                return n[:n.rfind(b'\\') + 1].decode('latin1')
    return ''


def compare(a, b):
    """a = game, b = ours -> list of (section, problems, of)"""
    r = []
    for k in ('nv', 'nf', 'ntl', 'nl', 'area_size', 'rect', 'reform', 'tail'):
        if a[k] != b[k]:
            r.append((k, '%s vs %s' % (a[k], b[k])))
    if len(a['mats']) != len(b['mats']):
        r.append(('materials', '%d vs %d' % (len(a['mats']), len(b['mats']))))
    else:
        def same(x, y):            # ("dir\\" + 0xCC: an empty bitmap name in a debug build)
            return x[0] == y[0] and [n.rstrip(bytes([0xCC])) for n in x[1]] == [n.rstrip(bytes([0xCC])) for n in y[1]]
        bad = [i for i, (x, y) in enumerate(zip(a['mats'], b['mats'])) if not same(x, y)]
        if bad:
            i = bad[0]
            diff = [o for o in range(0, 320, 4) if a['mats'][i][0][o:o + 4] != b['mats'][i][0][o:o + 4]]
            r.append(('materials', '%d differ, first #%d at offsets %s names %s / %s' % (
                len(bad), i, diff[:8], a['mats'][i][1][:2], b['mats'][i][1][:2])))
    n = min(len(a['verts']), len(b['verts']))
    pos = sum(1 for i in range(n) if a['verts'][i][:3] != b['verts'][i][:3])
    col = 0      # (one step: rounding of the light maths)
    col1 = sum(1 for i in range(n) if max(abs(p - q) for p, q in zip(a['verts'][i][3:], b['verts'][i][3:])) > 1)
    if pos or col1:
        ex = next((i for i in range(n) if a['verts'][i][:3] != b['verts'][i][:3] or max(abs(p - q) for p, q in zip(a['verts'][i][3:], b['verts'][i][3:])) > 1), None)
        r.append(('vertices', 'pos %d, colour %d (%d off by more than 1) of %d; first #%s %s / %s' % (
            pos, col, col1, n, ex, a['verts'][ex] if ex is not None else '', b['verts'][ex] if ex is not None else '')))
    n = min(len(a['faces']), len(b['faces']))
    fv = sum(1 for i in range(n) if a['faces'][i][:4] != b['faces'][i][:4])
    fm = sum(1 for i in range(n) if a['faces'][i][3] != b['faces'][i][3])
    fn = sum(1 for i in range(n) if max(abs(p - q) for p, q in zip(a['faces'][i][5:], b['faces'][i][5:])) > 1)
    if fv or fn:
        ex = next((i for i in range(n) if a['faces'][i][:4] != b['faces'][i][:4] or max(abs(p - q) for p, q in zip(a['faces'][i][5:], b['faces'][i][5:])) > 1), None)
        r.append(('faces', 'index/material %d (material %d), normal %d of %d; first #%s %s / %s' % (
            fv, fm, fn, n, ex, a['faces'][ex], b['faces'][ex])))
    ca, cb = chains(a), chains(b)
    n = min(len(ca), len(cb))
    cnt_bad = sum(1 for i in range(n) if len(ca[i]) != len(cb[i]))
    def far(x, y):                 # more than one float step apart
        return any(abs(p - q) > 2.5e-7 * max(1.0, abs(p)) for u, v in zip(x, y) for p, q in zip(u, v))
    uv_bad = sum(1 for i in range(n) if len(ca[i]) == len(cb[i]) and far(ca[i], cb[i]))
    uv_far = sum(1 for i in range(n) if len(ca[i]) == len(cb[i]) and ca[i] != cb[i] and
                 max(abs(p - q) for x, y in zip(ca[i], cb[i]) for p, q in zip(x, y)) > 1e-4)
    if cnt_bad or uv_bad:
        ex = next((i for i in range(n) if len(ca[i]) != len(cb[i]) or far(ca[i], cb[i])), None)
        r.append(('uv', 'layer count %d, uv %d (%d by more than 1e-4) of %d faces; first #%s %s / %s' % (
            cnt_bad, uv_bad, uv_far, n, ex, ca[ex][:2], cb[ex][:2])))
    if a['lights'] != b['lights']:
        r.append(('lights', '%s / %s' % (a['lights'][:2], b['lights'][:2])))
    if a['areas'] != b['areas']:
        da = dict(a['areas']); db = dict(b['areas'])
        diff = [k for k in set(da) | set(db) if da.get(k) != db.get(k)]
        r.append(('areas', '%d cells differ of %d' % (len(diff), len(da))))
    return r


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
            smd = low.get(f[:-4].lower() + '.smd')
            if not smd:
                continue
            gp = os.path.join(dp, smd)
            g = stage(gp)
            if g is None:
                continue
            c, br, lx, ly, lz = g['light']
            best = None
            for mode in ('double', 'single'):          # (the shipped maps were built in either FPU mode)
                out = os.path.join(work, mode + '_' + smd)
                cmd = [exe, '--ase2smd', os.path.join(dp, f), out, texdir(g), 'game', str(c), str(br), str(lx), str(ly), str(lz)]
                if mode == 'single':
                    cmd.append('single')
                cmd.append('2012')
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.returncode != 0 or not os.path.exists(out):
                    print('FAIL', f, p.stdout.strip(), p.stderr.strip()[-300:])
                    break
                probs = [x for x in compare(g, stage(out)) if x[0] != 'tail']
                if best is None or len(probs) < len(best[1]):
                    best = (mode, probs)
            total += 1
            if best is None:
                continue
            mode, probs = best
            if not probs:
                exact += 1
                print('EXACT', mode, os.path.join(dp, f))
            else:
                print('DIFF ', mode, os.path.join(dp, f))
                for k, v in probs:
                    print('        %-10s %s' % (k, v))
    print('%d of %d maps exact' % (exact, total))


if __name__ == '__main__':
    main()
