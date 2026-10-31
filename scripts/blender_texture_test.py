"""Blender: original artist ASE textures via the extra texture folder and via textures\ next to the .ase."""
import sys
import bpy
sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402
io_scene_pt_ase.register()
for label, ase, dirs in (('extra-folder', r'X:\Projects\SMD-ANIM\Martial Artist ASE\TfbF01.ASE',
                          [r'C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD']),
                         ('textures-subfolder', r'X:\Projects\SMD-ANIM\work\ma_out\TfbF01.ASE', [])):
    r = ase_import.import_ase(bpy.context, ase, ase_import.ImportOptions(texture_dirs=dirs, animation=False))
    print('TEX %s: missing %s, images %d' % (label, r['missing'], len([i for i in bpy.data.images if i.has_data or i.size[0]])))
