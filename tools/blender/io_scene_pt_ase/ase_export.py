"""ASE exporter for Blender (Priston Tale flavour).

Writes 3ds Max ASCII Scene Export v2.00 in the same dialect as the PT Max exporter and the
converter, so the game's own ASE loader can turn it back into .smd:

  * one Multi/Sub-Object material per object (sub-material N == material slot N)
  * material names keep PT keyword flags (wind:, wall:, render_latter:, BLEND_LAMP: ...)
  * texture layer 0 -> *MAP_DIFFUSE, layers 1+ -> *MAP_SELFILLUM (PT convention), alpha -> *MAP_OPACITY;
    MAP_NAME keeps blend/scroll keywords (BS_ADD:, FS_SCROLL2: ...), *MAP_CHANNEL = UV channel
  * every UV map (UV map k -> mapping channel k+1), vertex colours, smoothing, NODE_TM, NODE_PARENT
  * objects imported with the PT importer are written back in exact game units
    (the scale of their "<map>_root" empty is undone); other objects use the Scale option
"""

import math
import os
import shutil
import time

import bpy
from mathutils import Matrix

from . import ase_anim
from . import ase_export_rig as rig


def _f(x):
    s = ('%.8f' % x).rstrip('0')
    if s.endswith('.'):
        s += '0'
    return '0.0' if s in ('-0.0', '-0') else s


def _f4(x):
    s = '%.4f' % x
    return '0.0000' if s == '-0.0000' else s


def _q(s):
    return '"%s"' % str(s).replace('"', "'")


def _p3(v):
    return '%s\t%s\t%s' % (_f(v[0]), _f(v[1]), _f(v[2]))


class ExportOptions(object):
    def __init__(self, **kw):
        self.selection_only = True
        self.include_hidden = False      # also hidden objects (a map's collision walls; the game needs them)
        self.apply_modifiers = True
        self.scale = 100.0               # for objects without a PT root (inverse of the importer's 0.01)
        self.copy_textures = True
        self.include_lights = True
        self.vertex_colors = True
        self.skeleton = True             # characters/monsters: bones + *PHYSIQUE
        self.animation = 'AUTO'          # AUTO | ALWAYS | NEVER  (AUTO: a file's own animation, i.e.
                                         # monsters; not a shared player-class animation)
        for k, v in kw.items():
            setattr(self, k, v)


# --------------------------------------------------------------------------- materials
def _upstream_image(node_input, seen=None):
    """First Image Texture node feeding this socket (through mix/math nodes)."""
    if node_input is None or not node_input.is_linked:
        return None
    seen = seen or set()
    for link in node_input.links:
        n = link.from_node
        if n in seen:
            continue
        seen.add(n)
        if n.bl_idname == 'ShaderNodeTexImage':
            return n
        for inp in n.inputs:
            r = _upstream_image(inp, seen)
            if r is not None:
                return r
    return None


def _image_channel(node, mesh):
    if 'ase_channel' in node:
        return int(node['ase_channel'])
    v = node.inputs.get('Vector')
    if v is not None and v.is_linked:
        src = v.links[0].from_node
        while src.bl_idname == 'ShaderNodeMapping' and src.inputs['Vector'].is_linked:
            src = src.inputs['Vector'].links[0].from_node
        if src.bl_idname == 'ShaderNodeUVMap' and src.uv_map and mesh is not None:
            idx = mesh.uv_layers.find(src.uv_map)
            if idx >= 0:
                return idx + 1
    return 1


def _image_path(node):
    img = node.image
    if img is None:
        return ''
    # imported textures: keep the original path (decoded copies live in a temp cache)
    if 'ase_bitmap' in node and node.get('ase_image') in (None, img.name):
        return node['ase_bitmap']
    p = img.filepath_raw or img.filepath
    return bpy.path.abspath(p) if p else img.name


