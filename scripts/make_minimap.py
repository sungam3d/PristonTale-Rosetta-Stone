"""Render a field minimap from converted .ase files, aligned exactly the way the game draws it.

The game stretches the minimap image over the stage's StageMapRect (the bounds of every vertex of
the map, stored in the .smd header): u = (x - left) / width, v = (bottom - z) / height, north up.
This renders the map straight down with an orthographic camera fitted to that rectangle, in the
importer's GAME look (texture x baked lighting, no scene lights), on a transparent background.

  blender --background --factory-startup --python make_minimap.py -- <out.png> <left> <right> <top> <bottom> <map.ase> [extra.ase ...]

left/right = min/max X, top/bottom = min/max Z of StageMapRect (game units, 3ds Max X/Y).
"""
import sys

import bpy

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
out = args[0]
left, right, top, bottom = (float(a) for a in args[1:5])
files = args[5:]
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
sc = bpy.context.scene
for f in files:
    opts = ase_import.ImportOptions(scale=1.0)
    opts.import_lights = False
    ase_import.import_ase(bpy.context, f, opts)
for c in bpy.data.collections:                      # hidden collision walls stay out of the picture
    if c.name.endswith('_collision'):
        c.hide_render = True

w, h = right - left, bottom - top
H = 2048
W = int(round(H * w / h))
cam_data = bpy.data.cameras.new('minimap')
cam_data.type = 'ORTHO'
cam_data.ortho_scale = max(w, h)
cam_data.sensor_fit = 'AUTO'
cam_data.clip_start = 1.0
cam_data.clip_end = 200000.0
cam = bpy.data.objects.new('minimap', cam_data)
sc.collection.objects.link(cam)
zmax = max((o.matrix_world @ v.co).z for o in sc.objects if o.type == 'MESH' for v in o.data.vertices[:1]) + 50000
cam.location = ((left + right) / 2.0, (top + bottom) / 2.0, zmax)
cam.rotation_euler = (0.0, 0.0, 0.0)              # looking straight down, +Y (north, larger Z in game) up
sc.camera = cam

sc.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items} else 'BLENDER_EEVEE_NEXT'
sc.render.resolution_x = W
sc.render.resolution_y = H
sc.render.resolution_percentage = 100
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.view_settings.view_transform = 'Standard'
sc.view_settings.look = 'None'
if sc.world is None:
    sc.world = bpy.data.worlds.new('World')
sc.world.use_nodes = True
bg = sc.world.node_tree.nodes.get('Background')
if bg:
    bg.inputs['Color'].default_value = (0, 0, 0, 1)
    bg.inputs['Strength'].default_value = 0.0
try:
    sc.eevee.taa_render_samples = 16
except AttributeError:
    pass
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print('RENDERED', out, W, H)
