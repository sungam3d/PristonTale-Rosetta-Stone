"""Render an imported character at a few frames (visual check).

  blender --background --factory-startup --python blender_render_test.py -- <ase> <out_prefix> frame ...
"""
import math
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
ase, out = args[:2]
frames = [int(f) for f in args[2:]] or [0]
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
r = ase_import.import_ase(bpy.context, ase, ase_import.ImportOptions())
scn = bpy.context.scene
scn.render.engine = 'BLENDER_EEVEE'
scn.render.resolution_x, scn.render.resolution_y = 640, 800
scn.world = bpy.data.worlds.new('w')
scn.world.color = (0.35, 0.38, 0.45)
mesh = [o for o in r['visible'] if o.type == 'MESH']
for fr in frames:
    scn.frame_set(fr)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in mesh:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        pts += [o.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    c = (lo + hi) / 2
    size = max(hi - lo)
    cam = bpy.data.objects.get('cam') or bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    if cam.name not in scn.collection.objects:
        scn.collection.objects.link(cam)
    scn.camera = cam
    # 3ds Max front view: character faces -Y
    cam.location = c + Vector((size * 0.9, -size * 2.2, size * 0.25))
    cam.rotation_euler = (c - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = 50
    scn.render.filepath = '%s_%05d.png' % (out, fr)
    bpy.ops.render.render(write_still=True)
    print('rendered', scn.render.filepath)
