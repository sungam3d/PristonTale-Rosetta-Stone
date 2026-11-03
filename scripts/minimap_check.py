"""Overlay a stage map's floor (top view) on its minimap image, the way the game maps one onto the other:
u = (x - minX) / width, v = (maxZ - z) / height  (StageMapRect from the .smd, north up).

  python scripts/minimap_check.py <map.smd> <minimap.png> <out.png>
"""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim.smdfile import Stage   # noqa: E402

smd, mm, out = sys.argv[1:4]
st = Stage(smd)
xs = [p[0] for p in st.positions]
zs = [p[1] for p in st.positions]
x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
img = Image.open(mm).convert('RGB')
W, H = img.size
top = Image.new('RGB', (W, H), (0, 0, 0))
d = ImageDraw.Draw(top)
for a, b, c, m in st.faces:
    mat = st.materials[m] if m < len(st.materials) else None
    if mat is None or mat.is_collision:
        continue
    pts = [((st.positions[v][0] - x0) / (x1 - x0) * W, (z1 - st.positions[v][1]) / (z1 - z0) * H) for v in (a, b, c)]
    d.polygon(pts, fill=(0, 255, 0))
over = Image.blend(img, top, 0.35)
both = Image.new('RGB', (W * 3, H))
both.paste(img, (0, 0))
both.paste(top, (W, 0))
both.paste(over, (2 * W, 0))
both.save(out)
print('StageMapRect X %.1f..%.1f  Z %.1f..%.1f  (%.0f x %.0f)' % (x0, x1, z0, z1, x1 - x0, z1 - z0))
