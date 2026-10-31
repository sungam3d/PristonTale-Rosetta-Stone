"""Priston Tale ASE importer / exporter for Blender.

File > Import > Priston Tale / 3ds Max ASE (.ase)
    Imports the .ase files made by the PT SMD -> ASE Converter (and original artist ASE files),
    with a progress bar in the status bar, then frames the imported map in the 3D viewports.
    Characters and monsters come in as an Armature with the skinned mesh and every animation;
    the "PT" tab of the 3D view sidebar (N) lists the motions (walk, attack ...) to play.
File > Export > Priston Tale / 3ds Max ASE (.ase)
    Writes .ase in the dialect PT's own loader converts to .smd (PT material keywords,
    texture layers, every UV channel, vertex colours), in game units.
"""

bl_info = {
    "name": "Priston Tale ASE Import/Export",
    "author": "PT-World-Map project",
    "version": (1, 4, 1),
    "blender": (4, 2, 0),
    "location": "File > Import / Export > Priston Tale / 3ds Max ASE (.ase)",
    "description": "Import and export 3ds Max ASCII Scene Export (.ase) files for Priston Tale, "
                   "with textures, lightmaps, baked game lighting, character skeletons and animation",
    "category": "Import-Export",
}

import os
import tempfile
import time

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       StringProperty)
from bpy.types import Operator, OperatorFileListElement
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import ase_anim, ase_export, ase_import

# files + options handed from the file-browser operator to the progress runner
_pending = []


def _default_cache():
    return os.path.join(tempfile.gettempdir(), 'pt_texture_cache')


