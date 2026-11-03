"""3ds Max test suite: max_suite.ms in 3dsmaxbatch over a job list, then the checks in Python.

  python run_max_suite.py <jobs.json> <out dir> [workers] [--sample N] [--groups a,b] [--batch N]

jobs.json as for the Blender suite (bltest/make_jobs.py).  Each worker runs batches of files in
one 3ds Max session (a crash only loses the rest of that batch); a re-run continues where it
stopped.  One JSON line per file in out/results.jsonl; summary: python ../bltest/report.py.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'bltest'))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import asecheck                                                          # noqa: E402
from maxcheck import check, prop_ticks, read_dump                        # noqa: E402

MAX = r'C:\Program Files\Autodesk\3ds Max 2020\3dsmaxbatch.exe'
args = sys.argv[1:]


def opt(name, default):
    if name in args:
        i = args.index(name)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


sample = int(opt('--sample', 0))
groups = opt('--groups', '')
batch = int(opt('--batch', 25))
jobs_path, out = args[:2]
workers = int(args[2]) if len(args) > 2 else 3
jobs = json.load(open(jobs_path, encoding='utf-8'))
if groups:
    jobs = [j for j in jobs if j['group'] in groups.split(',')]
if sample:
    random.seed(1)
    by = {}
    for j in jobs:
        by.setdefault(j['group'], []).append(j)
    jobs = [j for g in sorted(by) for j in (by[g] if len(by[g]) <= sample else random.sample(by[g], sample))]
os.makedirs(os.path.join(out, 'tmp'), exist_ok=True)
res_path = os.path.join(out, 'results.jsonl')
done = set()
if os.path.exists(res_path):
    for line in open(res_path, encoding='utf-8'):
        try:
            done.add(json.loads(line)['ase'])
        except Exception:
            pass
todo = [j for j in jobs if j['ase'] not in done]
print('%d jobs, %d to do' % (len(jobs), len(todo)))
lock = threading.Lock()
outf = open(res_path, 'a', encoding='utf-8')


def run_batch(k, part):
    tmpd = os.path.join(out, 'tmp')
    lst = os.path.join(tempfile.gettempdir(), 'pt_max_suite_%d.txt' % k)
    srcs = {}
    with open(lst, 'w', encoding='utf-8') as f:
        for i, j in enumerate(part):
            exp = os.path.abspath(os.path.join(tmpd, 'exp_%d_%d.ase' % (k, i)))
            dump = os.path.abspath(os.path.join(tmpd, 'dump_%d_%d.txt' % (k, i)))
            for p in (exp, dump):
                if os.path.exists(p):
                    os.remove(p)
            try:
                src = asecheck.load(j['ase'])
                ticks = prop_ticks(src)
            except Exception as e:
                src, ticks = None, []
                srcs[i] = ('load: %s' % e, exp, dump)
                continue
            srcs[i] = (src, exp, dump)
            f.write('%s|%s|%s|#(%s)\n' % (os.path.abspath(j['ase']), exp, dump, ','.join('%g' % t for t in ticks)))
    env = dict(os.environ, PT_MAX_SUITE=str(k))
    log = os.path.join(tmpd, 'log_%d.txt' % k)
    t0 = time.time()
    try:
        subprocess.run([MAX, os.path.join(HERE, 'max_suite.ms'), '-listenerlog', log], env=env,
                       capture_output=True, timeout=300 + 120 * len(part))
    except subprocess.TimeoutExpired:
        pass
    secs = time.time() - t0
    for i, j in enumerate(part):
        src, exp, dump = srcs[i]
        res = dict(ase=j['ase'], group=j['group'])
        if isinstance(src, str):
            res['error'] = src
        else:
            d = read_dump(dump)
            if 'IMPORT' not in d:
                res['error'] = 'import: ' + d.get('ERROR', 'no output (Max crashed?)')
            else:
                ms, cnt = d['IMPORT'].split()
                res['t_import'] = int(ms) / 1000.0
                res['nodes'] = int(cnt)
                if 'ERROR' in d:
                    res['error'] = 'max: ' + d['ERROR'][:300]
                try:
                    check(j, src, d, exp, res)
                except Exception as e:
                    import traceback
                    res['error'] = 'check: %s' % e
                    res['trace'] = traceback.format_exc()[-1200:]
        res['batch_s'] = round(secs, 1)
        with lock:
            outf.write(json.dumps(res) + '\n')
            outf.flush()
        for p in (exp, dump):
            if os.path.exists(p) and not os.environ.get('PT_SUITE_KEEP'):
                os.remove(p)


queue = [todo[i:i + batch] for i in range(0, len(todo), batch)]
t_start = time.time()


def worker(k):
    while True:
        with lock:
            if not queue:
                return
            part = queue.pop(0)
        run_batch(k, part)
        with lock:
            n = sum(1 for _ in open(res_path, encoding='utf-8'))
        print('worker %d: %d results, %.0f s' % (k, n, time.time() - t_start))
        sys.stdout.flush()


ths = [threading.Thread(target=worker, args=(k,)) for k in range(workers)]
for t in ths:
    t.start()
for t in ths:
    t.join()
print('finished in %.0f s' % (time.time() - t_start))
