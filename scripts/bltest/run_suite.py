"""Run blender_suite.py over a job list in parallel Blender processes.

  python run_suite.py <all_jobs.json> <out dir> [workers]

Each worker gets every n-th job (so slow and fast kinds mix) and writes out/results_<k>.jsonl;
a re-run continues where a worker stopped.  Summary: python report.py out/results_*.jsonl
"""
import json
import os
import subprocess
import sys
import time

BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
HERE = os.path.dirname(os.path.abspath(__file__))
jobs_path, out = sys.argv[1:3]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
jobs = json.load(open(jobs_path, encoding='utf-8'))
os.makedirs(out, exist_ok=True)
procs = []
t0 = time.time()
for k in range(n):
    part = jobs[k::n]
    jp = os.path.join(out, 'jobs_%d.json' % k)
    json.dump(part, open(jp, 'w', encoding='utf-8'))
    log = open(os.path.join(out, 'log_%d.txt' % k), 'a', encoding='utf-8', errors='replace')
    procs.append(subprocess.Popen(
        [BLENDER, '--background', '--factory-startup', '--python', os.path.join(HERE, 'blender_suite.py'), '--',
         jp, os.path.join(out, 'results_%d.jsonl' % k), os.path.join(out, 'tmp_%d' % k)],
        stdout=log, stderr=subprocess.STDOUT))
for p in procs:
    p.wait()
done = sum(1 for k in range(n) for _ in open(os.path.join(out, 'results_%d.jsonl' % k), encoding='utf-8'))
print('finished %d of %d jobs in %.0f s' % (done, len(jobs), time.time() - t0))
