"""Debug: imported local rotation of one bone vs what the exporter computes back."""
import sys
import json
import bpy
from mathutils import Matrix
sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import, ase_anim, ase_export_rig as rig   # noqa: E402
from io_scene_pt_ase.aseparse import parse_ase            # noqa: E402

SRC = r'X:\Projects\SMD-ANIM\work\rt_in\Tees.ase'
BONE = sys.argv[sys.argv.index('--') + 1]
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
r = ase_import.import_ase(bpy.context, SRC, ase_import.ImportOptions(scale=1.0))
arm = r['armature']
tracks = ase_anim.tracks_from(parse_ase(SRC))
tr = tracks[BONE]
bind = json.loads(arm['pt_bind'])
b = arm.data.bones[BONE]
W = {k: Matrix(v) for k, v in bind.items()}
rest_local = W[b.parent.name].inverted() @ W[BONE]
r_loc, r_rot, r_scl = rest_local.decompose()
L0 = tr.local(0, r_loc, r_rot, r_scl)
print('orig local q', L0.to_quaternion(), 'rest_local det', rest_local.to_3x3().determinant())
out = rig.bone_tracks(arm, Matrix.Identity(4), arm.animation_data.action)
pos, rot, scl = out[BONE]
print('first exported rot key', rot[0])
import math
ax, ay, az, ang = rot[0][1:]
from mathutils import Quaternion, Vector
q = Quaternion(Vector((ax, ay, az)), -ang)
print('exported abs q (conj of delta)', q)
print('matrix_local vs bind diff', max(abs((b.matrix_local @ ase_anim.AXIS_INV)[i][j] - W[BONE][i][j]) for i in range(4) for j in range(4)))
print('parent ml vs bind diff', max(abs((b.parent.matrix_local @ ase_anim.AXIS_INV)[i][j] - W[b.parent.name][i][j]) for i in range(4) for j in range(4)))
pb = arm.pose.bones[BONE]
print('basis q at 0', pb.rotation_quaternion, 'scale', pb.scale)
