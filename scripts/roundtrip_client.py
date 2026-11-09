"""Whole client: C# decode (no models) -> C# encode, compared with the game's own files.
Also: C# texture decode == Python texture decode for every client texture.

    python roundtrip_client.py [client folder]      (writes work\\rt; ~3 minutes)
"""
import collections
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.textures import decode_texture_bytes   # noqa: E402

EXE = r'X:\Projects\SMD-ANIM\src\smd2ase\bin\Release\net48\smd2ase.exe'
G = sys.argv[1] if len(sys.argv) > 1 else r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)'
W = r'X:\Projects\SMD-ANIM\work\rt'
DEC, ENC = os.path.join(W, 'dec'), os.path.join(W, 'enc')
shutil.rmtree(W, ignore_errors=True)
t0 = time.time()
r = subprocess.run([EXE, '--client', G, '-o', DEC, '--no-models'], capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout.strip().splitlines()[-3:], '%.0fs' % (time.time() - t0))

# textures: C# decode == Python decode
bad = 0; n = 0
for d, _s, fs in os.walk(G):
    for f in fs:
        if not f.lower().endswith(('.bmp', '.tga')):
            continue
        src = os.path.join(d, f)
        rel = os.path.relpath(src, G)
        cs = os.path.join(DEC, rel)
        if not os.path.isfile(cs):
            continue
        n += 1
        if decode_texture_bytes(open(src, 'rb').read())[0] != open(cs, 'rb').read():
            bad += 1
            if bad <= 5:
                print('texture decode differs C#/Python:', rel)
print('textures decoded: %d, C#/Python differ: %d' % (n, bad))

t0 = time.time()
r = subprocess.run([EXE, '--to-game', DEC, '-o', ENC], capture_output=True, text=True, encoding='utf-8', errors='replace')
lines = r.stdout.strip().splitlines()
print(lines[-1], '%.0fs' % (time.time() - t0))
notes = collections.Counter(l.split(': ', 1)[1].split(' (')[0][:70] if ': ' in l else l for l in lines if l.startswith('note '))
for k, v in notes.most_common(25):
    print('  %5d  %s' % (v, k))

same = collections.Counter(); diff = collections.Counter(); ex = collections.defaultdict(list)
for d, _s, fs in os.walk(ENC):
    for f in fs:
        p = os.path.join(d, f)
        rel = os.path.relpath(p, ENC)
        g = os.path.join(G, rel)
        ext = os.path.splitext(f)[1].lower()
        if not os.path.isfile(g):
            diff[ext + ' (not in the client)'] += 1
            ex[ext + ' (not in the client)'].append(rel)
            continue
        if open(g, 'rb').read() == open(p, 'rb').read():
            same[ext] += 1
        else:
            diff[ext] += 1
            ex[ext].append(rel)
print('identical to the game\'s own file:', dict(same))
print('different:', dict(diff))
for k, v in ex.items():
    print(' ', k, v[:6])
