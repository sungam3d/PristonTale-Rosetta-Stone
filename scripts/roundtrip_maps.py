"""Every map of a client: .smd -> our .ase (decode) -> .smd (encode, as ENCODE does it) -> compared with
the client's own .smd as geometry (check_ase2smd_geo: faces by corner positions, winding, material,
UVs, colours, normals, lights, lighting).

    python roundtrip_maps.py <client folder> <smd2ase.exe> <work folder>
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_ase2smd import stage, texdir                 # noqa: E402
from check_ase2smd_geo import faces                      # noqa: E402


def summary(a, b):
    fa, fb = faces(a), faces(b)
    only_a = sum(len(v) for k, v in fa.items() if k not in fb)
    only_b = sum(len(v) for k, v in fb.items() if k not in fa)
    mat = uv = col = nrm = 0
    for k, la in fa.items():
        lb = fb.get(k)
        if not lb:
            continue
        x, y = la[0], lb[0]
        if x[0] != y[0]:
            mat += 1
        if len(x[1]) != len(y[1]) or any(abs(p - q) > 1e-4 for u, v in zip(x[1], y[1]) for c, d in zip(u, v) for p, q in zip(c, d)):
            uv += 1
        if any(abs(p - q) > 1 for c, d in zip(x[2], y[2]) for p, q in zip(c, d)):
            col += 1
        if any(abs(p - q) > 1 for p, q in zip(x[3], y[3])):
            nrm += 1
    lights = sorted(a['lights']) == sorted(b['lights'])
    return dict(faces=len(a['faces']), missing=only_a, extra=only_b, material=mat, uv=uv, colour=col, normal=nrm,
                lights=lights, lighting=a['light'] == b['light'], rect=a['rect'] == b['rect'])


def main():
    client, exe, work = sys.argv[1:4]
    os.makedirs(work, exist_ok=True)
    smds = []
    for dp, dn, fn in os.walk(client):
        for f in sorted(fn):
            p = os.path.join(dp, f)
            if f.lower().endswith('.smd') and open(p, 'rb').read(9) == b'SMD Stage':
                smds.append(p)
    perfect = 0
    for p in smds:
        rel = os.path.relpath(p, client)
        dec = os.path.join(work, 'dec')
        subprocess.run([exe, p, '-o', dec], capture_output=True, text=True)
        ase = None
        for dp, dn, fn in os.walk(dec):
            for f in fn:
                if f.lower() == os.path.splitext(os.path.basename(p))[0].lower() + '.ase':
                    ase = os.path.join(dp, f)
        if not ase:
            print('NO ASE', rel)
            continue
        g = stage(p)
        out = os.path.join(work, 'rt.smd')
        c, br, lx, ly, lz = g['light']
        r = subprocess.run([exe, '--ase2smd', ase, out, texdir(g), str(c), str(br), str(lx), str(ly), str(lz)],
                           capture_output=True, text=True)
        os.remove(ase)
        if not os.path.exists(out):
            print('FAIL', rel, r.stdout[-300:], r.stderr[-300:])
            continue
        s = summary(g, stage(out))
        os.remove(out)
        bad = {k: v for k, v in s.items() if k != 'faces' and v not in (0, True)}
        if not bad:
            perfect += 1
        print('%-6s %-45s %6d faces %s' % ('OK' if not bad else 'DIFF', rel, s['faces'], bad if bad else ''))
    print('%d of %d maps come back the same' % (perfect, len(smds)))


if __name__ == '__main__':
    main()
