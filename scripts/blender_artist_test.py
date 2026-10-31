"""Blender: import an ORIGINAL artist character ASE animated with a class motions file
(or in T-pose) and compare the posed mesh with the game's own pose of the matching .smd.

  blender --background --factory-startup --python blender_artist_test.py -- <ase> <anim|-> <smd> <smb> frame ...
  (anim '-' = automatic lookup, 'tpose' = T-pose)
"""
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402
from game_pose import posed_vertices                       # noqa: E402

a = sys.argv[sys.argv.index('--') + 1:]
ase, anim, smd, smb = a[:4]
frames = [int(f) for f in a[4:]]
io_scene_pt_ase.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
opts = ase_import.ImportOptions(scale=1.0, animation=anim != 'tpose', animation_file='' if anim in ('-', 'tpose') else anim)
r = ase_import.import_ase(bpy.context, ase, opts)
arm = r['armature']
act = arm.animation_data.action if arm and arm.animation_data else None
print('RESULT bones %d, motions %d, action %s, missing anim %r, frames %d-%d'
      % (r['bones'], len(arm.pt_motions), act and act.name, r['missing_animation'],
         bpy.context.scene.frame_start, bpy.context.scene.frame_end))
skinned = [o for o in bpy.data.objects if o.type == 'MESH' and o.find_armature()]
for fr in frames:
    bpy.context.scene.frame_set(fr)
    dg = bpy.context.evaluated_depsgraph_get()
    got = []
    for o in skinned:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        got += [list(o.matrix_world @ v.co) for v in me.vertices]
        ev.to_mesh_clear()
    got = np.array(got)
    exp = posed_vertices(smd, smb, fr)
    exp = exp[~np.isnan(exp).any(1)]
    d = np.concatenate([np.sqrt(((exp[i:i + 400, None] - got[None]) ** 2).sum(-1)).min(1) for i in range(0, len(exp), 400)])
    print('FRAME %5d: game vertices %d vs artist mesh %d: nearest-neighbour median %.4f  99%% %.4f  max %.4f'
          % (fr, len(exp), len(got), np.median(d), np.percentile(d, 99), d.max()))
