"""Guide screenshots in Blender (real window):
  PT_SHOT_MODE=browser : File > Import file browser with the PT import options
  PT_SHOT_MODE=weapon  : a weapon imported in the 3D view
  PT_SHOT_MODE=map     : a split map with one of its objects selected

  blender --factory-startup empty.blend --python blender_guide_shots.py
"""
import os
import sys

import bpy

sys.path.insert(0, r'X:\Projects\SMD-ANIM\tools\blender')
import io_scene_pt_ase                                     # noqa: E402
from io_scene_pt_ase import ase_import                    # noqa: E402

OUT = r'X:\Projects\SMD-ANIM\work\shots'
MODE = os.environ.get('PT_SHOT_MODE', 'browser')
st = {'phase': 0}


def find_win(kind):
    for w in bpy.context.window_manager.windows:
        if any(a.type == kind for a in w.screen.areas):
            return w
    return None


def shot(win, name):
    area = win.screen.areas[0]
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, name))
    print('SHOT', name)


def tick():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    if st['phase'] == 0:
        io_scene_pt_ase.register()
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o)
        if MODE == 'browser':
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.import_scene.pt_ase('INVOKE_DEFAULT',
                                            filepath=r'X:\Projects\SMD-ANIM\work\PT_ASE_Output\MmbA34.ase')
        elif MODE == 'export':
            with bpy.context.temp_override(window=win, area=area, region=region):
                ase_import.import_ase(bpy.context, r'X:\Projects\SMD-ANIM\work\PT_ASE_Output\Tees.ase',
                                      ase_import.ImportOptions())
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.export_scene.pt_ase('INVOKE_DEFAULT',
                                            filepath=r'X:\Projects\SMD-ANIM\work\export_test\Tees.ase')
        elif MODE == 'map':
            import math
            from mathutils import Euler
            with bpy.context.temp_override(window=win, area=area, region=region):
                r = ase_import.import_ase(bpy.context,
                                          r'X:\Projects\SMD-ANIM\work\PT_ASE_Output3\Field\forest\village-1.ase',
                                          ase_import.ImportOptions())
                area.spaces.active.region_3d.view_rotation = Euler((math.radians(55), 0, math.radians(35))).to_quaternion()
                ase_import.frame_objects(bpy.context, r['visible'])
                pick = bpy.data.objects.get('village-1_017_sod_roof')
                for o in bpy.context.view_layer.objects:
                    o.select_set(o is pick)
                bpy.context.view_layer.objects.active = pick
            area.spaces.active.region_3d.view_distance *= 0.5
            area.spaces.active.shading.type = 'MATERIAL'
            area.spaces.active.overlay.show_relationship_lines = False
            for a in win.screen.areas:                      # show the selected object in the outliner
                if a.type == 'OUTLINER':
                    reg = next(rg for rg in a.regions if rg.type == 'WINDOW')
                    with bpy.context.temp_override(window=win, area=a, region=reg):
                        bpy.ops.outliner.show_active()
                elif a.type == 'PROPERTIES':                # a tall outliner in place of the properties
                    a.type = 'OUTLINER'

        else:
            with bpy.context.temp_override(window=win, area=area, region=region):
                r = ase_import.import_ase(bpy.context, r'X:\Projects\SMD-ANIM\work\items\itWA105.ase',
                                          ase_import.ImportOptions())
                ase_import.frame_objects(bpy.context, r['visible'])
                for o in bpy.context.view_layer.objects:
                    o.select_set(False)
        st['phase'] = 1
        return 2.0
    if st['phase'] == 1:
        if MODE in ('browser', 'export'):
            fb = find_win('FILE_BROWSER')
            if fb:
                shot(fb, 'bl_file_browser.png' if MODE == 'browser' else 'bl_export_browser.png')
        else:
            if MODE == 'map':
                for a in win.screen.areas:
                    if a.type == 'OUTLINER':
                        reg = next(rg for rg in a.regions if rg.type == 'WINDOW')
                        with bpy.context.temp_override(window=win, area=a, region=reg):
                            bpy.ops.outliner.show_one_level(open=True)
                            bpy.ops.outliner.show_active()
                        a.tag_redraw()
                st['phase'] = 2
                return 1.0
            shot(win, 'bl_%s.png' % MODE)
        bpy.ops.wm.quit_blender()
        return None
    if st['phase'] == 2:
        shot(win, 'bl_%s.png' % MODE)
        bpy.ops.wm.quit_blender()
        return None


def safe_tick():
    try:
        return tick()
    except Exception:                                   # never leave a window hanging
        import traceback
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(safe_tick, first_interval=2.0)