class MaterialInfo(object):
    def __init__(self, mat, mesh):
        self.name = mat.get('ase_name', mat.name) if mat else 'default'
        self.diffuse = list(mat.get('ase_diffuse', mat.diffuse_color[:3])) if mat else [0.588] * 3
        self.transparency = float(mat.get('ase_transparency', 0.0)) if mat else 0.0
        self.self_illum = float(mat.get('ase_selfillum', 0.0)) if mat else 0.0
        self.two_sided = bool(mat.get('ase_two_sided', not mat.use_backface_culling)) if mat else False
        self.additive = bool(mat.get('ase_additive', False)) if mat else False
        self.maps = []          # (tag, map_name, subno, bitmap, channel)
        if mat is None or mat.node_tree is None:
            return
        nodes = [n for n in mat.node_tree.nodes if n.bl_idname == 'ShaderNodeTexImage' and n.image]
        tagged = [n for n in nodes if 'ase_role' in n]
        if tagged:
            dif = [n for n in tagged if n['ase_role'] == 'diffuse']
            lay = [n for n in tagged if n['ase_role'] == 'layer']
            opa = [n for n in tagged if n['ase_role'] == 'opacity']
        else:
            # user-made material: follow Base Color / Emission Color and Alpha back to images
            dif, lay, opa = [], [], []
            for n in mat.node_tree.nodes:
                if n.bl_idname == 'ShaderNodeBsdfPrincipled':
                    d = _upstream_image(n.inputs.get('Base Color')) or _upstream_image(n.inputs.get('Emission Color'))
                    a = _upstream_image(n.inputs.get('Alpha'))
                    if d is not None:
                        dif = [d]
                    if a is not None:
                        opa = [a]
                    break
                if n.bl_idname == 'ShaderNodeEmission':
                    d = _upstream_image(n.inputs.get('Color'))
                    if d is not None:
                        dif = [d]
            if not dif and nodes:
                dif = [nodes[0]]
        if dif:
            n = dif[0]
            self.maps.append(('*MAP_DIFFUSE', n.get('ase_map_name', 'Map #1'), 1, _image_path(n), _image_channel(n, mesh)))
        for k, n in enumerate(lay):
            self.maps.append(('*MAP_SELFILLUM', n.get('ase_map_name', 'Map #%d' % (k + 2)), 5, _image_path(n),
                              _image_channel(n, mesh)))
        if opa:
            n = opa[0]
            self.maps.append(('*MAP_OPACITY', n.get('ase_map_name', 'Map #opacity'), 6, _image_path(n),
                              _image_channel(n, mesh)))
        elif mat.get('ase_opacity_same') and dif:
            n = dif[0]
            self.maps.append(('*MAP_OPACITY', 'Map #opacity', 6, _image_path(n), _image_channel(n, mesh)))


def _write_map(w, ind, tag, name, subno, bitmap, channel):
    w('%s%s {' % (ind, tag))
    i2 = ind + '\t'
    w('%s*MAP_NAME %s' % (i2, _q(name)))
    w('%s*MAP_CLASS "Bitmap"' % i2)
    w('%s*MAP_SUBNO %d' % (i2, subno))
    w('%s*MAP_AMOUNT 1.0000' % i2)
    w('%s*BITMAP %s' % (i2, _q(bitmap)))
    w('%s*MAP_TYPE Screen' % i2)
    w('%s*MAP_CHANNEL %d' % (i2, channel))
    for k, v in (('UVW_U_OFFSET', '0.0000'), ('UVW_V_OFFSET', '0.0000'), ('UVW_U_TILING', '1.0000'),
                 ('UVW_V_TILING', '1.0000'), ('UVW_ANGLE', '0.0000'), ('UVW_BLUR', '1.0000'),
                 ('UVW_BLUR_OFFSET', '0.0000'), ('UVW_NOUSE_AMT', '1.0000'), ('UVW_NOISE_SIZE', '1.0000'),
                 ('UVW_NOISE_LEVEL', '1'), ('UVW_NOISE_PHASE', '0.0000')):
        w('%s*%s %s' % (i2, k, v))
    w('%s*BITMAP_FILTER Pyramidal' % i2)
    w('%s}' % ind)


