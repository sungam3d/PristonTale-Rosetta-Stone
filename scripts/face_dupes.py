"""Faces that share their three vertices with another face (back faces / duplicates) and
degenerate faces, per textured object.   python face_dupes.py file.ase ..."""
import os
import sys

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all   # noqa: E402

for p in sys.argv[1:]:
    for g in find_all(parse_ase(p), '*GEOMOBJECT'):
        if find(g, '*MATERIAL_REF') is None:
            continue
        fl = find(find(g, '*MESH'), '*MESH_FACE_LIST')[2] or []
        seen, rev, same, degen = {}, 0, 0, 0
        for c in fl:
            s = c[1]
            a = int(s.split('A:')[1].split()[0])
            b = int(s.split('B:')[1].split()[0])
            cc = int(s.split('C:')[1].split()[0])
            if len({a, b, cc}) < 3:
                degen += 1
                continue
            key = frozenset((a, b, cc))
            if key in seen:
                if seen[key] in [(a, b, cc), (b, cc, a), (cc, a, b)]:
                    same += 1
                else:
                    rev += 1
            else:
                seen[key] = (a, b, cc)
        print('%-22s faces %6d  back faces (reversed duplicates) %4d  same-winding duplicates %4d  degenerate %4d'
              % (os.path.basename(p), len(fl), rev, same, degen))
