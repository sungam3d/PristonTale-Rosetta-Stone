"""Priston Tale ASE importer / exporter for Blender.

Priston Tale menu (top bar) and File > Import > Priston Tale (.ase, .smd, .smb)
    One choice says what is imported (map as in the game / for editing, character animated / T-pose /
    mesh only, or just an animation onto the character in the scene), as in the 3ds Max plug-in.
    Opens .ase files and the game's .smd / .smb directly (converted by PT_RosettaStone's smd2ase.exe),
    with a progress bar in the status bar, then frames the imported map in the 3D viewports.
    Characters and monsters come in as an Armature with the skinned mesh and every animation;
    the "PT" tab of the 3D view sidebar (N) lists the motions (walk, attack ...) to play.
Priston Tale menu and File > Export > Priston Tale (.ase)
    Writes .ase in the dialect PT's own loader converts to .smd (PT material keywords,
    texture layers, every UV channel, vertex colours), in game units.
"""

bl_info = {
    "name": "Priston Tale ASE Import/Export",
    "author": "sungam3d",
    "version": (1, 5, 0),
    "blender": (4, 2, 0),
    "location": "Priston Tale menu, File > Import / Export > Priston Tale",
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

from bpy.app.translations import pgettext_rpt as rpt_
from bpy.app.translations import pgettext_iface as iface_

from . import ase_anim, ase_export, ase_import, translations

# files + options handed from the file-browser operator to the progress runner
_pending = []


def _default_cache():
    return os.path.join(tempfile.gettempdir(), 'pt_texture_cache')


def _fill(text, *args):
    """A translated message with {1} {2} ... filled in (the same texts as the 3ds Max plug-in)."""
    t = rpt_(text)
    for i, a in enumerate(args):
        t = t.replace('{%d}' % (i + 1), str(a))
    return t


def _wrapped(layout, text, width=None, context=None):
    """A long hint as several label lines (translated first, then wrapped to the panel's width)."""
    import textwrap
    if width is None:
        region = getattr(context or bpy.context, 'region', None)
        px = region.width if region is not None and region.width > 50 else 300
        scale = bpy.context.preferences.view.ui_scale * bpy.context.preferences.system.ui_scale or 1.0
        width = max(20, int(px / (6.5 * scale)) - 2)
    col = layout.column(align=True)
    col.scale_y = 0.8
    for line in textwrap.wrap(iface_(text), width):
        col.label(text=line, translate=False)


def _check(layout, data, prop, text, context):
    """A checkbox whose long text wraps instead of being cut off (the file browser's side panel is narrow)."""
    row = layout.row(align=False)
    row.prop(data, prop, text="")
    _wrapped(row, text, context=context)


# What are you importing? - one choice sets everything up, as in the 3ds Max plug-in; the single
# settings are under "Advanced options" (closed).
_WHAT = (
    ('MAP_GAME', "Map - as seen in the game",
     "The map with its textures and baked lighting, as the game shows it. Collision walls are hidden."),
    ('MAP_EDIT', "Map - for editing and exporting",
     "Everything you need to change the map and export it again: collision walls visible on their own layer, "
     "lights included."),
    ('CHAR_ANIM', "Character / monster - animated",
     "Skeleton, skin and animation (a monster's own; armour uses its class file, e.g. m1.smb, found next to it)."),
    ('CHAR_TPOSE', "Character / monster - T-pose, with bones",
     "Skeleton and skin in the bind pose, without animation - the pose to edit the model in."),
    ('CHAR_MESH', "Character / monster - mesh only, no bones",
     "Just the mesh, without a skeleton (weapons and items have none anyway)."),
    ('ANIM_ONLY', "Animation only - onto the character in the scene",
     "Replaces the animation of the character in the scene with this file's (a class file m1.smb ... m8.smb, "
     "or a monster's)."),
)


def _what_changed(self, context):
    w = self.what
    if w in ('MAP_GAME', 'MAP_EDIT'):
        self.mode = 'GAME'
        self.vertex_colors = True
        self.lightmaps = True
        self.hide_collision = w == 'MAP_GAME'
        self.import_lights = w == 'MAP_EDIT'
        self.armature = True
        self.pose = 'ANIMATED'
    elif w == 'CHAR_ANIM':
        self.armature = True
        self.pose = 'ANIMATED'
    elif w == 'CHAR_TPOSE':
        self.armature = True
        self.pose = 'TPOSE'
    elif w == 'CHAR_MESH':
        self.armature = False


class IMPORT_SCENE_OT_pt_ase(Operator, ImportHelper):
    """Import Priston Tale maps and models: converted .ase files, or the game's .smd / .smb directly"""
    bl_idname = "import_scene.pt_ase"
    bl_label = "Import"
    bl_options = {'REGISTER', 'PRESET'}
    filename_ext = ".ase"
    filter_glob: StringProperty(default="*.ase;*.ASE;*.smd;*.SMD;*.smb;*.SMB", options={'HIDDEN'})

    files: CollectionProperty(type=OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    what: EnumProperty(name="What are you importing?", default='MAP_GAME', update=_what_changed,
                       items=[(k, n, h) for k, n, h in _WHAT])
    preset_now: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    whole_folder: BoolProperty(name="Folder with .ase files (searched recursively)", default=False,
                               description="Import every .ase / .smd / .smb in the folder shown, and the folders in it")

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
                                   description="Optional: the animation to use, e.g. the game's m8.smb or a "
                                               "converted m8_motions.ase for Martial Artist (found automatically "
                                               "when it is next to the imported file)")
    texture_dir: StringProperty(name="Extra texture folder", subtype='DIR_PATH', default="",
                                description="Optional folder searched for textures by file name")

    def draw(self, context):
        l = self.layout
        l.label(text="What are you importing?")
        l.prop(self, "what", text="")                    # (the file browser's side panel is narrow)
        _wrapped(l, next(h for k, n, h in _WHAT if k == self.what), context=context)
        if self.what != 'ANIM_ONLY':
            l.prop(self, "whole_folder", text="Import a whole folder...")
        _wrapped(l, "Opens .ase files, and game files (.smd, .smb) directly.", context=context)
        if self.what == 'ANIM_ONLY':
            return
        header, body = l.panel("PT_ASE_import_advanced", default_closed=True)
        header.label(text="Advanced options")
        if body is None:
            return
        col = body.column(heading="Shading")
        col.prop(self, "mode", text="")
        col.prop(self, "vertex_colors")
        col.prop(self, "lightmaps")
        col = body.column(heading="Scene")
        col.prop(self, "hide_collision")
        col.prop(self, "import_lights")
        col.prop(self, "scale")
        col.prop(self, "smooth")
        col.prop(self, "frame_view")
        col.prop(self, "material_preview")
        col.label(text="Extra texture folder:")
        col.prop(self, "texture_dir", text="")
        col = body.column(heading="Characters / monsters")
        col.prop(self, "armature")
        sub = col.column()
        sub.enabled = self.armature
        sub.row().prop(self, "pose", expand=True)
        sub2 = sub.column()
        sub2.enabled = self.pose == 'ANIMATED'
        sub2.label(text="Animation file (optional, e.g. m8.ase):")
        sub2.prop(self, "animation_file", text="")

    def invoke(self, context, event):
        if self.preset_now:                               # (from the import window: its choice's settings)
            self.preset_now = False
            _what_changed(self, context)
        return ImportHelper.invoke(self, context, event)

    def _paths(self):
        if self.whole_folder and self.what != 'ANIM_ONLY':
            d = self.directory or os.path.dirname(self.filepath)
            return ase_import.find_files(d) if d and os.path.isdir(d) else []
        if self.files and self.directory:
            paths = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        else:
            paths = [self.filepath]
        return [p for p in paths if os.path.isfile(p)]

    def execute(self, context):
        paths = self._paths()
        if not paths:
            self.report({'ERROR'}, rpt_("No .ase files found."))
            return {'CANCELLED'}
        # game files: converted to .ase first (PT_RosettaStone's converter)
        ase, errors = [], []
        for p in paths:
            try:
                ase.append(ase_import.to_ase(p))
            except RuntimeError as e:
                errors.append(_fill(*e.args))
        for e in errors:
            print('[PT import]', e)
        if not ase:
            self.report({'ERROR'}, errors[0] if errors else rpt_("No .ase files found."))
            return {'CANCELLED'}
        if self.what == 'ANIM_ONLY':
            try:
                name, found, total = ase_import.apply_animation(context, ase[0])
            except RuntimeError as e:
                self.report({'ERROR'}, _fill(*e.args))
                return {'CANCELLED'}
            self.report({'INFO'}, _fill("PT ASE: animation of {1} put on {2} of {3} bones", name, found, total))
            return {'FINISHED'}
        anim = self.animation_file
        if anim:
            try:
                anim = ase_import.to_ase(bpy.path.abspath(anim))
            except RuntimeError as e:
                self.report({'ERROR'}, _fill(*e.args))
                return {'CANCELLED'}
        opts = ase_import.ImportOptions(
            scale=self.scale, mode=self.mode, vertex_colors=self.vertex_colors,
            lightmaps=self.lightmaps, smooth=self.smooth, hide_collision=self.hide_collision,
            import_lights=self.import_lights, armature=self.armature, animation=self.pose == 'ANIMATED',
            animation_file=anim,
            texture_dirs=[bpy.path.abspath(self.texture_dir)] if self.texture_dir else [],
            cache_dir=_default_cache())
        _pending.append(dict(paths=ase, opts=opts, frame=self.frame_view, preview=self.material_preview))
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
        msg = rpt_("Imported %d file(s), %d objects in %.1f s") % (len(self.results), len(visible), time.time() - self.t0)
        rigs = [r['armature'] for r in self.results if r.get('armature')]
        if rigs:
            msg += rpt_("; skeleton with %d bones - motions are in the sidebar (N) > PT tab") % self.results[-1]['bones']
            try:
                context.view_layer.objects.active = rigs[-1]
            except Exception:
                pass
        no_anim = sorted(set(r['missing_animation'] for r in self.results if r.get('missing_animation')))
        if no_anim:
            msg += rpt_("; no animation found (%s) - imported in T-pose. Put it next to the .ase or pick it under Animation file") % ", ".join(os.path.basename(n) for n in no_anim)
        if self.cancelled:
            msg += rpt_(" (cancelled)")
        if missing:
            msg += rpt_("; %d texture(s) not found (see console)") % len(missing)
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
            self.report({'ERROR'}, rpt_("PT ASE import failed: %s") % e)
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
        self._status(context)
        return {'RUNNING_MODAL'}


class EXPORT_SCENE_OT_pt_ase(Operator, ExportHelper):
    """Export objects as .ase for Priston Tale (ENCODE in PT_RosettaStone.exe builds the game's .smd / .smb)"""
    bl_idname = "export_scene.pt_ase"
    bl_label = "Export ASE"
    bl_options = {'REGISTER', 'PRESET'}
    filename_ext = ".ase"
    filter_glob: StringProperty(default="*.ase;*.ASE", options={'HIDDEN'})

    which: EnumProperty(name="Export:", default='SELECTED', items=(
        ('SELECTED', "Selected objects", ""),
        ('ALL', "Everything in the scene", ""),
    ))
    include_hidden: BoolProperty(name="Include hidden objects (a map's collision walls)", default=True,
                                 description="Hidden objects too: a map's collision walls sit in a hidden "
                                             "collection and the game needs them")
    copy_textures: BoolProperty(name="Copy textures next to the exported .ase", default=True,
                                description="Copy every texture into the export folder so the folder can be "
                                            "dropped into the game as-is")
    animation: EnumProperty(name="Characters: export animation", default='AUTO', items=(
        ('AUTO', "Auto (monsters yes, player armour no)",
         "Write a model's own animation (monsters). Player armour/heads get theirs from the "
         "game's class file, so their shared class animation is left out"),
        ('ALWAYS', "Always", "Write the bone animation whenever there is one"),
        ('NEVER', "Never", "Bones and skin only, no animation"),
    ))

    apply_modifiers: BoolProperty(name="Apply modifiers", default=True)
    vertex_colors: BoolProperty(name="Vertex colours", default=True,
                                description="Write vertex colours (the baked lighting of a map)")
    include_lights: BoolProperty(name="Point lights", default=True)
    scale: FloatProperty(name="Scale (non-PT objects)", default=100.0, min=0.0001, max=100000.0,
                         description="Scale for objects that were not imported with the PT importer. "
                                     "100 undoes the importer's default 0.01. Imported maps always export "
                                     "in exact game units")
    skeleton: BoolProperty(name="Skeleton + skin", default=True,
                           description="Characters and monsters: write the bones and which bone each vertex "
                                       "follows (the mesh is written in its rest pose)")

    def draw(self, context):
        l = self.layout
        l.label(text="Export:")
        l.props_enum(self, "which")
        _check(l, self, "include_hidden", "Include hidden objects (a map's collision walls)", context)
        _check(l, self, "copy_textures", "Copy textures next to the exported .ase", context)
        l.label(text="Characters: export animation")
        l.prop(self, "animation", text="")
        _wrapped(l, "Then drop the .ase on ENCODE in PT_RosettaStone.exe: it builds the game's .smd (and .smb).",
                 context=context)
        header, body = l.panel("PT_ASE_export_advanced", default_closed=True)
        header.label(text="Advanced options")
        if body is None:
            return
        body.prop(self, "skeleton")
        body.prop(self, "apply_modifiers")
        body.prop(self, "vertex_colors")
        body.prop(self, "include_lights")
        body.prop(self, "scale")

    def execute(self, context):
        if self.which == 'SELECTED' and not context.selected_objects:
            self.report({'ERROR'}, rpt_("Nothing selected: select the objects to export, or choose 'Everything in the scene'."))
            return {'CANCELLED'}
        opts = ase_export.ExportOptions(
            selection_only=self.which == 'SELECTED', include_hidden=self.include_hidden,
            apply_modifiers=self.apply_modifiers,
            vertex_colors=self.vertex_colors, copy_textures=self.copy_textures,
            include_lights=self.include_lights, scale=self.scale,
            skeleton=self.skeleton, animation=self.animation)
        try:
            r = ase_export.export_ase(context, self.filepath, opts)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        msg = rpt_("Exported %d object(s), %d faces, %d texture(s) in %.1f s -> %s") % (
            r['objects'], r['faces'], r['textures'], r['seconds'], os.path.basename(self.filepath))
        if r.get('bones'):
            msg += rpt_("; %d bones%s") % (r['bones'], rpt_(", with animation") if r.get('animated') else rpt_(", no animation"))
        if r.get('unassigned'):
            msg += rpt_("; %d vertices have no bone (give them a vertex group)") % r['unassigned']
        self.report({'WARNING'} if r.get('unassigned') else {'INFO'}, msg)
        return {'FINISHED'}


class PT_ASE_OT_import_window(Operator):
    """The import window, as in the 3ds Max plug-in: say what you are importing, then pick the files"""
    bl_idname = "pt_ase.import_window"
    bl_label = "Priston Tale - Import"

    what: EnumProperty(name="What are you importing?", default='MAP_GAME',
                       items=[(k, n, h) for k, n, h in _WHAT])

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=440)

    def draw(self, context):
        l = self.layout
        l.label(text="Priston Tale - Import", icon='IMPORT')
        l.label(text="What are you importing?")
        l.props_enum(self, "what")
        _wrapped(l, next(h for k, n, h in _WHAT if k == self.what), width=70)
        col = l.column()
        col.scale_y = 1.4
        op = col.operator(IMPORT_SCENE_OT_pt_ase.bl_idname, text="Import file(s)...", icon='FILEBROWSER')
        op.what = self.what
        op.whole_folder = False
        op.preset_now = True
        if self.what != 'ANIM_ONLY':
            op = l.operator(IMPORT_SCENE_OT_pt_ase.bl_idname, text="Import a whole folder...", icon='FILE_FOLDER')
            op.what = self.what
            op.whole_folder = True
            op.preset_now = True
        l.label(text="Opens .ase files, and game files (.smd, .smb) directly.")

    def execute(self, context):
        return {'FINISHED'}


