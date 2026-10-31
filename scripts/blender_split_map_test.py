"""Blender: import a split map (many objects), report object count and time, export it back.

  blender --background --factory-startup --python blender_split_map_test.py -- <in.ase> <out.ase>
"""
import sys
import time

import bpy

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402

io_scene_pt_ase.register()
src, out = sys.argv[sys.argv.index('--') + 1:][:2]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
t = time.time()
bpy.ops.import_scene.pt_ase(filepath=src)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
print('IMPORT %d objects, %d faces, %.1f s' % (len(meshes), sum(len(o.data.polygons) for o in meshes), time.time() - t))
from mathutils import Vector                              # noqa: E402
worst = 0.0
origin = 0
for o in meshes:
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mid = sum(pts, Vector()) / 8.0
    piv = o.matrix_world.translation
    worst = max(worst, (piv - mid).length / max(o.matrix_world.to_scale()))
    origin += piv.length < 0.01
print('PIVOTS furthest pivot from its box centre %.4f (file units), pivots at the origin %d' % (worst, origin))
for o in bpy.context.view_layer.objects:
    o.select_set(o.type == 'MESH')
t = time.time()
r = bpy.ops.export_scene.pt_ase(filepath=out, copy_textures=False)
print('EXPORT', r, '%.1f s' % (time.time() - t))
