import sys, numpy as np
sys.path.insert(0, r'X:\Projects\SMD-ANIM\scripts')
from probe_keys import bones, qmat
paths = [r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\monster\Tees\Tees.smb']
res = {}
def add(k, e): res.setdefault(k, []).append(e)
for path in paths:
    for name, rot, prev in bones(path):
        Q = [qmat(*r[1:]) for r in rot]
        accs = {'L': np.eye(3), 'R': np.eye(3), 'LT': np.eye(3), 'RT': np.eye(3)}
        hist = {k: [] for k in accs}
        for q in Q:
            accs['L'] = accs['L'] @ q; accs['R'] = q @ accs['R']
            accs['LT'] = accs['LT'] @ q.T; accs['RT'] = q.T @ accs['RT']
            for k in accs: hist[k].append(accs[k].copy())
        for i, P in enumerate(prev):
            for k in hist:
                for shift in (0, 1):
                    j = i - shift
                    A = hist[k][j] if j >= 0 else np.eye(3)
                    add('%s shift%d' % (k, shift), min(np.abs(P - A).max(), np.abs(P - A.T).max()))
for k, v in sorted(res.items()):
    v = np.array(v); print('%-10s max %.4f  share<1e-3 %.3f' % (k, v.max(), (v < 1e-3).mean()))
