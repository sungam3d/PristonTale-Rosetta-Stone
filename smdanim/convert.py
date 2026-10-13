"""SMD -> ASE conversion.

Produces standard 3ds Max ASCII Scene Export (ASE v2.00) text.

Conventions used in the generated ASE (all readable by the bundled Blender
and 3ds Max importers, and by PT's own ASE loader):

  * One Multi/Sub-Object material per file; sub-material N == SMD material.
  * Sub-material names reproduce PT keyword flags ("wind:", "wall:",
    "render_latter:", "BLEND_LAMP:", "anim8:flame%d.tga:6" ...).
  * Texture layer 0  -> *MAP_DIFFUSE        (UVs: main *MESH_TVERTLIST, channel 1)
    Texture layer k  -> *MAP_SELFILLUM #k   (UVs: *MESH_MAPPINGCHANNEL k+1)
    This is exactly how PT artists authored multi-layer materials (lightmaps
    and scrolling overlays).  Each map also carries "*MAP_CHANNEL n".
    MAP_NAME carries the blend/scroll keywords (BS_ADD:, FS_SCROLL2: ...).
  * Alpha textures -> *MAP_OPACITY.
  * Stage vertex colours = the game's baked lighting (sDef_Color / 255).
  * Untextured collision faces (wall:, pass: helpers...) go into a separate
    "<map>__collision" object so they can be hidden with one click.
"""

import math
import os

from .smdfile import Stage, Model, SMDError, file_kind, BLEND_TYPE_NAMES
from .textures import resolve_case_insensitive, decode_texture_file


# ----------------------------------------------------------------------------- math
def _inv3(m):
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    A = e * i - f * h
    B = -(d * i - f * g)
    C = d * h - e * g
    det = a * A + b * B + c * C
    if abs(det) < 1e-12:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    inv = [[A, -(b * i - c * h), b * f - c * e],
           [B, a * i - c * g, -(a * f - c * d)],
           [C, -(a * h - b * g), a * e - b * d]]
    return [[v / det for v in row] for row in inv]


def _xform(p, rows, t):
    return (p[0] * rows[0][0] + p[1] * rows[1][0] + p[2] * rows[2][0] + t[0],
            p[0] * rows[0][1] + p[1] * rows[1][1] + p[2] * rows[2][1] + t[1],
            p[0] * rows[0][2] + p[1] * rows[1][2] + p[2] * rows[2][2] + t[2])