def _write_std(w, ind, tag, idx, mi):
    w('%s%s %d {' % (ind, tag, idx))
    i2 = ind + '\t'
    d = mi.diffuse
    w('%s*MATERIAL_NAME %s' % (i2, _q(mi.name)))
    w('%s*MATERIAL_CLASS "Standard"' % i2)
    w('%s*MATERIAL_AMBIENT %s\t%s\t%s' % (i2, _f4(d[0]), _f4(d[1]), _f4(d[2])))
    w('%s*MATERIAL_DIFFUSE %s\t%s\t%s' % (i2, _f4(d[0]), _f4(d[1]), _f4(d[2])))
    w('%s*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000' % i2)
    w('%s*MATERIAL_SHINE 0.1000' % i2)
    w('%s*MATERIAL_SHINESTRENGTH 0.0000' % i2)
    w('%s*MATERIAL_TRANSPARENCY %s' % (i2, _f4(mi.transparency)))
    w('%s*MATERIAL_WIRESIZE 1.0000' % i2)
    w('%s*MATERIAL_SHADING Blinn' % i2)
    w('%s*MATERIAL_XP_FALLOFF 0.0000' % i2)
    w('%s*MATERIAL_SELFILLUM %s' % (i2, _f4(mi.self_illum)))
    if mi.two_sided:
        w('%s*MATERIAL_TWOSIDED' % i2)
    w('%s*MATERIAL_FALLOFF In' % i2)
    w('%s*MATERIAL_XP_TYPE %s' % (i2, 'Additive' if mi.additive else 'Filter'))
    for m in mi.maps:
        _write_map(w, i2, *m)
    w('%s}' % ind)


# --------------------------------------------------------------------------- geometry
def _pt_root(ob):
    p = ob.parent
    while p is not None:
        if p.get('pt_ase_root'):
            return p
        p = p.parent
    return None


def _export_space(ob, opts):
    root = _pt_root(ob)
    if root is not None:
        return root.matrix_world.inverted_safe()
    return Matrix.Scale(opts.scale, 4)


def _rows(m):
    """ASE TM rows (row vectors) from a Blender (column-vector) matrix."""
    return ([m[0][0], m[1][0], m[2][0]], [m[0][1], m[1][1], m[2][1]],
            [m[0][2], m[1][2], m[2][2]], [m[0][3], m[1][3], m[2][3]])


def _exact_rows(ob):
    """The exact (double precision) ASE pivot of an object imported with the PT importer,
    if it hasn't been moved since.  None otherwise."""
    tm, basis = ob.get('ase_tm'), ob.get('ase_basis')
    if tm is None or basis is None or _pt_root(ob) is None:
        return None
    if (ob.parent.name if ob.parent else '') != ob.get('ase_parent', ''):
        return None
    # an object with its own imported animation moves every frame; its mesh stays relative to
    # the imported pivot, which is therefore still exact
    cur = [v for row in ob.matrix_basis for v in row]
    if not ob.get('ase_anim') and any(abs(a - b) > 1e-6 * max(1.0, abs(b)) for a, b in zip(cur, basis)):
        return None
    t = list(tm)
    return [t[0:3], t[3:6], t[6:9], t[9:12]]


def _rows_from_matrix(m):
    r = _rows(m)
    return [[float(v) for v in row] for row in r]


def _axis_angle(m):
    q = m.to_3x3().normalized().to_quaternion()
    # ASE stores the conjugate-style axis (matches original 3ds Max exports)
    axis, ang = (-q).to_axis_angle() if q.w < 0 else q.to_axis_angle()
    return (-axis[0], -axis[1], -axis[2]), ang


def _write_tm(w, name, r, ind='\t'):
    m = Matrix(((r[0][0], r[1][0], r[2][0], r[3][0]), (r[0][1], r[1][1], r[2][1], r[3][1]),
                (r[0][2], r[1][2], r[2][2], r[3][2]), (0.0, 0.0, 0.0, 1.0)))
    sc = m.to_scale()
    axis, ang = _axis_angle(m)
    w('%s*NODE_TM {' % ind)
    i2 = ind + '\t'
    w('%s*NODE_NAME %s' % (i2, _q(name)))
    w('%s*INHERIT_POS 0 0 0' % i2)
    w('%s*INHERIT_ROT 0 0 0' % i2)
    w('%s*INHERIT_SCL 0 0 0' % i2)
    for k in range(4):
        w('%s*TM_ROW%d %s' % (i2, k, _p3(r[k])))
    w('%s*TM_POS %s' % (i2, _p3(r[3])))
    w('%s*TM_ROTAXIS %s' % (i2, _p3(axis)))
    w('%s*TM_ROTANGLE %s' % (i2, _f(ang)))
    w('%s*TM_SCALE %s' % (i2, _p3(sc)))
    w('%s*TM_SCALEAXIS 0.0000\t0.0000\t0.0000' % i2)
    w('%s*TM_SCALEAXISANG 0.0000' % i2)
    w('%s}' % ind)


