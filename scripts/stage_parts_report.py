"""Objects per map with the converter's map split (smdanim.convert._stage_parts).

  python scripts/stage_parts_report.py <Field dir> [original Field dir]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.smdfile import Stage, SMDError      # noqa: E402
from smdanim.convert import _stage_parts         # noqa: E402

rows = []
for dp, dn, fn in os.walk(sys.argv[1]):
    for f in fn:
        if not f.lower().endswith('.smd'):
            continue
        try:
            st = Stage(os.path.join(dp, f))
        except SMDError:
            continue
        rel = os.path.relpath(os.path.join(dp, f), sys.argv[1])
        orig = ''
        if len(sys.argv) > 2:
            a = os.path.join(sys.argv[2], os.path.splitext(rel)[0] + '.ASE')
            if os.path.exists(a):
                with open(a, 'r', encoding='latin-1') as fh:
                    orig = sum(1 for line in fh if line.lstrip().startswith('*GEOMOBJECT'))
        rows.append((len(_stage_parts(st)), orig, len(st.faces), rel))
rows.sort(key=lambda r: r[0])
for r in rows:
    print('%6d objects (original %5s)  %7d faces  %s' % r)
print('maps', len(rows), 'median', rows[len(rows) // 2][0], 'max', rows[-1][0])
