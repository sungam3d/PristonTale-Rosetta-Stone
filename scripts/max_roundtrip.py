"""Run max_roundtrip.ms in 3dsmaxbatch.   python max_roundtrip.py <in.ase> <out.ase> [#auto|#always|#never] [anim file]"""
import os
import subprocess
import sys
import tempfile

a = sys.argv[1:]
src, dst = a[0], a[1]
mode = a[2] if len(a) > 2 else '#auto'
animf = a[3] if len(a) > 3 else ''
tmp = tempfile.gettempdir()
with open(os.path.join(tmp, 'pt_max_rt.txt'), 'w') as f:
    f.write('%s\n%s\n%s\n%s\n' % (os.path.abspath(src), os.path.abspath(dst), mode, animf))
log = os.path.join(tmp, 'pt_max_rt_log.txt')
if os.path.exists(log):
    os.remove(log)
subprocess.run([r'C:\Program Files\Autodesk\3ds Max 2020\3dsmaxbatch.exe', r'X:\Projects\SMD-ANIM\scripts\max_roundtrip.ms',
                '-listenerlog', log], capture_output=True, timeout=3600)
for line in open(log, encoding='utf-8', errors='replace'):
    if any(k in line for k in ('RT ', 'PT ASE', 'rror', '-- ')):
        print('  max:', line.rstrip()[:200])
