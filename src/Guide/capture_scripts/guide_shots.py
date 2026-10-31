import bpy, os, time, sys

OUT = r'X:\Projects\PT-World-Map\work\guide'
MODE = os.environ.get('PT_SHOT_MODE', 'prefs')
CUR = [int(v) for v in os.environ.get('PT_CURSOR', '0,0').split(',')]
log = open(os.path.join(OUT, 'blender_shots_%s.log' % MODE), 'w')
st = {'phase': 0, 't': 0.0}


def L(*a):
    print(*a, file=log, flush=True)


def shot(win, name):
    area = win.screen.areas[0]
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, name))
    L('shot', name, win.width, win.height)


def find_win(kind):
    for w in bpy.context.window_manager.windows:
        if any(a.type == kind for a in w.screen.areas):
            return w
    return None


def tick():
    try:
        wm = bpy.context.window_manager
        main = wm.windows[0]
        if MODE == 'prefs':
            if st['phase'] == 0:
                bpy.context.preferences.active_section = 'EXTENSIONS'
                with bpy.context.temp_override(window=main):
                    bpy.ops.screen.userpref_show()
                st['phase'] = 1
                return 1.5
            if st['phase'] == 1:
                pw = find_win('PREFERENCES')
                shot(pw, 'bl_1_prefs.png')
                if CUR != [0, 0]:
                    pw.cursor_warp(CUR[0], CUR[1])
                    area = next(a for a in pw.screen.areas if a.type == 'PREFERENCES')
                    region = next(r for r in area.regions if r.type == 'WINDOW')
                    with bpy.context.temp_override(window=pw, area=area, region=region):
                        bpy.ops.wm.call_menu(name='USERPREF_MT_extensions_settings')
                    st['phase'] = 2
                    return 0.2
                st['phase'] = 9
                return 0.5
            if st['phase'] == 2:
                shot(find_win('PREFERENCES'), 'bl_2_prefs_menu.png')
                st['phase'] = 9
                return 0.5
        if MODE == 'import':
            if st['phase'] == 0:
                if CUR != [0, 0]:
                    main.cursor_warp(CUR[0], CUR[1])
                area = next(a for a in main.screen.areas if a.type == 'VIEW_3D')
                with bpy.context.temp_override(window=main, area=area):
                    bpy.ops.wm.call_menu(name='TOPBAR_MT_file_import')
                st['phase'] = 1
                return 0.2
            if st['phase'] == 1:
                shot(main, 'bl_3_import_menu.png')
                # close the menu, open the file browser on the converted Ice maps
                main.cursor_warp(main.width // 2, main.height // 2)
                area = next(a for a in main.screen.areas if a.type == 'VIEW_3D')
                with bpy.context.temp_override(window=main, area=area):
                    bpy.ops.import_scene.pt_ase('INVOKE_DEFAULT',
                                                filepath=r'X:\Projects\PT-World-Map\ase_out\Field\Ice\ice1.ase')
                st['phase'] = 2
                return 2.0
            if st['phase'] == 2:
                fb = find_win('FILE_BROWSER')
                L('file browser window', fb is not None)
                if fb:
                    shot(fb, 'bl_4_file_browser.png')
                st['phase'] = 9
                return 0.5
        if MODE == 'export':
            if st['phase'] == 0:
                bpy.ops.mesh.primitive_cube_add()
                if CUR != [0, 0]:
                    main.cursor_warp(CUR[0], CUR[1])
                area = next(a for a in main.screen.areas if a.type == 'VIEW_3D')
                with bpy.context.temp_override(window=main, area=area):
                    bpy.ops.wm.call_menu(name='TOPBAR_MT_file_export')
                st['phase'] = 1
                return 0.2
            if st['phase'] == 1:
                shot(main, 'bl_7_export_menu.png')
                main.cursor_warp(main.width // 2, main.height // 2)
                area = next(a for a in main.screen.areas if a.type == 'VIEW_3D')
                with bpy.context.temp_override(window=main, area=area):
                    bpy.ops.export_scene.pt_ase('INVOKE_DEFAULT',
                                                filepath=r'X:\Projects\PT-World-Map\worklender\export_test\my_edited_map.ase')
                st['phase'] = 2
                return 2.0
            if st['phase'] == 2:
                fb = find_win('FILE_BROWSER')
                if fb:
                    shot(fb, 'bl_8_export_browser.png')
                st['phase'] = 9
                return 0.5
        bpy.ops.wm.quit_blender()
    except Exception as e:
        import traceback
        L('ERROR', e, traceback.format_exc())
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2.0)
