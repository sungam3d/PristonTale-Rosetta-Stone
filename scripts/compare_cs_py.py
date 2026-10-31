"""C# (smd2ase.exe, net48 and net8) vs the Python reference: outputs must be byte-identical.

    python compare_cs_py.py <file.smd|.smb> ...
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.convert import Options, convert_file, guess_game_root   # noqa: E402

EXES = [r'X:\Projects\SMD-ANIM\src\smd2ase\bin\Release\net48\smd2ase.exe',
        r'X:\Projects\SMD-ANIM\src\smd2ase\bin\Release\net8.0\smd2ase.exe']
files = sys.argv[1:]
tmp = tempfile.mkdtemp()
py = os.path.join(tmp, 'py')
for f in files:                                  # mimic Batch.Run: output path relative to the game root
    root = guess_game_root(f)
    rel = os.path.relpath(f, root) if os.path.abspath(f).lower().startswith(os.path.abspath(root).lower() + os.sep) \
        else os.path.basename(f)
    convert_file(f, os.path.join(py, os.path.splitext(rel)[0] + '.ase'),
                 Options(game_root=root, texture_out=os.path.join(py, 'textures')))
bad = 0
for exe in EXES:
    cs = os.path.join(tmp, os.path.basename(os.path.dirname(exe)))
    r = subprocess.run([exe] + files + ['-o', cs, '--textures'], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
    n = same = 0
    for d, _s, names in os.walk(py):
        for nm in names:
            a = os.path.join(d, nm)
            b = os.path.join(cs, os.path.relpath(a, py))
            n += 1
            if os.path.isfile(b) and open(a, 'rb').read().replace(os.path.abspath(py).encode('latin-1'), b'<OUT>') == \
                    open(b, 'rb').read().replace(os.path.abspath(cs).encode('latin-1'), b'<OUT>'):
                same += 1
            else:
                bad += 1
                print('  DIFFERENT %s: %s' % (os.path.basename(os.path.dirname(exe)), os.path.relpath(a, py)))
    extra = sum(len(x[2]) for x in os.walk(cs)) - n
    print('%-8s %d / %d files identical (%d extra files)' % (os.path.basename(os.path.dirname(exe)), same, n, extra))
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if bad else 0)
