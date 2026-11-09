"""Client models: .smd (+ .smb) -> our .ase (decode) -> .smd (+ .smb) (encode) -> compared with the
client's files object by object (check_ase2model.compare).

    python roundtrip_models.py <smd2ase.exe> <work folder> <model.smd> ...
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_ase2model import model, compare, texdir   # noqa: E402


def main():
    exe, work = sys.argv[1:3]
    files = sys.argv[3:]
    os.makedirs(work, exist_ok=True)
    same = 0
    for p in files:
        g = model(p)
        if g is None:
            continue
        base = os.path.splitext(p)[0]
        smb = base + '.smb' if os.path.exists(base + '.smb') else None
        dec = os.path.join(work, 'dec')
        subprocess.run([exe, p, '-o', dec], capture_output=True)
        name = os.path.basename(base).lower() + '.ase'
        ase = next((os.path.join(dp, f) for dp, dn, fn in os.walk(dec) for f in fn if f.lower() == name), None)
        if not ase:
            print('NO ASE', p)
            continue
        o_smd, o_smb = os.path.join(work, 'rt.smd'), os.path.join(work, 'rt.smb')
        for x in (o_smd, o_smb):
            if os.path.exists(x):
                os.remove(x)
        r = subprocess.run([exe, '--ase2model', ase, o_smd, o_smb if smb else '-', texdir(g)], capture_output=True, text=True)
        os.remove(ase)
        if not os.path.exists(o_smd):
            print('FAIL', p, r.stdout[-300:], r.stderr[-500:])
            continue
        probs = ['smd ' + x for x in compare(g, model(o_smd))]
        if smb:
            probs += ['smb ' + x for x in compare(model(smb), model(o_smb), True)] if os.path.exists(o_smb) else ['smb not written']
        same += not probs
        print('%-5s %s  %s' % ('OK' if not probs else 'DIFF', p, r.stdout.strip()[:120]))
        for x in probs:
            print('        ' + x[:400])
    print('%d of %d come back the same' % (same, len(files)))


if __name__ == '__main__':
    main()