class PT_ASE_OT_export_window(Operator):
    """The export window, as in the 3ds Max plug-in"""
    bl_idname = "pt_ase.export_window"
    bl_label = "Priston Tale - Export"

    which: EnumProperty(name="Export:", default='SELECTED', items=(
        ('SELECTED', "Selected objects", ""), ('ALL', "Everything in the scene", "")))
    include_hidden: BoolProperty(name="Include hidden objects (a map's collision walls)", default=True)
    copy_textures: BoolProperty(name="Copy textures next to the exported .ase", default=True)
    animation: EnumProperty(name="Characters: export animation", default='AUTO', items=(
        ('AUTO', "Auto (monsters yes, player armour no)", ""), ('ALWAYS', "Always", ""), ('NEVER', "Never", "")))

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=440)

    def draw(self, context):
        l = self.layout
        l.label(text="Priston Tale - Export", icon='EXPORT')
        l.label(text="Export:")
        l.props_enum(self, "which")
        l.prop(self, "include_hidden")
        l.prop(self, "copy_textures")
        l.label(text="Characters: export animation")
        l.prop(self, "animation", text="")
        col = l.column()
        col.scale_y = 1.4
        op = col.operator(EXPORT_SCENE_OT_pt_ase.bl_idname, text="Export ASE...", icon='FILEBROWSER')
        op.which = self.which
        op.include_hidden = self.include_hidden
        op.copy_textures = self.copy_textures
        op.animation = self.animation
        _wrapped(l, "Then drop the .ase on ENCODE in PT_RosettaStone.exe: it builds the game's .smd (and .smb).",
                 width=70)

    def execute(self, context):
        return {'FINISHED'}


