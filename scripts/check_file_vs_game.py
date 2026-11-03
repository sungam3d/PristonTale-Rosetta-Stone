"""Convert one .smd with the current converter and compare its ASE with the game at some frames.

    python check_file_vs_game.py <file.smd> [frame ...]
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from smdanim.convert import convert_file   # noqa: E402

smd = sys.argv[1]
out = os.path.join(tempfile.gettempdir(), 'pt_check_' + os.path.splitext(os.path.basename(smd))[0] + '.ase')
sc = convert_file(smd, out)
smb = sc.skeleton.path if sc.skeleton else None
if not smb:
    sys.exit('no skeleton')
print('skeleton', os.path.basename(smb))
subprocess.run([sys.executable, os.path.join(HERE, 'check_ase_vs_game.py'), out, smd, smb] + sys.argv[2:])
