"""Score rules that rebuild a map's original objects from the stage .smd alone.

For every original 2012 ASE whose .smd has the same faces in the same order, the
true object boundaries are known.  Each rule starts from the possible cuts (see
probe_stage_split.py) and merges a piece into the current group when the rule says so.
  lost  = real boundaries that were merged away (two original objects in one piece)
  extra = cuts kept inside one original object (an object split in parts)

  python scripts/probe_stage_rules.py <orig Field dir> <smd Field dir>
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim.smdfile import Stage   # noqa: E402

orig_dir, smd_dir = sys.argv[1:3]


def object_face_counts(path):
    counts = []
    depth = 0
    with open(path, 'r', encoding='latin-1') as fh:
        for line in fh:
            s = line.strip()
            if s.startswith('*GEOMOBJECT'):
                counts.append(0)
            elif s.startswith('*MESH_NUMFACES') and counts:
                counts[-1] = int(s.split()[1])
    return counts


def pieces_of(st):
    n = len(st.faces)
    suf = [1 << 30] * (n + 1)
    for i in range(n - 1, -1, -1):
        suf[i] = min(suf[i + 1], *st.faces[i][:3])
    bounds = [0]
    hi = -1
    for i in range(1, n):
        hi = max(hi, *st.faces[i - 1][:3])
        if hi < suf[i]:
            bounds.append(i)
    bounds.append(n)
    out = []
    for k in range(len(bounds) - 1):
        fs = st.faces[bounds[k]:bounds[k + 1]]
        vs = set(v for f in fs for v in f[:3])
        P = [st.positions[v] for v in vs]
        bb = [min(p[j] for p in P) for j in range(3)] + [max(p[j] for p in P) for j in range(3)]
        out.append(dict(start=bounds[k], nf=len(fs), mats=set(f[3] for f in fs), bb=bb,
                        pos=set((round(p[0], 1), round(p[1], 1), round(p[2], 1)) for p in P)))
    return out


def bb_touch(a, b, tol):
    return all(a[j] <= b[j + 3] + tol and b[j] <= a[j + 3] + tol for j in range(3))


RULES = {
    'all cuts': lambda g, p: False,
    'same mats': lambda g, p: bool(g['mats'] & p['mats']),
    'mats+bbox': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 1.0),
    'bbox': lambda g, p: bb_touch(g['bb'], p['bb'], 1.0),
    'touch': lambda g, p: bool(g['pos'] & p['pos']),
    'mats+touch': lambda g, p: bool(g['mats'] & p['mats']) and bool(g['pos'] & p['pos']),
    'mats+near50': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 50.0),
    'mats+near200': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 200.0),
    'subset+near50': lambda g, p: p['mats'] <= g['mats'] and bb_touch(g['bb'], p['bb'], 50.0),
    'mats+inside': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], -0.0) and all(
        g['bb'][j] - 1 <= p['bb'][j] and p['bb'][j + 3] <= g['bb'][j + 3] + 1 for j in range(3)),
    'mats+bbox|touch': lambda g, p: (bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 1.0))
                                    or bool(g['pos'] & p['pos']),
    'mats+near500': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 500.0),
    'mats+near1000': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 1000.0),
    'mats+near3000': lambda g, p: bool(g['mats'] & p['mats']) and bb_touch(g['bb'], p['bb'], 3000.0),
    # against the previous piece only (a terrain group's box covers the whole map)
    'last: mats+bbox': lambda g, p: bool(g['last']['mats'] & p['mats']) and bb_touch(g['last']['bb'], p['bb'], 1.0),
    'last: mats+near50': lambda g, p: bool(g['last']['mats'] & p['mats']) and bb_touch(g['last']['bb'], p['bb'], 50.0),
    'last: mats': lambda g, p: bool(g['last']['mats'] & p['mats']),
    'tiny<=2 + mats': lambda g, p: p['nf'] <= 2 and bool(g['mats'] & p['mats']),
    'tiny<=4 + mats': lambda g, p: p['nf'] <= 4 and bool(g['mats'] & p['mats']),
    'tiny<=2|touch': lambda g, p: (p['nf'] <= 2 and bool(g['mats'] & p['mats'])) or bool(g['pos'] & p['pos']),
    'tiny<=4|last mats+bbox': lambda g, p: (p['nf'] <= 4 and bool(g['mats'] & p['mats'])) or (
        bool(g['last']['mats'] & p['mats']) and bb_touch(g['last']['bb'], p['bb'], 1.0)),
}

tot = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
n_obj = n_files = 0
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
        except Exception:
            continue
        counts = object_face_counts(os.path.join(dp, f))
        if sum(counts) != len(st.faces) or len(counts) < 2:
            continue
        true = set()
        acc = 0
        for c in counts[:-1]:
            acc += c
            true.add(acc)
        P = pieces_of(st)
        cuts = set(p['start'] for p in P[1:])
        if not true <= cuts:
            print('skip (faces reordered):', rel)
            continue
        n_files += 1
        n_obj += len(counts)
        for name, rule in RULES.items():
            g = None
            kept = set()
            for p in P:
                if g is not None and rule(g, p):
                    g['mats'] |= p['mats']
                    g['bb'] = [min(g['bb'][j], p['bb'][j]) for j in range(3)] + \
                              [max(g['bb'][j + 3], p['bb'][j + 3]) for j in range(3)]
                    g['pos'] |= p['pos']
                    g['last'] = p
                else:
                    if g is not None:
                        kept.add(p['start'])
                    g = dict(mats=set(p['mats']), bb=list(p['bb']), pos=set(p['pos']), last=p)
            # face-weighted: purity = faces of a piece from its main original object,
            # completeness = faces of an original object inside its main piece
            obj_of = []
            for oi, c in enumerate(counts):
                obj_of += [oi] * c
            bounds = sorted(kept | {0}) + [len(st.faces)]
            pur = 0
            comp = defaultdict(lambda: defaultdict(int))
            for k in range(len(bounds) - 1):
                cnt = defaultdict(int)
                for fi in range(bounds[k], bounds[k + 1]):
                    cnt[obj_of[fi]] += 1
                    comp[obj_of[fi]][k] += 1
                pur += max(cnt.values())
            t = tot[name]
            t[3] += pur
            t[4] += sum(max(d.values()) for d in comp.values())
            t[5] += len(st.faces)
            t[0] += len(kept) + 1
            t[1] += len(true - kept)
            t[2] += len(kept - true)
print('files', n_files, 'original objects', n_obj)
for name, (groups, lost, extra, pur, comp, nf) in tot.items():
    print('%-24s pieces %6d   lost %5d   extra %6d   purity %5.1f%%   complete %5.1f%%'
          % (name, groups, lost, extra, 100.0 * pur / nf, 100.0 * comp / nf))
