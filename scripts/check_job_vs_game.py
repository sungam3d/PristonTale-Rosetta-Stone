"""check_ase_vs_game.py for a test job by file name:  python check_job_vs_game.py <name.ase> [frame ...]"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1]
for j in json.load(open(os.path.join(HERE, '..', 'work', 'bltest', 'all_jobs.json'), encoding='utf-8')):
    if os.path.basename(j['ase'].replace('\\', '/')).lower() == name.lower() and j.get('smb'):
        print('==', name, os.path.basename(j['smb'].replace('\\', '/')))
        out = subprocess.run([sys.executable, os.path.join(HERE, 'check_ase_vs_game.py'), j['ase'], j['smd'], j['smb']]
                             + sys.argv[2:], capture_output=True, text=True).stdout
        print('\n'.join(out.splitlines()[:14]))
        break
