"""Quick sanity report of converted ASE files: per mesh object vertex box, NaN/huge values,
faces pointing at missing vertices, physique bones that are not in the file.

  python scripts/ase_sanity.py <file.ase> ...
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402

for p in sys.argv[1:]:
    r = parse_ase(p)
    geoms = find_all(r, '*GEOMOBJECT')
    names = set(unquote(val(g, '*NODE_NAME', '')) for g in geoms)
    print('==', os.path.basename(p), len(geoms), 'objects')
    for g in geoms:
        if find(g, '*MATERIAL_REF') is None:
            continue
        m = find(g, '*MESH')
        V = [[float(x) for x in c[1].split()[1:4]] for c in find(m, '*MESH_VERTEX_LIST')[2] or []]
        F = []
        for c in find(m, '*MESH_FACE_LIST')[2] or []:
            t = c[1].replace(':', ' : ').split()
            F.append((int(t[t.index('A') + 2]), int(t[t.index('B') + 2]), int(t[t.index('C') + 2])))
        bad = sum(1 for v in V for x in v if not math.isfinite(x) or abs(x) > 1e5)
        badf = sum(1 for f in F if max(f) >= len(V))
        ph = find(g, '*PHYSIQUE')
        miss = set()
        nph = 0
        if ph:
            for c in ph[2] or []:
                if c[0].startswith('*PHYSIQUE_VERTEXASSIGNMENT'):
                    nph += 1
                    bn = unquote(c[1].split(None, 1)[1].strip())
                    if bn not in names:
                        miss.add(bn)
        bb = [min(v[j] for v in V) for j in range(3)] + [max(v[j] for v in V) for j in range(3)] if V else []
        print('  %-24s v%5d f%5d  box %s  bad values %d  bad faces %d  skinned %d  missing bones %s'
              % (unquote(val(g, '*NODE_NAME', ''))[:24], len(V), len(F), ' '.join('%.0f' % x for x in bb), bad, badf, nph, sorted(miss)[:5]))
