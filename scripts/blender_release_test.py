"""Release check: install the add-on zip like a user would, enable it, import a monster, export it again.

  set BLENDER_USER_RESOURCES=<empty temp folder>   (keeps the real Blender setup untouched)
  blender --background --factory-startup --python blender_release_test.py -- <zip> <ase> <out.ase>
"""
import sys

import bpy

zp, ase, out = sys.argv[sys.argv.index('--') + 1:][:3]
bpy.ops.extensions.package_install_files(filepath=zp, repo='user_default', enable_on_install=True)
print('ENABLED', 'bl_ext.user_default.pt_ase_smd_importer' in bpy.context.preferences.addons.keys())
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
r = bpy.ops.import_scene.pt_ase(filepath=ase)
arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
print('IMPORT', r, 'bones', arm and len(arm.data.bones), 'motions', arm and len(arm.pt_motions))
bpy.context.scene.frame_set(50)
for o in bpy.context.view_layer.objects:
    o.select_set(o.type == 'MESH')
r = bpy.ops.export_scene.pt_ase(filepath=out, copy_textures=False)
print('EXPORT', r)
