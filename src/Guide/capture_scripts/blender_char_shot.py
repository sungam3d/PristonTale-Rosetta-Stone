"""Guide screenshot: a character in Blender with the PT Motions panel open.

  blender --factory-startup empty.blend --python blender_char_shot.py
  (opening any .blend skips the splash screen)
"""
import os
import sys

import bpy

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402

ASE = r'X:\Projects\SMD-ANIM\work\PT_ASE_Output\MmbA34.ase'
OUT = r'X:\Projects\SMD-ANIM\work\shots\blender_character.png'
st = {'phase': 0}


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
    return win, area, next(r for r in area.regions if r.type == 'WINDOW')


def tick():
    win, area, region = view3d()
    if st['phase'] == 0:
        io_scene_pt_ase.register()
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o)
        with bpy.context.temp_override(window=win, area=area, region=region):
            r = ase_import.import_ase(bpy.context, ASE, ase_import.ImportOptions())
            arm = r['armature']
            ase_import.frame_objects(bpy.context, [o for o in r['visible'] if o.type == 'MESH'])
            for o in bpy.context.view_layer.objects:
                o.select_set(False)
            arm.select_set(True)
            bpy.context.view_layer.objects.active = arm
            idx = next(i for i, m in enumerate(arm.pt_motions) if m.name == 'walk_01')
            arm.pt_motion_index = idx                   # same as clicking it in the list
            bpy.context.scene.frame_set(arm.pt_motions[idx].start + 10)
        space = area.spaces.active
        from mathutils import Euler
        import math
        space.region_3d.view_rotation = Euler((math.radians(78), 0, math.radians(28))).to_quaternion()
        with bpy.context.temp_override(window=win, area=area, region=region):
            for o in bpy.context.view_layer.objects:
                o.select_set(o.type == 'MESH')
            bpy.ops.view3d.view_selected()
            for o in bpy.context.view_layer.objects:
                o.select_set(o is arm)
            bpy.context.view_layer.objects.active = arm
        space.show_region_ui = True
        space.overlay.show_overlays = True
        st['phase'] = 1
        return 1.0
    if st['phase'] == 1:
        # switch the sidebar to the PT tab
        for reg in area.regions:
            if reg.type == 'UI':
                try:
                    reg.active_panel_category = 'PT'
                except Exception as e:
                    print('category', e)
        area.tag_redraw()
        st['phase'] = 2
        return 1.0
    if st['phase'] == 2:
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.screen.screenshot(filepath=OUT)
        print('SHOT', OUT)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=2.0)