def _uv_block(w, ind, tris, uv_data):
    index = {}
    tverts = []
    tf = []
    for tri in tris:
        f = []
        for li in tri.loops:
            u, v = uv_data[li].uv
            key = ('%.6f' % u, '%.6f' % v)
            k = index.get(key)
            if k is None:
                k = index[key] = len(tverts)
                tverts.append(key)
            f.append(k)
        tf.append(f)
    w('%s*MESH_NUMTVERTEX %d' % (ind, len(tverts)))
    w('%s*MESH_TVERTLIST {' % ind)
    for i, (u, v) in enumerate(tverts):
        w('%s\t*MESH_TVERT %d\t%s\t%s\t0.0000' % (ind, i, u, v))
    w('%s}' % ind)
    w('%s*MESH_NUMTVFACES %d' % (ind, len(tf)))
    w('%s*MESH_TFACELIST {' % ind)
    for i, f in enumerate(tf):
        w('%s\t*MESH_TFACE %d\t%d\t%d\t%d' % (ind, i, f[0], f[1], f[2]))
    w('%s}' % ind)


def _color_corners(me):
    attr = me.color_attributes.get('Col') or me.color_attributes.active_color
    if attr is None:
        return None
    n = len(attr.data)
    flat = [0.0] * (n * 4)
    attr.data.foreach_get('color', flat)
    cols = [(flat[i * 4], flat[i * 4 + 1], flat[i * 4 + 2]) for i in range(n)]
    if attr.domain == 'CORNER':
        return cols
    if attr.domain == 'POINT':
        return [cols[l.vertex_index] for l in me.loops]
    return None


def node_name(ob):
    """The name written to the ASE: the imported ASE name when Blender only added its .001
    suffix (several meshes may share a name, and the game's detail-level lists use names),
    otherwise the object's name."""
    n = ob.get('ase_name')
    if n is None:
        return ob.name
    if ob.name == ob.get('ase_import_name') or ob.name == n or \
            (n and ob.name.startswith(n + '.') and ob.name[len(n) + 1:].isdigit()):
        return n                                    # (an empty ASE name stays empty: bak_NPC_blue)
    return ob.name


def _write_geom(w, ob, me, r, mat_ref, parent_name, opts, physique=None, track=None, vfix=None):
    """vfix: {bone: 3x4+ affine (doubles)} applied to the world position of every vertex skinned
    on that bone (undoes the importer's bind maps; physique gives the bone)."""
    me.calc_loop_triangles()
    tris = list(me.loop_triangles)
    w('*GEOMOBJECT {')
    w('\t*NODE_NAME %s' % _q(node_name(ob)))
    if parent_name:
        w('\t*NODE_PARENT %s' % _q(parent_name))
    _write_tm(w, node_name(ob), r)
    w('\t*MESH {')
    w('\t\t*TIMEVALUE 0')
    w('\t\t*MESH_NUMVERTEX %d' % len(me.vertices))
    w('\t\t*MESH_NUMFACES %d' % len(tris))
    w('\t\t*MESH_VERTEX_LIST {')
    # world = local * R + t, in Python doubles
    co = [0.0] * (len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2), (t0, t1, t2) = r
    for i in range(len(me.vertices)):
        x, y, z = co[i * 3], co[i * 3 + 1], co[i * 3 + 2]
        wx, wy, wz = x * a0 + y * b0 + z * c0 + t0, x * a1 + y * b1 + z * c1 + t1, x * a2 + y * b2 + z * c2 + t2
        m = vfix.get(physique[i]) if (vfix and physique is not None and i < len(physique)) else None
        if m is not None:
            wx, wy, wz = (m[0][0] * wx + m[0][1] * wy + m[0][2] * wz + m[0][3],
                          m[1][0] * wx + m[1][1] * wy + m[1][2] * wz + m[1][3],
                          m[2][0] * wx + m[2][1] * wy + m[2][2] * wz + m[2][3])
        w('\t\t\t*MESH_VERTEX %5d\t%s\t%s\t%s' % (i, _f(wx), _f(wy), _f(wz)))
    w('\t\t}')
    w('\t\t*MESH_FACE_LIST {')
    polys = me.polygons
    for i, t in enumerate(tris):
        a, b, c = t.vertices
        smooth = '1' if polys[t.polygon_index].use_smooth else ''
        w('\t\t\t*MESH_FACE %5d:    A: %5d B: %5d C: %5d AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING %s \t*MESH_MTLID %d'
          % (i, a, b, c, smooth, t.material_index))
    w('\t\t}')
    uvs = list(me.uv_layers)
    # extra channels first (legacy importers then still end with channel 1)
    for k in range(1, len(uvs)):
        w('\t\t*MESH_MAPPINGCHANNEL %d {' % (k + 1))
        _uv_block(w, '\t\t\t', tris, uvs[k].data)
        w('\t\t}')
    if uvs:
        _uv_block(w, '\t\t', tris, uvs[0].data)
    else:
        w('\t\t*MESH_NUMTVERTEX 0')
    cols = _color_corners(me) if opts.vertex_colors else None
    if cols:
        index = {}
        cv = []
        cf = []
        for t in tris:
            f = []
            for li in t.loops:
                c = cols[li]
                key = (_f4(c[0]), _f4(c[1]), _f4(c[2]))
                k = index.get(key)
                if k is None:
                    k = index[key] = len(cv)
                    cv.append(key)
                f.append(k)
            cf.append(f)
        w('\t\t*MESH_NUMCVERTEX %d' % len(cv))
        w('\t\t*MESH_CVERTLIST {')
        for i, c in enumerate(cv):
            w('\t\t\t*MESH_VERTCOL %d\t%s\t%s\t%s' % (i, c[0], c[1], c[2]))
        w('\t\t}')
        w('\t\t*MESH_NUMCVFACES %d' % len(cf))
        w('\t\t*MESH_CFACELIST {')
        for i, f in enumerate(cf):
            w('\t\t\t*MESH_CFACE %d\t%d\t%d\t%d' % (i, f[0], f[1], f[2]))
        w('\t\t}')
    w('\t}')
    w('\t*PROP_MOTIONBLUR 0')
    w('\t*PROP_CASTSHADOW 1')
    w('\t*PROP_RECVSHADOW 1')
    if track:
        rig.write_tm_animation(w, node_name(ob), track)
    w('\t*MATERIAL_REF %d' % mat_ref)
    if physique is not None:
        rig.write_physique(w, physique)
    elif ob.get('pt_physique_empty'):
        rig.write_physique(w, [])                   # a rigid part of a character: a mesh, not a bone
    w('}')


