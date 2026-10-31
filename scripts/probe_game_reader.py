"""What does the game keep when it builds .smd/.smb from an artist ASE?

For original ASE files with the game-built .smd/.smb next to them: which ASE objects
(GEOMOBJECT / HELPEROBJECT, with or without mesh, material, physique, animation) end up
as objects in the .smb / .smd."""
import os
import sys

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402
from smdanim.smdfile import Model                                       # noqa: E402

PAIRS = [
    (r'X:\Projects\PT-World-Map\char\char\monster\MonGknight\MonGknight-motion.ASE', r'X:\Projects\PT-World-Map\char\char\monster\MonGknight\MonGknight-motion.smb'),
    (r'X:\Projects\PT-World-Map\char\char\monster\MonGknight\MonGknight-model.ASE', r'X:\Projects\PT-World-Map\char\char\monster\MonGknight\MonGknight-model.smd'),
    (r'X:\Projects\PT-World-Map\char\char\monster\MonGknight\MonGknight-model.ASE', r'X:\Projects\PT-World-Map\char\char\monster\MonGknight\MonGknight-model.smb'),
    (r'X:\Projects\PT-World-Map\char\char\tmABCD\M1-motion1.ASE', r'X:\Projects\PT-World-Map\char\char\tmABCD\M1-motion1.smb'),
    (r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD\MmbA34.ASE', r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD\MmbA34.smd'),
]
for ase, smx in PAIRS:
    if not (os.path.isfile(ase) and os.path.isfile(smx)):
        print('skip', ase)
        continue
    root = parse_ase(ase)
    kept = {o.name: o for o in Model(smx).objects}
    rows = {}
    for g in find_all(root, '*GEOMOBJECT') + find_all(root, '*HELPEROBJECT'):
        m = find(g, '*MESH')
        nv = int(val(m, '*MESH_NUMVERTEX', '0')) if m else -1
        kind = (g[0][1:5], 'mesh' if nv > 0 else 'nomesh', 'mat' if find(g, '*MATERIAL_REF') is not None else 'nomat',
                'phys' if find(g, '*PHYSIQUE') is not None else '-', 'anim' if find(g, '*TM_ANIMATION') is not None else '-')
        k = unquote(val(g, '*NODE_NAME')) in kept
        rows.setdefault(kind, [0, 0])[0 if k else 1] += 1
    print('%s -> %s  (%d objects in %s)' % (os.path.basename(ase), os.path.basename(smx), len(kept), os.path.splitext(smx)[1]))
    for kind, (k, d) in sorted(rows.items()):
        print('    %-42s kept %3d  dropped %3d' % (' '.join(kind), k, d))
    o = next(iter(kept.values()))
    print('    first kept object: %s verts %d faces %d' % (o.name, len(o.local_verts), len(o.faces)))