def _rows_to_axis_angle(rows):
    """TM rows -> (axis, angle, scale) in ASE convention (matches original files)."""
    sc = [math.sqrt(sum(v * v for v in r)) or 1.0 for r in rows]
    R = [[rows[r][c] / sc[r] for c in range(3)] for r in range(3)]
    M = [[R[c][r] for c in range(3)] for r in range(3)]  # M = R^T  (== PT quaternion matrix)
    tr = M[0][0] + M[1][1] + M[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (M[1][2] - M[2][1]) / s
        y = (M[2][0] - M[0][2]) / s
        z = (M[0][1] - M[1][0]) / s
    elif M[0][0] > M[1][1] and M[0][0] > M[2][2]:
        s = math.sqrt(1.0 + M[0][0] - M[1][1] - M[2][2]) * 2
        w = (M[1][2] - M[2][1]) / s
        x = 0.25 * s
        y = (M[1][0] + M[0][1]) / s
        z = (M[2][0] + M[0][2]) / s
    elif M[1][1] > M[2][2]:
        s = math.sqrt(1.0 + M[1][1] - M[0][0] - M[2][2]) * 2
        w = (M[2][0] - M[0][2]) / s
        x = (M[1][0] + M[0][1]) / s
        y = 0.25 * s
        z = (M[2][1] + M[1][2]) / s
    else:
        s = math.sqrt(1.0 + M[2][2] - M[0][0] - M[1][1]) * 2
        w = (M[0][1] - M[1][0]) / s
        x = (M[2][0] + M[0][2]) / s
        y = (M[2][1] + M[1][2]) / s
        z = 0.25 * s
    return _quat_to_axis_angle((x, y, z, w)) + (tuple(sc),)


def _quat_to_axis_angle(q):
    x, y, z, w = q
    w = max(-1.0, min(1.0, w))
    ang = 2.0 * math.acos(w)
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-7:
        return (0.0, 0.0, 0.0), 0.0
    return (x / s, y / s, z / s), ang


# ----------------------------------------------------------------------------- scene model
class GeomObject(object):
    def __init__(self, name):
        self.name = name
        self.parent = ''
        self.rows = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.pos = (0.0, 0.0, 0.0)
        self.verts = []            # world positions (Max axes)
        self.faces = []            # (a, b, c, sub-material index)
        self.channels = []         # [channel][face] -> ((u,v),(u,v),(u,v)) in ASE convention
        self.colors = None         # per-vertex (r,g,b) floats or None
        self.pos_keys = []
        self.rot_keys = []         # (tick, axis, angle)
        self.scale_keys = []


class Scene(object):
    def __init__(self, name):
        self.name = name
        self.materials = []        # output order (smdfile.Material)
        self.objects = []
        self.lights = []
        self.last_frame = 100
        self.texture_paths = {}    # smd texture string -> output path string
        self.source = ''
        self.kind = ''


# ----------------------------------------------------------------------------- options
class Options(object):
    def __init__(self, **kw):
        self.game_root = None          # root folder that contains 'Field', 'char', ...
        self.texture_out = None        # copy+decrypt textures here (None = reference in place)
        self.texture_dir_override = None  # use this folder (flat) for every BITMAP path
        self.split_collision = True
        self.drop_collision = False
        self.compact_materials = True
        self.vertex_colors = True
        self.clamp_colors = True
        self.color_scale = 1.0
        self.include_bones = False
        self.include_lights = True
        self.texture_log = None        # dict collecting missing textures
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError('unknown option %s' % k)
            setattr(self, k, v)


def guess_game_root(path):
    """Walk up from an SMD path to the folder containing 'Field'."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        parent = os.path.dirname(d)
        if os.path.basename(d).lower() == 'field':
            return parent
        if parent == d:
            return os.path.dirname(os.path.abspath(path))
        d = parent


# ----------------------------------------------------------------------------- builders
def _material_remap(materials, used, compact):
    if not compact:
        return list(materials), {m.index: m.index for m in materials}
    order = [m for m in materials if m.index in used]
    return order, {m.index: i for i, m in enumerate(order)}


def _channels_from_layers(face_layers, nlayers, v_mode):
    """face_layers: per face list of (u0,u1,u2,v0,v1,v2).  Returns [channel][face]."""
    chans = []
    for k in range(nlayers):
        ch = []
        for layers in face_layers:
            if k < len(layers):
                u0, u1, u2, v0, v1, v2 = layers[k]
                if v_mode == 'neg':
                    ch.append(((u0, -v0), (u1, -v1), (u2, -v2)))
                else:
                    ch.append(((u0, 1.0 - v0), (u1, 1.0 - v1), (u2, 1.0 - v2)))
            else:
                ch.append(((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)))
        chans.append(ch)
    if not chans:
        chans.append([((0.0, 0.0),) * 3 for _ in face_layers])
    return chans


def build_stage_scene(path, opt):
    st = Stage(path)
    name = os.path.splitext(os.path.basename(path))[0]
    sc = Scene(name)
    sc.kind = 'stage'
    sc.source = path
    mats = st.materials
    nmat = len(mats)

    used = set(f[3] for f in st.faces if f[3] < nmat)
    sc.materials, remap = _material_remap(mats, used, opt.compact_materials)

    nlayers = st.max_layers()
    colors = None
    if opt.vertex_colors:
        colors = []
        for (r, g, b, a) in st.colors:
            c = [v * opt.color_scale / 255.0 for v in (r, g, b)]
            if opt.clamp_colors:
                c = [min(1.0, max(0.0, v)) for v in c]
            colors.append(tuple(c))

    groups = [('', [])]
    coll = []
    for fi, f in enumerate(st.faces):
        m = mats[f[3]] if f[3] < nmat else None
        if opt.split_collision and (m is None or m.is_collision):
            coll.append(fi)
        else:
            groups[0][1].append(fi)
    if coll and not opt.drop_collision:
        groups.append(('__collision', coll))

    for suffix, fidx in groups:
        if not fidx and suffix:
            continue
        go = GeomObject(name + suffix)
        vmap = {}
        faces = []
        for fi in fidx:
            a, b, c, m = st.faces[fi]
            out = []
            for v in (a, b, c):
                if v not in vmap:
                    vmap[v] = len(go.verts)
                    go.verts.append(st.positions[v])
                out.append(vmap[v])
            faces.append((out[0], out[1], out[2], remap.get(m, 0)))
        go.faces = faces
        if colors is not None:
            inv = [0] * len(vmap)
            for k, v in vmap.items():
                inv[v] = k
            go.colors = [colors[k] for k in inv]
        go.channels = _channels_from_layers([st.face_uvs[fi] for fi in fidx], nlayers, 'neg')
        sc.objects.append(go)

    if opt.include_lights:
        sc.lights = st.lights
    sc.stage = st
    return sc


def _model_world(o):
    """World rows & translation for a model object (exactly what PT used to
    convert the original world-space vertices to local space)."""
    ti = [[o.tminv[r][c] / 256.0 for c in range(3)] for r in range(3)]
    rows = _inv3(ti)
    t = (o.tm[3][0] / 256.0, o.tm[3][1] / 256.0, o.tm[3][2] / 256.0)
    return rows, t


def find_bone_file(path):
    base = os.path.splitext(path)[0]
    for ext in ('.smb', '.SMB', '.Smb'):
        if os.path.isfile(base + ext):
            return base + ext
    return None


def build_model_scene(path, opt, bone_path=None):
    md = Model(path)
    name = os.path.splitext(os.path.basename(path))[0]
    sc = Scene(name)
    sc.kind = 'model'
    sc.source = path
    mats = md.materials
    nmat = len(mats)
    used = set()
    for o in md.objects:
        for f in o.faces:
            if f[3] < nmat:
                used.add(f[3])
    sc.materials, remap = _material_remap(mats, used, opt.compact_materials)

    bones = {}
    needs_bones = any(o.physique for o in md.objects)
    bone_model = None
    if needs_bones:
        bone_path = bone_path or find_bone_file(path)
        if bone_path and os.path.isfile(bone_path):
            bone_model = Model(bone_path)
            for b in bone_model.objects:
                bones[b.name] = _model_world(b)
    sc.missing_bones = needs_bones and not bones

    def emit(o, is_bone=False):
        rows, t = _model_world(o)
        go = GeomObject(o.name)
        go.parent = o.parent
        go.rows, go.pos = rows, t
        if o.physique:
            vs = []
            for lv, bn in zip(o.local_verts, o.physique):
                br, bt = bones.get(bn, (rows, t))
                vs.append(_xform(lv, br, bt))
            go.verts = vs
        else:
            go.verts = [_xform(v, rows, t) for v in o.local_verts]
        go.faces = [(a, b, c, remap.get(m, 0)) for (a, b, c, m) in o.faces]
        nl = max([len(l) for l in o.face_uvs] or [0])
        go.channels = _channels_from_layers(o.face_uvs, nl, 'one_minus')
        go.pos_keys = list(o.pos_keys)
        go.rot_keys = [(k[0],) + _quat_to_axis_angle(k[1:5]) for k in o.rot_keys]
        go.scale_keys = list(o.scale_keys)
        go.is_bone = is_bone
        return go

    if opt.include_bones and bone_model:
        for b in bone_model.objects:
            sc.objects.append(emit(b, True))
    for o in md.objects:
        sc.objects.append(emit(o))
    ticks = md.last_frame_ticks()
    if bone_model:
        ticks = max(ticks, bone_model.last_frame_ticks())
    sc.last_frame = max(1, ticks // 160) if ticks else 100
    sc.model = md
    return sc


def build_scene(path, opt):
    kind = file_kind(path)
    if kind == 'stage':
        return build_stage_scene(path, opt)
    if kind == 'model':
        return build_model_scene(path, opt)
    raise SMDError('%s: unknown file type' % path)


# ----------------------------------------------------------------------------- textures
def resolve_textures(sc, opt, smd_path):
    root = opt.game_root or guess_game_root(smd_path)
    names = set()
    for m in sc.materials:
        for n, na in m.textures + m.anim_textures:
            if n:
                names.add(n)
            if na:
                names.add(na)
    for n in sorted(names):
        rel = n.replace('\\', '/')
        src = resolve_case_insensitive(root, rel)
        if src is None and opt.texture_log is not None:
            opt.texture_log.setdefault(n, set()).add(os.path.basename(smd_path))
        if opt.texture_dir_override:
            out = os.path.join(opt.texture_dir_override, os.path.basename(src or rel))
        elif opt.texture_out:
            relpath = os.path.relpath(src, root) if src else rel
            out = os.path.join(opt.texture_out, relpath)
            if src and not os.path.isfile(out):
                decode_texture_file(src, out)
        else:
            out = src or os.path.join(root, rel)
        sc.texture_paths[n] = os.path.abspath(out).replace('/', '\\')


# ----------------------------------------------------------------------------- writer
def _f(x):
    s = '%.8f' % x
    s = s.rstrip('0')
    if s.endswith('.'):
        s += '0000'
    elif len(s) - s.index('.') < 5:
        s += '0' * (5 - (len(s) - s.index('.')))
    if s == '-0.0000':
        s = '0.0000'
    return s


def _f4(x):
    s = '%.4f' % x
    return '0.0000' if s == '-0.0000' else s


def _f6(x):
    s = '%.6f' % x
    return '0.000000' if s == '-0.000000' else s


def _q(s):
    return '"%s"' % s.replace('"', "'")


def _write_map(w, ind, tag, map_name, subno, bitmap, channel):
    w('%s%s {' % (ind, tag))
    i2 = ind + '\t'
    w('%s*MAP_NAME %s' % (i2, _q(map_name)))
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


def _write_material(w, sc, idx, m, ind):
    tp = sc.texture_paths
    name = m.pt_name() or ('%d - Default' % (m.index + 1))
    w('%s*SUBMATERIAL %d {' % (ind, idx))
    i2 = ind + '\t'
    d = m.diffuse
    w('%s*MATERIAL_NAME %s' % (i2, _q(name)))
    w('%s*MATERIAL_CLASS "Standard"' % i2)
    w('%s*MATERIAL_AMBIENT %s\t%s\t%s' % (i2, _f4(d[0]), _f4(d[1]), _f4(d[2])))
    w('%s*MATERIAL_DIFFUSE %s\t%s\t%s' % (i2, _f4(d[0]), _f4(d[1]), _f4(d[2])))
    w('%s*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000' % i2)
    w('%s*MATERIAL_SHINE 0.1000' % i2)
    w('%s*MATERIAL_SHINESTRENGTH 0.0000' % i2)
    w('%s*MATERIAL_TRANSPARENCY %s' % (i2, _f4(m.transparency)))
    w('%s*MATERIAL_WIRESIZE 1.0000' % i2)
    w('%s*MATERIAL_SHADING Blinn' % i2)
    w('%s*MATERIAL_XP_FALLOFF 0.0000' % i2)
    w('%s*MATERIAL_SELFILLUM %s' % (i2, _f4(m.self_illum)))
    if m.two_sided:
        w('%s*MATERIAL_TWOSIDED' % i2)
    w('%s*MATERIAL_FALLOFF In' % i2)
    w('%s*MATERIAL_XP_TYPE %s' % (i2, 'Additive' if m.blend_type in (4, 5) else 'Filter'))
    # PT extension block - ignored by other readers, used by our importers
    w('%s*PT_MATERIAL {' % i2)
    w('%s\t*PT_INDEX %d' % (i2, m.index))
    w('%s\t*PT_BLEND %s' % (i2, BLEND_TYPE_NAMES.get(m.blend_type, str(m.blend_type))))
    w('%s\t*PT_USESTATE %d' % (i2, m.use_state))
    w('%s\t*PT_COLLISION %d' % (i2, 1 if m.is_collision else 0))
    w('%s\t*PT_TEXTYPE %d' % (i2, m.texture_type))
    if m.anim_textures:
        w('%s\t*PT_ANIM_SPEED %d' % (i2, m.anim_speed_shift))
        for n, _na in m.anim_textures:
            w('%s\t*PT_ANIM_FRAME %s' % (i2, _q(tp.get(n, n))))
    w('%s}' % i2)
    layers = list(m.textures)
    if not layers and m.anim_textures:
        layers = [m.anim_textures[0]]
    for k, (n, na) in enumerate(layers):
        if k == 0:
            _write_map(w, i2, '*MAP_DIFFUSE', m.layer_map_name(0) or ('Map #%d' % (m.index * 8 + 1)),
                       1, tp.get(n, n), 1)
        else:
            _write_map(w, i2, '*MAP_SELFILLUM', m.layer_map_name(k) or ('Map #%d' % (m.index * 8 + 1 + k)),
                       5, tp.get(n, n), k + 1)
    if layers:
        n0, na0 = layers[0]
        if m.map_opacity or na0:
            _write_map(w, i2, '*MAP_OPACITY', 'Map #%d' % (m.index * 8 + 7), 6, tp.get(na0 or n0, na0 or n0), 1)
    w('%s}' % ind)


def _write_tm(w, go, ind):
    w('%s*NODE_TM {' % ind)
    i2 = ind + '\t'
    axis, ang, scale = _rows_to_axis_angle(go.rows)
    w('%s*NODE_NAME %s' % (i2, _q(go.name)))
    w('%s*INHERIT_POS 0 0 0' % i2)
    w('%s*INHERIT_ROT 0 0 0' % i2)
    w('%s*INHERIT_SCL 0 0 0' % i2)
    for r in range(3):
        w('%s*TM_ROW%d %s\t%s\t%s' % (i2, r, _f4(go.rows[r][0]), _f4(go.rows[r][1]), _f4(go.rows[r][2])))
    p = go.pos
    w('%s*TM_ROW3 %s\t%s\t%s' % (i2, _f(p[0]), _f(p[1]), _f(p[2])))
    w('%s*TM_POS %s\t%s\t%s' % (i2, _f(p[0]), _f(p[1]), _f(p[2])))
    w('%s*TM_ROTAXIS %s\t%s\t%s' % (i2, _f4(axis[0]), _f4(axis[1]), _f4(axis[2])))
    w('%s*TM_ROTANGLE %s' % (i2, _f4(ang)))
    w('%s*TM_SCALE %s\t%s\t%s' % (i2, _f4(scale[0]), _f4(scale[1]), _f4(scale[2])))
    w('%s*TM_SCALEAXIS 0.0000\t0.0000\t0.0000' % i2)
    w('%s*TM_SCALEAXISANG 0.0000' % i2)
    w('%s}' % ind)


def _write_uv_block(w, ind, channel_faces):
    tv = {}
    tlist = []
    tfaces = []
    for tri in channel_faces:
        idx = []
        for uv in tri:
            key = (round(uv[0], 6), round(uv[1], 6))
            k = tv.get(key)
            if k is None:
                k = tv[key] = len(tlist)
                tlist.append(key)
            idx.append(k)
        tfaces.append(idx)
    w('%s*MESH_NUMTVERTEX %d' % (ind, len(tlist)))
    if tlist:
        w('%s*MESH_TVERTLIST {' % ind)
        for i, (u, v) in enumerate(tlist):
            w('%s\t*MESH_TVERT %d\t%s\t%s\t0.0000' % (ind, i, _f6(u), _f6(v)))
        w('%s}' % ind)
    w('%s*MESH_NUMTVFACES %d' % (ind, len(tfaces)))
    if tfaces:
        w('%s*MESH_TFACELIST {' % ind)
        for i, (a, b, c) in enumerate(tfaces):
            w('%s\t*MESH_TFACE %d\t%d\t%d\t%d' % (ind, i, a, b, c))
        w('%s}' % ind)


def _write_geom(w, sc, go):
    w('*GEOMOBJECT {')
    w('\t*NODE_NAME %s' % _q(go.name))
    if go.parent:
        w('\t*NODE_PARENT %s' % _q(go.parent))
    _write_tm(w, go, '\t')
    w('\t*MESH {')
    w('\t\t*TIMEVALUE 0')
    w('\t\t*MESH_NUMVERTEX %d' % len(go.verts))
    w('\t\t*MESH_NUMFACES %d' % len(go.faces))
    w('\t\t*MESH_VERTEX_LIST {')
    for i, v in enumerate(go.verts):
        w('\t\t\t*MESH_VERTEX %5d\t%s\t%s\t%s' % (i, _f(v[0]), _f(v[1]), _f(v[2])))
    w('\t\t}')
    w('\t\t*MESH_FACE_LIST {')
    for i, (a, b, c, m) in enumerate(go.faces):
        w('\t\t\t*MESH_FACE %5d:    A: %5d B: %5d C: %5d AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING 1 \t*MESH_MTLID %d'
          % (i, a, b, c, m))
    w('\t\t}')
    # Extra mapping channels are written BEFORE the main UV list: legacy ASE
    # importers that don't understand MESH_MAPPINGCHANNEL then still end up
    # with channel 1 (the main list overwrites whatever they read first).
    for k in range(1, len(go.channels)):
        w('\t\t*MESH_MAPPINGCHANNEL %d {' % (k + 1))
        _write_uv_block(w, '\t\t\t', go.channels[k])
        w('\t\t}')
    _write_uv_block(w, '\t\t', go.channels[0] if go.channels else [])
    if go.colors is not None:
        w('\t\t*MESH_NUMCVERTEX %d' % len(go.colors))
        w('\t\t*MESH_CVERTLIST {')
        for i, c in enumerate(go.colors):
            w('\t\t\t*MESH_VERTCOL %d\t%s\t%s\t%s' % (i, _f4(c[0]), _f4(c[1]), _f4(c[2])))
        w('\t\t}')
        w('\t\t*MESH_NUMCVFACES %d' % len(go.faces))
        w('\t\t*MESH_CFACELIST {')
        for i, (a, b, c, m) in enumerate(go.faces):
            w('\t\t\t*MESH_CFACE %d\t%d\t%d\t%d' % (i, a, b, c))
        w('\t\t}')
    w('\t}')
    w('\t*PROP_MOTIONBLUR 0')
    w('\t*PROP_CASTSHADOW 1')
    w('\t*PROP_RECVSHADOW 1')
    if go.pos_keys or go.rot_keys or go.scale_keys:
        w('\t*TM_ANIMATION {')
        w('\t\t*NODE_NAME %s' % _q(go.name))
        if go.pos_keys:
            w('\t\t*CONTROL_POS_TRACK {')
            for (t, x, y, z) in go.pos_keys:
                w('\t\t\t*CONTROL_POS_SAMPLE %d\t%s\t%s\t%s' % (t, _f4(x), _f4(y), _f4(z)))
            w('\t\t}')
        if go.rot_keys:
            w('\t\t*CONTROL_ROT_TRACK {')
            for (t, ax, ang) in go.rot_keys:
                w('\t\t\t*CONTROL_ROT_SAMPLE %d\t%s\t%s\t%s\t%s' % (t, _f4(ax[0]), _f4(ax[1]), _f4(ax[2]), _f4(ang)))
            w('\t\t}')
        if go.scale_keys:
            w('\t\t*CONTROL_SCALE_TRACK {')
            for (t, x, y, z) in go.scale_keys:
                w('\t\t\t*CONTROL_SCALE_SAMPLE %d\t%s\t%s\t%s\t0.0000\t0.0000\t0.0000\t0.0000'
                  % (t, _f4(x), _f4(y), _f4(z)))
            w('\t\t}')
        w('\t}')
    w('\t*MATERIAL_REF 0')
    w('}')


def _write_light(w, i, L):
    nm = '%s%02d' % (L.name(), i)
    w('*LIGHTOBJECT {')
    w('\t*NODE_NAME %s' % _q(nm))
    w('\t*LIGHT_TYPE Omni')
    w('\t*NODE_TM {')
    w('\t\t*NODE_NAME %s' % _q(nm))
    w('\t\t*INHERIT_POS 0 0 0')
    w('\t\t*INHERIT_ROT 0 0 0')
    w('\t\t*INHERIT_SCL 0 0 0')
    w('\t\t*TM_ROW0 1.0000\t0.0000\t0.0000')
    w('\t\t*TM_ROW1 0.0000\t1.0000\t0.0000')
    w('\t\t*TM_ROW2 0.0000\t0.0000\t1.0000')
    p = L.pos
    w('\t\t*TM_ROW3 %s\t%s\t%s' % (_f(p[0]), _f(p[1]), _f(p[2])))
    w('\t\t*TM_POS %s\t%s\t%s' % (_f(p[0]), _f(p[1]), _f(p[2])))
    w('\t\t*TM_ROTAXIS 0.0000\t0.0000\t0.0000')
    w('\t\t*TM_ROTANGLE 0.0000')
    w('\t\t*TM_SCALE 1.0000\t1.0000\t1.0000')
    w('\t\t*TM_SCALEAXIS 0.0000\t0.0000\t0.0000')
    w('\t\t*TM_SCALEAXISANG 0.0000')
    w('\t}')
    w('\t*LIGHT_SHADOWS Off')
    w('\t*LIGHT_USELIGHT 1')
    w('\t*LIGHT_SPOTSHAPE Circle')
    w('\t*LIGHT_USEGLOBAL 0')
    w('\t*LIGHT_ABSMAPBIAS 0')
    w('\t*LIGHT_OVERSHOOT 0')
    w('\t*LIGHT_SETTINGS {')
    w('\t\t*TIMEVALUE 0')
    c = L.color
    w('\t\t*LIGHT_COLOR %s\t%s\t%s' % (_f4(c[0] / 255.0), _f4(c[1] / 255.0), _f4(c[2] / 255.0)))
    w('\t\t*LIGHT_INTENS 1.0000')
    w('\t\t*LIGHT_ASPECT -1.0000')
    w('\t\t*LIGHT_ATTNSTART 0.0000')
    w('\t\t*LIGHT_ATTNEND %s' % _f4(L.range))
    w('\t\t*LIGHT_MAPBIAS 1.0000')
    w('\t\t*LIGHT_MAPRANGE 4.0000')
    w('\t\t*LIGHT_MAPSIZE 512')
    w('\t\t*LIGHT_RAYBIAS 0.0000')
    w('\t}')
    w('}')


def write_ase(sc, out_path):
    lines = []
    w = lines.append
    w('*3DSMAX_ASCIIEXPORT\t200')
    w('*COMMENT "AsciiExport Version  2.00 - PT smd2ase from %s"' % os.path.basename(sc.source))
    w('*SCENE {')
    w('\t*SCENE_FILENAME %s' % _q(sc.name + '.max'))
    w('\t*SCENE_FIRSTFRAME 0')
    w('\t*SCENE_LASTFRAME %d' % sc.last_frame)
    w('\t*SCENE_FRAMESPEED 30')
    w('\t*SCENE_TICKSPERFRAME 160')
    w('\t*SCENE_BACKGROUND_STATIC 0.0000\t0.0000\t0.0000')
    w('\t*SCENE_AMBIENT_STATIC 0.0000\t0.0000\t0.0000')
    w('}')
    w('*MATERIAL_LIST {')
    w('\t*MATERIAL_COUNT 1')
    w('\t*MATERIAL 0 {')
    w('\t\t*MATERIAL_NAME %s' % _q('PT_' + sc.name))
    w('\t\t*MATERIAL_CLASS "Multi/Sub-Object"')
    w('\t\t*MATERIAL_AMBIENT 0.5880\t0.5880\t0.5880')
    w('\t\t*MATERIAL_DIFFUSE 0.5880\t0.5880\t0.5880')
    w('\t\t*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000')
    w('\t\t*MATERIAL_SHINE 0.1000')
    w('\t\t*MATERIAL_SHINESTRENGTH 0.0000')
    w('\t\t*MATERIAL_TRANSPARENCY 0.0000')
    w('\t\t*MATERIAL_WIRESIZE 1.0000')
    w('\t\t*NUMSUBMTLS %d' % len(sc.materials))
    for i, m in enumerate(sc.materials):
        _write_material(w, sc, i, m, '\t\t')
    w('\t}')
    w('}')
    for go in sc.objects:
        _write_geom(w, sc, go)
    for i, L in enumerate(sc.lights):
        _write_light(w, i, L)
    d = os.path.dirname(out_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out_path, 'w', encoding='latin-1', newline='\r\n') as f:
        f.write('\n'.join(lines))
        f.write('\n')


def convert_file(smd_path, out_path, opt=None):
    opt = opt or Options()
    sc = build_scene(smd_path, opt)
    resolve_textures(sc, opt, smd_path)
    write_ase(sc, out_path)
    return sc