class IMPORT_SCENE_OT_pt_ase(Operator, ImportHelper):
    """Import Priston Tale maps converted to .ase (3ds Max ASCII Scene Export)"""
    bl_idname = "import_scene.pt_ase"
    bl_label = "Import PT ASE"
    bl_options = {'REGISTER', 'PRESET'}
    filename_ext = ".ase"
    filter_glob: StringProperty(default="*.ase;*.ASE", options={'HIDDEN'})

    files: CollectionProperty(type=OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    scale: FloatProperty(name="Scale", default=0.01, min=0.0001, max=100.0,
                         description="Game units are tiny; 0.01 gives a map a few hundred metres across")
    mode: EnumProperty(name="Shading", default='GAME', items=(
        ('GAME', "Game look (unlit)", "Texture x baked vertex lighting x lightmaps, emitted as-is. "
                                      "Matches the game exactly, independent of scene lights"),
        ('LIT', "Lit (Principled)", "Same colours into a Principled BSDF so your own lights/sky shade the map"),
    ))
    vertex_colors: BoolProperty(name="Baked vertex lighting", default=True,
                                description="Use the game's baked per-vertex lighting")
    lightmaps: BoolProperty(name="Lightmaps / texture layers", default=True,
                            description="Blend 2nd+ texture layers (lightmaps, scrolling overlays)")
    smooth: BoolProperty(name="Smooth shading", default=True)
    hide_collision: BoolProperty(name="Hide collision walls", default=True,
                                 description="Put invisible collision geometry in a hidden collection")
    import_lights: BoolProperty(name="Import lights", default=False,
                                description="Import the map's dynamic (night) omni lights")
    frame_view: BoolProperty(name="Frame imported map", default=True,
                             description="Select the imported map and zoom the 3D viewports to it "
                                         "(maps are far from the world origin)")
    material_preview: BoolProperty(name="Show textures (Material Preview)", default=True,
                                   description="Switch Solid/Wireframe viewports to Material Preview")
    armature: BoolProperty(name="Skeleton (Armature + skin)", default=True,
                           description="Characters and monsters: turn the Bip01 bones into an Armature and "
                                       "skin the mesh to it (one bone per vertex, like the game)")
    pose: EnumProperty(name="Pose", default='ANIMATED', items=(
        ('ANIMATED', "Animated", "Load the character's animation and motion list (walk, attack ...). Converted "
                                 "monsters carry it inside; player armour/heads and original artist files use their "
                                 "class file (m1_motions.ase ... m8_motions.ase) next to the .ase or picked below"),
        ('TPOSE', "T-pose (bind pose)", "Bones in the bind pose, no animation"),
    ))
    animation_file: StringProperty(name="Animation file", subtype='FILE_PATH', default="",
                                   description="Optional: a converted motions file to animate with, e.g. "
                                               "m8_motions.ase for Martial Artist (found automatically when it is "
                                               "next to the imported .ase)")
    texture_dir: StringProperty(name="Extra texture folder", subtype='DIR_PATH', default="",
                                description="Optional folder searched for textures by file name")

    def draw(self, context):
        l = self.layout
        l.prop(self, "mode")
        l.prop(self, "scale")
        col = l.column(heading="Include")
        col.prop(self, "vertex_colors")
        col.prop(self, "lightmaps")
        col.prop(self, "import_lights")
        col = l.column(heading="Characters")
        col.prop(self, "armature")
        sub = col.column()
        sub.enabled = self.armature
        sub.row().prop(self, "pose", expand=True)
        sub2 = sub.column()
        sub2.enabled = self.pose == 'ANIMATED'
        sub2.label(text="Animation file (optional):")
        sub2.prop(self, "animation_file", text="")
        col = l.column(heading="Scene")
        col.prop(self, "hide_collision")
        col.prop(self, "smooth")
        col.prop(self, "frame_view")
        col.prop(self, "material_preview")
        l.prop(self, "texture_dir")

    def execute(self, context):
        if self.files and self.directory:
            paths = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        else:
            paths = [self.filepath]
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            self.report({'ERROR'}, "No .ase file selected")
            return {'CANCELLED'}
        opts = ase_import.ImportOptions(
            scale=self.scale, mode=self.mode, vertex_colors=self.vertex_colors,
            lightmaps=self.lightmaps, smooth=self.smooth, hide_collision=self.hide_collision,
            import_lights=self.import_lights, armature=self.armature, animation=self.pose == 'ANIMATED',
            animation_file=bpy.path.abspath(self.animation_file) if self.animation_file else '',
            texture_dirs=[bpy.path.abspath(self.texture_dir)] if self.texture_dir else [],
            cache_dir=_default_cache())
        _pending.append(dict(paths=paths, opts=opts, frame=self.frame_view, preview=self.material_preview))
        if context.window is None:                       # background / scripted: no UI to animate
            return bpy.ops.import_scene.pt_ase_run('EXEC_DEFAULT')
        bpy.ops.import_scene.pt_ase_run('INVOKE_DEFAULT')
        return {'FINISHED'}


class IMPORT_SCENE_OT_pt_ase_run(Operator):
    """Runs a PT ASE import step by step with a progress bar (Esc cancels)"""
    bl_idname = "import_scene.pt_ase_run"
    bl_label = "Importing PT ASE"
    bl_options = {'INTERNAL', 'UNDO'}

    _timer = None

    # -- the work, as one generator over all files
    def _steps(self, context):
        paths, opts = self.job['paths'], self.job['opts']
        n = len(paths)
        for i, p in enumerate(paths):
            gen = ase_import.import_ase_steps(context, p, opts)
            name = os.path.basename(p)
            try:
                while True:
                    f, label = next(gen)
                    prefix = ('%s  (%d of %d)' % (name, i + 1, n)) if n > 1 else name
                    yield (i + f) / n, prefix + ' - ' + label
            except StopIteration as e:
                self.results.append(e.value)

    def _start(self, context):
        if not _pending:
            return False
        self.job = _pending.pop(0)
        self.results = []
        self.cancelled = False
        self.frac = 0.0
        self.label = 'Starting'
        self.t0 = time.time()
        self.gen = self._steps(context)
        return True

    def _finish(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        try:
            wm.progress_end()
        except Exception:
            pass
        if context.workspace:
            context.workspace.status_text_set(None)
        visible = [o for r in self.results for o in r.get('visible', [])]
        if self.job['frame'] and context.window is not None:
            try:
                ase_import.frame_objects(context, visible, self.job['preview'])
            except Exception as e:  # never fail the import over the view
                print('[PT import] could not frame view:', e)
        missing = sorted(set(m for r in self.results for m in r['missing']))
        msg = "Imported %d file(s), %d objects in %.1f s" % (len(self.results), len(visible), time.time() - self.t0)
        rigs = [r['armature'] for r in self.results if r.get('armature')]
        if rigs:
            msg += "; skeleton with %d bones - motions are in the sidebar (N) > PT tab" % self.results[-1]['bones']
            try:
                context.view_layer.objects.active = rigs[-1]
            except Exception:
                pass
        no_anim = sorted(set(r['missing_animation'] for r in self.results if r.get('missing_animation')))
        if no_anim:
            msg += "; no animation found (%s) - imported in T-pose. Put it next to the .ase or pick it under Animation file" % ", ".join(os.path.basename(n) for n in no_anim)
        if self.cancelled:
            msg += " (cancelled)"
        if missing:
            msg += "; %d texture(s) not found (see console)" % len(missing)
            print("[PT import] missing textures:")
            for m in missing:
                print("   ", m)
        self.report({'WARNING'} if (missing or self.cancelled or no_anim) else {'INFO'}, msg)
        for area in context.screen.areas if context.screen else []:
            area.tag_redraw()

    def _status(self, context):
        frac, label = self.frac, self.label

        def draw(header, _ctx):
            row = header.layout.row(align=False)
            row.label(text="Importing PT ASE", icon='IMPORT')
            bar = row.row()
            bar.ui_units_x = 16
            bar.progress(factor=frac, type='BAR', text="%d%%" % int(frac * 100))
            row.label(text=label)
            row.separator()
            row.label(text=" to cancel", icon='EVENT_ESC')
        if context.workspace:
            context.workspace.status_text_set(draw)
        try:
            context.window_manager.progress_update(int(frac * 100))
        except Exception:
            pass

    # -- blocking (scripts / background)
    def execute(self, context):
        if not self._start(context):
            return {'CANCELLED'}
        for self.frac, self.label in self.gen:
            pass
        self._finish(context)
        return {'FINISHED'}

    # -- interactive
    def invoke(self, context, event):
        if not self._start(context):
            return {'CANCELLED'}
        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._status(context)
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.cancelled = True
            self._finish(context)
            return {'FINISHED'}
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}          # block input while importing
        t = time.time()
        try:
            while time.time() - t < 0.05:     # do ~50 ms of work, then let the UI redraw
                self.frac, self.label = next(self.gen)
        except StopIteration:
            self._finish(context)
            return {'FINISHED'}
        except Exception as e:
            self._finish(context)
            self.report({'ERROR'}, "PT ASE import failed: %s" % e)
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
        self._status(context)
        return {'RUNNING_MODAL'}


class EXPORT_SCENE_OT_pt_ase(Operator, ExportHelper):
    """Export objects as .ase for Priston Tale (the game converts .ase to .smd)"""
    bl_idname = "export_scene.pt_ase"
    bl_label = "Export PT ASE"
    bl_options = {'REGISTER', 'PRESET'}
    filename_ext = ".ase"
    filter_glob: StringProperty(default="*.ase;*.ASE", options={'HIDDEN'})

    selection_only: BoolProperty(name="Selected objects only", default=True)
    apply_modifiers: BoolProperty(name="Apply modifiers", default=True)
    vertex_colors: BoolProperty(name="Vertex colours", default=True,
                                description="Write vertex colours. For maps going back into the game, consider "
                                            "converting without baked lighting so the game does not light them twice")
    copy_textures: BoolProperty(name="Copy textures next to the .ase", default=True,
                                description="Copy every texture into the export folder so the folder can be "
                                            "dropped into the game as-is")
    include_lights: BoolProperty(name="Point lights", default=True)
    scale: FloatProperty(name="Scale (non-PT objects)", default=100.0, min=0.0001, max=100000.0,
                         description="Scale for objects that were not imported with the PT importer. "
                                     "100 undoes the importer's default 0.01. Imported maps always export "
                                     "in exact game units")
    skeleton: BoolProperty(name="Skeleton + skin", default=True,
                           description="Characters and monsters: write the bones and which bone each vertex "
                                       "follows (the mesh is written in its rest pose)")
    animation: EnumProperty(name="Animation", default='AUTO', items=(
        ('AUTO', "Auto", "Write a model's own animation (monsters). Player armour/heads get theirs from the "
                         "game's class file, so their shared class animation is left out"),
        ('ALWAYS', "Always", "Write the bone animation whenever there is one"),
        ('NEVER', "Never", "Bones and skin only, no animation"),
    ))

    def draw(self, context):
        l = self.layout
        l.prop(self, "selection_only")
        l.prop(self, "apply_modifiers")
        l.prop(self, "vertex_colors")
        l.prop(self, "include_lights")
        l.prop(self, "copy_textures")
        l.prop(self, "scale")
        col = l.column(heading="Characters")
        col.prop(self, "skeleton")
        sub = col.column()
        sub.enabled = self.skeleton
        sub.label(text="Animation:")
        sub.prop(self, "animation", text="")

    def execute(self, context):
        opts = ase_export.ExportOptions(
            selection_only=self.selection_only, apply_modifiers=self.apply_modifiers,
            vertex_colors=self.vertex_colors, copy_textures=self.copy_textures,
            include_lights=self.include_lights, scale=self.scale,
            skeleton=self.skeleton, animation=self.animation)
        try:
            r = ase_export.export_ase(context, self.filepath, opts)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        msg = "Exported %d object(s), %d faces, %d texture(s) in %.1f s -> %s" % (
            r['objects'], r['faces'], r['textures'], r['seconds'], os.path.basename(self.filepath))
        if r.get('bones'):
            msg += "; %d bones%s" % (r['bones'], ", with animation" if r.get('animated') else ", no animation")
        if r.get('unassigned'):
            msg += "; %d vertices have no bone (give them a vertex group)" % r['unassigned']
        self.report({'WARNING'} if r.get('unassigned') else {'INFO'}, msg)
        return {'FINISHED'}


def _menu_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_pt_ase.bl_idname, text="Priston Tale / 3ds Max ASE (.ase)")


def _menu_ase(self, context):
    self.layout.operator(IMPORT_SCENE_OT_pt_ase.bl_idname, text="Priston Tale / 3ds Max ASE (.ase)")


_classes = (IMPORT_SCENE_OT_pt_ase, IMPORT_SCENE_OT_pt_ase_run, EXPORT_SCENE_OT_pt_ase)


def register():
    ase_anim.register()
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_ase)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_ase)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    ase_anim.unregister()
