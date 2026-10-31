import bpy, sys, os, time

ASE = r'X:\Projects\PT-World-Map\ase_out\Field\LandofNurwn\LandofNurwn.ase'
OUT = r'X:\Projects\PT-World-Map\work\blender'
log = open(os.path.join(OUT, 'gui_test.log'), 'w')
state = {'phase': 0, 't': time.time(), 'mid': False}


def L(*a):
    print(*a, file=log, flush=True)


def win_ctx():
    w = bpy.context.window_manager.windows[0]
    area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return dict(window=w, screen=w.screen, area=area, region=region)


def shot(name):
    c = win_ctx()
    with bpy.context.temp_override(**c):
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, name))


def tick():
    try:
        if state['phase'] == 0:
            L('addon op registered:', hasattr(bpy.ops.import_scene, 'pt_ase'))
            with bpy.context.temp_override(**win_ctx()):
                d = os.path.join(os.path.dirname(os.path.dirname(OUT)), "ase_out", "Field")
                r = bpy.ops.import_scene.pt_ase('EXEC_DEFAULT', directory=os.path.join(d, 'forest') + os.sep,
                                                files=[{'name': 'fore-1.ase'}, {'name': 'fore-2.ase'}, {'name': 'fore-3.ase'}])
            L('menu operator returned', r)
            state['phase'] = 1
            state['t'] = time.time()
            return 0.3
        if state['phase'] == 1:
            st = bpy.context.window_manager.windows[0].workspace
            running = 'LandofNurwn' not in bpy.data.collections or bpy.context.window_manager.operators[-1:] == []
            coll = bpy.data.collections.get('fore-1')
            n = len(coll.all_objects) if coll else 0
            if not state['mid'] and time.time() - state['t'] > 1.5:
                shot('gui_mid_import.png')
                state['mid'] = True
                L('mid-import screenshot taken, objects so far', n)
            sel = [o.name for o in bpy.context.selected_objects]
            if coll and sel and len(sel) >= 3 and all(c in bpy.data.collections for c in ('fore-2', 'fore-3')):
                L('done: objects', n, 'selected', sel)
                sp = win_ctx()['area'].spaces.active
                L('shading', sp.shading.type, 'clip_end', round(sp.clip_end, 1))
                state['phase'] = 3
                state['t'] = time.time()
                return 0.5
            if time.time() - state['t'] > 120:
                L('TIMEOUT')
                state['phase'] = 2
            return 0.05
        if state['phase'] == 3:
            if time.time() - state['t'] < 12:      # let EEVEE compile its shaders
                return 0.5
            shot('gui_after_import.png')
            state['phase'] = 2
            return 1.0
        if False:
            if time.time() - state['t'] > 120:
                L('TIMEOUT')
                state['phase'] = 2
            return 0.2
        bpy.ops.wm.quit_blender()
    except Exception as e:
        import traceback
        L('ERROR', e, traceback.format_exc())
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2.0)