class PT_ASE_OT_motions(Operator):
    """Priston Tale motion list (walk, attack ...)"""
    bl_idname = "pt_ase.show_motions"
    bl_label = "Motions..."

    def execute(self, context):
        ob = context.view_layer.objects.active
        if ob is not None and ob.type != 'ARMATURE':
            ob = ob.find_armature() if ob.type == 'MESH' else None
        if ob is None:
            ob = next((o for o in context.view_layer.objects if o.type == 'ARMATURE' and len(o.pt_motions)), None)
        if ob is None or not len(ob.pt_motions):
            self.report({'WARNING'}, rpt_("No motion list loaded.\nImport a character or monster .ase first.").replace('\n', ' '))
            return {'CANCELLED'}
        context.view_layer.objects.active = ob
        bpy.ops.wm.call_panel(name='VIEW3D_PT_pt_motions', keep_open=True)
        return {'FINISHED'}


class TOPBAR_MT_priston_tale(bpy.types.Menu):
    """The Priston Tale menu, as in 3ds Max"""
    bl_idname = "TOPBAR_MT_priston_tale"
    bl_label = "Priston Tale"

    def draw(self, context):
        l = self.layout
        l.operator(PT_ASE_OT_import_window.bl_idname, text="Import...", icon='IMPORT')
        l.operator(PT_ASE_OT_export_window.bl_idname, text="Export...", icon='EXPORT')
        l.separator()
        l.operator(PT_ASE_OT_motions.bl_idname, text="Motions...", icon='ACTION')


def _menu_top(self, context):
    self.layout.menu(TOPBAR_MT_priston_tale.bl_idname)


def _menu_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_pt_ase.bl_idname, text="Priston Tale (.ase)")


def _menu_ase(self, context):
    self.layout.operator(IMPORT_SCENE_OT_pt_ase.bl_idname, text="Priston Tale (.ase, .smd, .smb)")


_classes = (IMPORT_SCENE_OT_pt_ase, IMPORT_SCENE_OT_pt_ase_run, EXPORT_SCENE_OT_pt_ase, PT_ASE_OT_import_window, PT_ASE_OT_export_window, PT_ASE_OT_motions,
            TOPBAR_MT_priston_tale)


def register():
    translations.register()
    ase_anim.register()
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_ase)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    bpy.types.TOPBAR_MT_editor_menus.append(_menu_top)


def unregister():
    bpy.types.TOPBAR_MT_editor_menus.remove(_menu_top)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_ase)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    ase_anim.unregister()
    translations.unregister()
