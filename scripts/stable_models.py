"""Decode -> encode -> decode again must give the same .ase (within float noise): every model given.
Compares the two .ase files number by number (vertex positions, UVs, keys ...) and the structure.

    python stable_models.py <smd2ase.exe> <work folder> <model.smd> ...
"""
import os
import re
import shutil
import subprocess
import sys

NUM = re.compile(r'-?\d+\.\d+(?:[eE][-+]?\d+)?|-?\d+')
TOL = {'*MESH_VERTEX': 0.02, '*MESH_TVERT': 2e-4, '*CONTROL_POS_SAMPLE': 0.02, '*CONTROL_ROT_SAMPLE': 2e-3,
       '*CONTROL_SCALE_SAMPLE': 0.01, '*TM_ROW0': 0.01, '*TM_ROW1': 0.01, '*TM_ROW2': 0.01, '*TM_ROW3': 0.02,
       '*TM_POS': 0.02, '*TM_ROTAXIS': 2e-3, '*TM_ROTANGLE': 2e-3, '*TM_SCALE': 0.01, '*MESH_VERTCOL': 0.01}


def decode(exe, smd, out):
    if os.path.exists(out):
        shutil.rmtree(out)
    subprocess.run([exe, smd, '-o', out], capture_output=True)
    name = os.path.splitext(os.path.basename(smd))[0].lower() + '.ase'
    return next((os.path.join(dp, f) for dp, dn, fn in os.walk(out) for f in fn if f.lower() == name), None)


def lines(p):
    out = []
    for l in open(p, encoding='latin-1'):
        t = l.strip()
        if t.startswith(('*COMMENT', '*BITMAP ', '*PT_INDEX')):
            continue
        if re.match(r'\*MATERIAL_NAME "\d+ - Default"$', t) or re.match(r'\*MAP_NAME "Map #\d+"$', t):
            continue
        out.append(t)
    return out


def main():
    exe, work = sys.argv[1:3]
    os.makedirs(work, exist_ok=True)
    ok = 0
    for smd in sys.argv[3:]:
        a = decode(exe, smd, os.path.join(work, 'a'))
        if not a:
            print('NO ASE', smd); continue
        base = os.path.splitext(smd)[0]
        tex = 'field\\x\\'
        enc = os.path.join(work, 'enc')
        os.makedirs(enc, exist_ok=True)
        name = os.path.basename(base)
        b_smd, b_smb = os.path.join(enc, name + '.smd'), os.path.join(enc, name + '.smb')
        for x in (b_smd, b_smb):
            if os.path.exists(x):
                os.remove(x)
        has_smb = os.path.exists(base + '.smb')
        if has_smb:
            shutil.copy(base + '.smb', b_smb)            # (the decoder looks for the bones next to the .smd)
        for l in open(a, encoding='latin-1'):
            if '*PT_SKELETON' in l:                      # (armour: the class skeleton the decoder found)
                sk = l.split('"')[1]
                src = os.path.join(os.path.dirname(smd), sk)
                if os.path.exists(src) and sk.lower() != name.lower() + '.smb':
                    shutil.copy(src, os.path.join(enc, sk))
                break
        if os.path.exists(base + '.inx'):
            shutil.copy(base + '.inx', os.path.join(enc, name + '.inx'))      # (motion list)
        r = subprocess.run([exe, '--ase2model', a, b_smd, b_smb if has_smb else '-', tex], capture_output=True, text=True)
        if not os.path.exists(b_smd):
            print('FAIL', smd, r.stdout[-200:], r.stderr[-400:]); continue
        b = decode(exe, b_smd, os.path.join(work, 'b'))
        la, lb = lines(a), lines(b)
        worst = {}
        struct_diff = None
        if len(la) != len(lb):
            struct_diff = 'lines %d vs %d' % (len(la), len(lb))
        for x, y in zip(la, lb):
            kx, ky = x.split(' ')[0].split('\t')[0], y.split(' ')[0].split('\t')[0]
            if kx != ky:
                struct_diff = struct_diff or ('%s / %s' % (x[:80], y[:80]))
                break
            if x == y:
                continue
            nx, ny = NUM.findall(x), NUM.findall(y)
            if len(nx) != len(ny):
                struct_diff = struct_diff or ('%s / %s' % (x[:80], y[:80]))
                continue
            d = max((abs(float(p) - float(q)) for p, q in zip(nx, ny)), default=0)
            tol = TOL.get(kx, 0)
            if d > tol:
                if d > worst.get(kx, (0,))[0]:
                    worst[kx] = (d, x[:90], y[:90])
        good = not struct_diff and not worst
        ok += good
        print('%-5s %s %s' % ('OK' if good else 'DIFF', smd, struct_diff or ''))
        for k, v in worst.items():
            print('        %-24s max %.5g  %s  |  %s' % (k, v[0], v[1], v[2]))
    print('%d of %d stable' % (ok, len(sys.argv) - 3))


if __name__ == '__main__':
    main()