def _write_light(w, ob, r):
    ld = ob.data
    w('*LIGHTOBJECT {')
    w('\t*NODE_NAME %s' % _q(ob.name))
    w('\t*LIGHT_TYPE Omni')
    _write_tm(w, ob.name, r)
    w('\t*LIGHT_SHADOWS Off')
    w('\t*LIGHT_USELIGHT 1')
    w('\t*LIGHT_SPOTSHAPE Circle')
    w('\t*LIGHT_USEGLOBAL 0')
    w('\t*LIGHT_ABSMAPBIAS 0')
    w('\t*LIGHT_OVERSHOOT 0')
    w('\t*LIGHT_SETTINGS {')
    w('\t\t*TIMEVALUE 0')
    w('\t\t*LIGHT_COLOR %s' % _p3(ld.color))
    w('\t\t*LIGHT_INTENS 1.0000')
    w('\t\t*LIGHT_ASPECT -1.0000')
    w('\t\t*LIGHT_ATTNSTART 0.0000')
    w('\t\t*LIGHT_ATTNEND %s' % _f4(max(1.0, ld.energy / 50.0)))
    w('\t}')
    w('}')


# --------------------------------------------------------------------------- entry point
def export_ase(context, filepath, opts=None):
    opts = opts or ExportOptions()
    t0 = time.time()
    if opts.selection_only:
        objs = [o for o in context.selected_objects]
    else:
        objs = [o for o in context.view_layer.objects if o.visible_get() or opts.include_hidden]
    meshes = [o for o in objs if o.type in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT')]
    # imported objects in their file order (three meshes all called "fi_d" in dfi), new ones after
    meshes.sort(key=lambda o: (0, o.get('ase_index', 0)) if 'ase_index' in o else (1, 0))
    lights = [o for o in objs if o.type == 'LIGHT' and o.data.type == 'POINT'] if opts.include_lights else []
    # characters / monsters: the armatures of the exported meshes, plus selected armatures
    # (selecting just the armature exports the meshes it deforms too)
    arms = []
    if opts.skeleton:
        for o in objs:
            if o.type == 'ARMATURE' and o not in arms:
                arms.append(o)
        for o in meshes:
            a = rig.armature_of(o)
            if a is not None and a not in arms:
                arms.append(a)
        for o in context.view_layer.objects:
            if o.type == 'MESH' and o not in meshes and rig.armature_of(o) in arms and (o.visible_get() or opts.include_hidden):
                meshes.append(o)
    if not meshes and not lights and not arms:
        raise RuntimeError("Nothing to export: select one or more mesh objects")
    with_anim = {}
    for a in arms:
        act = a.animation_data.action if a.animation_data else None
        own = a.get('pt_anim_source', 'own') != 'shared'
        with_anim[a.name] = act is not None and (opts.animation == 'ALWAYS' or (opts.animation == 'AUTO' and own))
    tracks = {}
    for a in arms:
        if with_anim[a.name]:
            tracks[a.name] = rig.bone_tracks(a, _export_space(a, opts), a.animation_data.action)
    last_tick = max([k[0] for tr in tracks.values() for (p, r, s) in tr.values() for k in p + r] or [0])

    depsgraph = context.evaluated_depsgraph_get()
    out_dir = os.path.dirname(os.path.abspath(filepath))
    exported = set(meshes)

    # objects with their own animation (map props: windmills, doors ...) keep it
    obj_tracks = {}
    if opts.animation != 'NEVER':
        for ob in meshes:
            if rig.armature_of(ob) is not None:
                continue
            on_bone = ob.parent_type == 'BONE' and ob.parent is not None and ob.parent.type == 'ARMATURE'                 and ob.parent_bone in ob.parent.data.bones
            if ob.parent_type == 'BONE' and not on_bone:
                continue

            def local_of(basis, ob=ob, on_bone=on_bone):
                if on_bone:
                    # a rigid part riding on a bone: Blender hangs it on the bone's tail, in Blender
                    # bone axes -> relative to the bone in 3ds Max axes, as the game reads it
                    b = ob.parent.data.bones[ob.parent_bone]
                    ax = ase_anim.bone_axes(ob.parent)[b.name]
                    return ax @ Matrix.Translation((0.0, b.length, 0.0)) @ ob.matrix_parent_inverse @ basis
                if ob.parent is not None and ob.parent in exported:
                    return ob.matrix_parent_inverse @ basis          # relative to its ASE parent
                pw = ob.parent.matrix_world if ob.parent is not None else Matrix.Identity(4)
                return _export_space(ob, opts) @ pw @ ob.matrix_parent_inverse @ basis
            tr = rig.object_track(ob, local_of)
            if tr:
                obj_tracks[ob] = tr
                last_tick = max([last_tick] + [k[0] for k in tr[0] + tr[1]])

    # one Multi/Sub material per distinct slot list
    mat_sets = []
    mat_ref = {}
    for ob in meshes:
        key = tuple(s.material.name if s.material else '' for s in ob.material_slots)
        if key not in mat_sets:
            mat_sets.append(key)
        mat_ref[ob] = mat_sets.index(key)

    lines = []
    w = lines.append
    w('*3DSMAX_ASCIIEXPORT\t200')
    w('*COMMENT "AsciiExport Version  2.00 - PT ASE Exporter (Blender %s)"' % bpy.app.version_string)
    scn = context.scene
    w('*SCENE {')
    w('\t*SCENE_FILENAME %s' % _q(os.path.splitext(os.path.basename(filepath))[0] + '.max'))
    w('\t*SCENE_FIRSTFRAME %d' % scn.frame_start)
    w('\t*SCENE_LASTFRAME %d' % (max(1, int(math.ceil(last_tick / 160.0))) if (tracks or obj_tracks) else scn.frame_end))
    w('\t*SCENE_FRAMESPEED %d' % scn.render.fps)
    w('\t*SCENE_TICKSPERFRAME 160')
    w('\t*SCENE_BACKGROUND_STATIC 0.0000\t0.0000\t0.0000')
    w('\t*SCENE_AMBIENT_STATIC 0.0000\t0.0000\t0.0000')
    w('}')
    rig.write_motions(w, arms, with_anim)

    copied = {}

    def tex_path(p):
        if not opts.copy_textures or not p or not os.path.isfile(p):
            return p
        name = os.path.basename(p)
        dst = os.path.join(out_dir, name)
        if name.lower() not in copied:
            if os.path.abspath(p).lower() != os.path.abspath(dst).lower():
                shutil.copy2(p, dst)
            copied[name.lower()] = dst
        return copied[name.lower()]

    w('*MATERIAL_LIST {')
    w('\t*MATERIAL_COUNT %d' % len(mat_sets))
    sample = {}
    for ob in meshes:
        sample.setdefault(mat_ref[ob], ob)
    for i, key in enumerate(mat_sets):
        ob = sample[i]
        mesh = ob.data if ob.type == 'MESH' else None
        infos = []
        for s in ob.material_slots:
            mi = MaterialInfo(s.material, mesh)
            mi.maps = [(t, n, sub, tex_path(b), ch) for (t, n, sub, b, ch) in mi.maps]
            infos.append(mi)
        w('\t*MATERIAL %d {' % i)
        w('\t\t*MATERIAL_NAME %s' % _q('PT_' + (ob.name if len(infos) else 'default')))
        w('\t\t*MATERIAL_CLASS "Multi/Sub-Object"')
        w('\t\t*MATERIAL_AMBIENT 0.5880\t0.5880\t0.5880')
        w('\t\t*MATERIAL_DIFFUSE 0.5880\t0.5880\t0.5880')
        w('\t\t*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000')
        w('\t\t*MATERIAL_SHINE 0.1000')
        w('\t\t*MATERIAL_SHINESTRENGTH 0.0000')
        w('\t\t*MATERIAL_TRANSPARENCY 0.0000')
        w('\t\t*MATERIAL_WIRESIZE 1.0000')
        if not infos:
            infos = [MaterialInfo(None, None)]
        w('\t\t*NUMSUBMTLS %d' % len(infos))
        for k, mi in enumerate(infos):
            _write_std(w, '\t\t', '*SUBMATERIAL', k, mi)
        w('\t}')
    w('}')

    wm = context.window_manager
    try:
        wm.progress_begin(0, len(meshes) + 1)
    except Exception:
        pass
    total_faces = 0
    unassigned = 0
    arm_names = {a.name for a in arms}
    unbind = {}
    for n, ob in enumerate(meshes):
        r = _exact_rows(ob) or _rows_from_matrix(_export_space(ob, opts) @ ob.matrix_world)
        a = rig.armature_of(ob) if arms else None
        skinned = a is not None and a in arms
        rest = rig.RestPose(ob) if skinned else None
        if rest:
            rest.__enter__()                        # skinned meshes are written in their rest pose
        try:
            dg = context.evaluated_depsgraph_get() if skinned else depsgraph
            src = ob.evaluated_get(dg) if opts.apply_modifiers else ob
            me = src.to_mesh()
            try:
                if ob.parent_type == 'BONE' and ob.parent is not None and ob.parent.name in arm_names:
                    parent = ob.parent_bone             # rigid part riding on a bone
                elif skinned:
                    # follows its bones through *PHYSIQUE; a bone it hung on in the file stays its parent
                    np_ = ob.get('ase_node_parent', '')
                    parent = np_ if np_ and np_ in a.data.bones else ''
                else:
                    parent = node_name(ob.parent) if ob.parent in exported else ''
                phys = None
                if skinned:
                    phys, miss = rig.physique(ob, me, {b.name for b in a.data.bones})
                    unassigned += miss
                # vertices are written in world space; the inverse is applied by readers via NODE_TM
                vfix = None
                if skinned and ob.get('pt_bind_fixed') and _pt_root(a) is not None:
                    vfix = unbind.setdefault(a.name, rig.unbind_maps(a))
                _write_geom(w, ob, me, r, mat_ref[ob], parent, opts, phys, obj_tracks.get(ob), vfix)
                total_faces += len(me.loop_triangles)
            finally:
                src.to_mesh_clear()
        finally:
            if rest:
                rest.__exit__()
        try:
            wm.progress_update(n + 1)
        except Exception:
            pass
    bones = 0
    for a in arms:
        bones += rig.write_bones(w, a, _export_space(a, opts), tracks.get(a.name, {}))
    for ob in lights:
        _write_light(w, ob, _rows_from_matrix(_export_space(ob, opts) @ ob.matrix_world))
    try:
        wm.progress_end()
    except Exception:
        pass

    with open(filepath, 'w', encoding='latin-1', errors='replace', newline='\r\n') as f:
        f.write('\n'.join(lines))
        f.write('\n')
    return dict(objects=len(meshes), lights=len(lights), faces=total_faces, textures=len(copied),
                seconds=time.time() - t0, bones=bones, animated=sorted(tracks), unassigned=unassigned)
