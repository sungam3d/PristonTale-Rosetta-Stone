"""Skinned-vertex check of some monsters in 3ds Max against the game math (max_anim_compare.py).

    python max_monster_check.py [name ...]      (ASE base names from work/bltest/all_jobs.json)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or ['monavelrisk-sword', 'spider', 'lizardfolk', 'Tees', 'Ahin']
jobs = json.load(open(os.path.join(HERE, '..', 'work', 'bltest', 'all_jobs.json'), encoding='utf-8'))
for nm in names:
    job = next((j for j in jobs if os.path.splitext(os.path.basename(j['ase'].replace('\\', '/')))[0].lower() == nm.lower()), None)
    if job is None:
        print(nm, ': no job')
        continue
    print('==', nm, os.path.basename(job['smb']))
    sys.stdout.flush()
    subprocess.run([sys.executable, os.path.join(HERE, 'max_anim_compare.py'), job['ase'], job['smd'], job['smb'],
                    '0', '21', '41', '77', '120', '155'])
