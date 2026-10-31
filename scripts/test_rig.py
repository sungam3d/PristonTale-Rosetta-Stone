"""Skeleton + motion-table lookup for a few characters and monsters."""
import os, sys
sys.path.insert(0, r'X:\Projects\SMD-ANIM')
from smdanim.motion import find_rig, smb_segments, read_ini, read_inx

C = r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char'
for smd in [r'tmABCD\MmbA34.smd', r'tmABCD\TfbD01.smd', r'tmABCD\Tfh-D03d.smd', r'monster\Tees\Tees.smd',
            r'monster\MonGknight\MonGknight-model.smd', r'monster\MonSRazorArcher\MonSRazorArcher.smd']:
    r = find_rig(os.path.join(C, smd))
    print('%-42s -> %-22s %s | LOD %s' % (smd, r.smb and os.path.basename(r.smb), r.how, r.lod_high))
    if r.info:
        seg = smb_segments(r.smb)
        ms = r.info.motions(seg)
        print('     pieces %d, motions %d, timeline %d frames' % (len(seg), len(ms), seg[-1][1] // 160 if seg else 0))
        print('     ', ms[:5], '...', ms[-2:])
G = r'X:\Projects\PT-World-Map\char\char\monster\MonGknight'
print('ini', read_ini(os.path.join(G, 'MonG2knight.ini')).raw_motions)
print('inx', read_inx(os.path.join(G, 'MonG2knight.inx')).raw_motions)
