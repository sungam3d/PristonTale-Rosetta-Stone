"""Score the converter's map split (smdanim.convert._stage_parts) against the original 2012 ASE files
whose faces are in the same order as the .smd.

  purity   = share of faces that sit in an object with mostly the same original object
  complete = share of faces of an original object that land in its main converted object

  python scripts/score_stage_parts.py <orig Field dir> <smd Field dir>
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.smdfile import Stage, SMDError      # noqa: E402
from smdanim import convert                      # noqa: E402

orig_dir, smd_dir = sys.argv[1:3]
tot = [0] * 5
for dp, dn, fn in os.walk(orig_dir):
    for f in fn:
        if not f.lower().endswith('.ase'):
            continue
        rel = os.path.relpath(os.path.join(dp, f), orig_dir)
        smd = os.path.join(smd_dir, os.path.splitext(rel)[0] + '.smd')
        if not os.path.exists(smd):
            continue
        try:
            st = Stage(smd)
        except SMDError:
            continue
        counts = []
        with open(os.path.join(dp, f), 'r', encoding='latin-1') as fh:
            for line in fh:
                s = line.strip()
                if s.startswith('*GEOMOBJECT'):
                    counts.append(0)
                elif s.startswith('*MESH_NUMFACES') and counts:
                    counts[-1] = int(s.split()[1])
        if sum(counts) != len(st.faces) or len(counts) < 2:
            continue
        obj_of = []
        for oi, c in enumerate(counts):
            obj_of += [oi] * c
        parts = convert._stage_parts(st)
        pur = 0
        comp = defaultdict(lambda: defaultdict(int))
        for k, fidx in enumerate(parts):
            cnt = defaultdict(int)
            for fi in fidx:
                cnt[obj_of[fi]] += 1
                comp[obj_of[fi]][k] += 1
            pur += max(cnt.values())
        c = sum(max(d.values()) for d in comp.values())
        print('%-34s objects %5d (original %5d)  purity %5.1f%%  complete %5.1f%%'
              % (rel, len(parts), len(counts), 100.0 * pur / len(st.faces), 100.0 * c / len(st.faces)))
        tot[0] += len(parts)
        tot[1] += len(counts)
        tot[2] += pur
        tot[3] += c
        tot[4] += len(st.faces)
print('TOTAL objects %d (original %d)  purity %.1f%%  complete %.1f%%'
      % (tot[0], tot[1], 100.0 * tot[2] / tot[4], 100.0 * tot[3] / tot[4]))
