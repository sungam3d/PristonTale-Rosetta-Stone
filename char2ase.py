"""Convert Priston Tale character / monster SMD (+SMB skeleton) files to ASE.

    python char2ase.py <file.smd|file.smb|folder> ... -o OUTDIR [--animation auto|embed|shared|none] [--lod high|all] [--one-mesh]

Textures are decoded and copied next to the .ase files (the game looks for
them there).  Player bodies/heads share their class animation file
(m1_motions.ase ...), monsters get their animation embedded.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smdanim.convert import Options, convert_file          # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--animation', default='auto', choices=('auto', 'embed', 'shared', 'none'))
    ap.add_argument('--lod', default='high', choices=('high', 'all'))
    ap.add_argument('--one-mesh', action='store_true', help='maps: one mesh instead of the original objects')
    a = ap.parse_args()
    files = []
    for p in a.inputs:
        if os.path.isdir(p):
            for d, _sub, names in os.walk(p):
                files += [os.path.join(d, n) for n in sorted(names) if n.lower().endswith('.smd')]
        else:
            files.append(p)
    log = {}
    fails = 0
    for i, f in enumerate(files):
        t = time.time()
        name = os.path.splitext(os.path.basename(f))[0]
        out = os.path.join(a.out, name + '.ase')
        opt = Options(texture_out=a.out, texture_dir_override=a.out, texture_log=log,
                      animation=a.animation, lod=a.lod, split_objects=not a.one_mesh)
        try:
            sc = convert_file(f, out, opt)
        except Exception as e:                                   # keep going on bad files
            fails += 1
            print('[%d/%d] FAILED %s: %s' % (i + 1, len(files), f, e))
            continue
        rig = getattr(sc, 'rig', None)
        info = ''
        if rig is not None and rig.smb:
            info = 'skeleton %s (%s), animation %s, %d motions' % (
                os.path.basename(rig.smb), rig.how, sc.anim_mode, len(sc.motions))
        if getattr(sc, 'missing_bones', None):
            info += ', MISSING BONES %s' % sc.missing_bones[:4]
        print('[%d/%d] %s -> %s  %s  (%.1fs)' % (i + 1, len(files), os.path.basename(f), os.path.basename(out),
                                                 info, time.time() - t))
    if log:
        print('missing textures:', ', '.join(sorted(log)))
    print('done, %d failed' % fails)


if __name__ == '__main__':
    main()
