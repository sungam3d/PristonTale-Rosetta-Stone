"""Blender: import an ASE, export everything again (optionally after posing), print the result.

  blender --background --factory-startup --python blender_roundtrip.py -- <in.ase> <out.ase> [AUTO|ALWAYS|NEVER] [anim file]
"""
import sys

import bpy

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import, ase_export        # noqa: E402

a = sys.argv[sys.argv.index('--') + 1:]
src, dst = a[0], a[1]
mode = a[2] if len(a) > 2 else 'AUTO'
animf = a[3] if len(a) > 3 else ''
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
r = ase_import.import_ase(bpy.context, src, ase_import.ImportOptions(animation_file=animf))
bpy.context.scene.frame_set(37)                 # any frame: skinned meshes must still export in rest pose
res = ase_export.export_ase(bpy.context, dst, ase_export.ExportOptions(selection_only=False, animation=mode,
                                                                        copy_textures=False))
print('ROUNDTRIP', res)
