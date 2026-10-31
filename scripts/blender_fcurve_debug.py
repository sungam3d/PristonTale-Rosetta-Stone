"""Print the imported f-curve keys of one bone around a frame (debug)."""
import sys
import bpy
sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
ase, bone, frame = args[0], args[1], float(args[2])
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
r = ase_import.import_ase(bpy.context, ase, ase_import.ImportOptions(scale=1.0))
arm = r['armature']
act = arm.animation_data.action
from bpy_extras.anim_utils import action_get_channelbag_for_slot
bag = action_get_channelbag_for_slot(act, arm.animation_data.action_slot)
for fc in bag.fcurves:
    if fc.data_path == 'pose.bones["%s"].rotation_quaternion' % bone:
        ks = [(k.co[0], round(k.co[1], 4), k.interpolation) for k in fc.keyframe_points if abs(k.co[0] - frame) < 12]
        print(fc.array_index, ks, 'eval', round(fc.evaluate(frame), 4))
