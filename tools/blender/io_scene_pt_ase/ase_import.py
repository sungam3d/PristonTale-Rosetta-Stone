"""3ds Max ASE importer for Blender, tuned for Priston Tale maps.

Reads any ASCII Scene Export file (original artist files and smd2ase output):
geometry, multi/sub materials, every UV channel (MESH_MAPPINGCHANNEL),
vertex colours, NODE_TM hierarchy, omni lights.

Material modes
  GAME : Emission( texture x vertex colour x layers ) -> exactly the in-game
         look; scene lighting is ignored (PT bakes lighting into vertex colours).
  LIT  : Principled BSDF with the same colour graph, for your own lighting.
"""

import math
import os
import tempfile
import time
import zlib

import bpy
from mathutils import Matrix, Vector

from .aseparse import parse_ase, find, find_all, val, unquote
from .textures import decode_texture_bytes
from . import ase_anim


# --------------------------------------------------------------------------- helpers
def _floats(s, n=None):
    out = []
    for t in s.split():
        try:
            out.append(float(t))
        except ValueError:            # '-1.#QNB' etc. from old Max exporters
            out.append(0.0)
    return out if n is None else (out + [0.0] * n)[:n]


def _sock(sockets, ident):
    for s in sockets:
        if s.identifier == ident:
            return s
    return sockets[ident]


def _walk_geoms(node, out):
    for c in node[2] or ():
        if c[0] in ('*GEOMOBJECT', '*LIGHTOBJECT', '*HELPEROBJECT'):
            out.append(c)
        elif c[0] == '*GROUP':
            _walk_geoms(c, out)
    return out


# --------------------------------------------------------------------------- materials
class MapDef(object):
    def __init__(self, slot, node):
        self.slot = slot
        self.name = unquote(val(node, '*MAP_NAME', ''))
        self.bitmap = ''
        self.channel = 1
        self.u_off = self.v_off = self.angle = 0.0
        self.u_tile = self.v_tile = 1.0
        bm = self._first_bitmap(node)
        if bm is not None:
            self.bitmap = unquote(val(bm, '*BITMAP', ''))
            self.channel = int(_floats(val(bm, '*MAP_CHANNEL', '1'), 1)[0]) or 1
            self.u_off = _floats(val(bm, '*UVW_U_OFFSET', '0'), 1)[0]
            self.v_off = _floats(val(bm, '*UVW_V_OFFSET', '0'), 1)[0]
            self.u_tile = _floats(val(bm, '*UVW_U_TILING', '1'), 1)[0] or 1.0
            self.v_tile = _floats(val(bm, '*UVW_V_TILING', '1'), 1)[0] or 1.0
            self.angle = _floats(val(bm, '*UVW_ANGLE', '0'), 1)[0]

    @staticmethod
    def _first_bitmap(node):
        if val(node, '*BITMAP') is not None:
            return node
        for c in node[2] or ():
            if c[2]:
                r = MapDef._first_bitmap(c)
                if r is not None:
                    return r
        return None

    def has_xform(self):
        return (abs(self.u_off) > 1e-5 or abs(self.v_off) > 1e-5 or abs(self.u_tile - 1) > 1e-5 or
                abs(self.v_tile - 1) > 1e-5 or abs(self.angle) > 1e-5)


class MatDef(object):
    def __init__(self, node, label):
        self.node = node
        self.label = label
        self.name = unquote(val(node, '*MATERIAL_NAME', 'Material'))
        self.cls = unquote(val(node, '*MATERIAL_CLASS', 'Standard'))
        self.diffuse = _floats(val(node, '*MATERIAL_DIFFUSE', '0.588 0.588 0.588'), 3)
        self.transparency = _floats(val(node, '*MATERIAL_TRANSPARENCY', '0'), 1)[0]
        self.self_illum = _floats(val(node, '*MATERIAL_SELFILLUM', '0'), 1)[0]
        self.two_sided = find(node, '*MATERIAL_TWOSIDED') is not None
        self.additive = val(node, '*MATERIAL_XP_TYPE', '') == 'Additive'
        pt = find(node, '*PT_MATERIAL')
        self.pt_blend = val(pt, '*PT_BLEND', '') if pt else ''
        self.collision = bool(pt) and val(pt, '*PT_COLLISION', '0') == '1'
        if self.pt_blend in ('lamp', 'addcolor'):
            self.additive = True
        self.diffuse_map = None
        self.layers = []           # extra texture layers (MAP_SELFILLUM in PT convention)
        self.opacity_map = None
        for c in node[2] or ():
            if c[0] == '*MAP_DIFFUSE' and self.diffuse_map is None:
                self.diffuse_map = MapDef('diffuse', c)
            elif c[0] == '*MAP_SELFILLUM':
                self.layers.append(MapDef('selfillum', c))
            elif c[0] == '*MAP_OPACITY':
                self.opacity_map = MapDef('opacity', c)
        if self.collision is False and not pt and self.diffuse_map is None and \
                any(f in self.name for f in ('wall:', 'notpass:')):
            self.collision = True
        self.subs = {}
        self.num_subs = int(_floats(val(node, '*NUMSUBMTLS', '0'), 1)[0])
        for s in find_all(node, '*SUBMATERIAL'):
            try:
                idx = int(s[1].split()[0])
            except (ValueError, IndexError):
                continue
            self.subs[idx] = MatDef(s, '%s.%d' % (label, idx))

    def resolve(self, mtlid):
        m = self
        while m.cls == 'Shell Material' and m.subs:
            m = m.subs.get(0) or list(m.subs.values())[0]
        if m.subs or m.num_subs:
            n = m.num_subs or (max(m.subs) + 1)
            sub = m.subs.get(mtlid % n if n else 0)
            if sub is None:
                return None
            return sub.resolve(0) if (sub.subs or sub.cls == 'Shell Material') else sub
        return m


# --------------------------------------------------------------------------- images
class ImageCache(object):
    def __init__(self, ase_dir, search_dirs, cache_dir):
        self.ase_dir = ase_dir
        self.search_dirs = [d for d in search_dirs if d]
        self.cache_dir = cache_dir
        self.images = {}
        self.missing = set()

    def _locate(self, path):
        if not path:
            return None
        cands = [path]
        base = os.path.basename(path.replace('\\', '/'))
        for d in [self.ase_dir] + self.search_dirs:
            cands.append(os.path.join(d, base))
        stem, ext = os.path.splitext(base)
        for d in [os.path.dirname(path)] + [self.ase_dir] + self.search_dirs:
            for e in ('.bmp', '.tga', '.BMP', '.TGA', '.png', '.dds'):
                cands.append(os.path.join(d, stem + e))
        for c in cands:
            if c and os.path.isfile(c):
                return c
        # the converter's "textures" folder next to the .ase (any depth), by file name
        if not hasattr(self, '_index'):
            self._index = {}
            tex = os.path.join(self.ase_dir, 'textures')
            for d, _s, files in os.walk(tex) if os.path.isdir(tex) else ():
                for n in files:
                    self._index.setdefault(n.lower(), os.path.join(d, n))
                    self._index.setdefault(os.path.splitext(n)[0].lower(), os.path.join(d, n))
        return self._index.get(base.lower()) or self._index.get(stem.lower())

    def get(self, path):
        if path in self.images:
            return self.images[path]
        img = None
        real = self._locate(path)
        if real:
            with open(real, 'rb') as f:
                head = f.read(2)
            if head in (b'A8', b'G8'):                 # encrypted PT client texture
                with open(real, 'rb') as f:
                    data, _ = decode_texture_bytes(f.read())
                os.makedirs(self.cache_dir, exist_ok=True)
                # stable name (path, size, date): the same texture reuses its decoded copy in
                # every session instead of piling up a new one each time
                st = os.stat(real)
                key = '%s|%d|%d' % (os.path.abspath(real).lower(), st.st_size, int(st.st_mtime))
                out = os.path.join(self.cache_dir, '%08x_%s' % (zlib.crc32(key.encode('utf-8')), os.path.basename(real)))
                if not os.path.isfile(out):
                    with open(out, 'wb') as f:
                        f.write(data)
                real = out
            try:
                img = bpy.data.images.load(real, check_existing=True)
                img.alpha_mode = 'STRAIGHT'
            except RuntimeError:
                img = None
        if img is None:
            self.missing.add(path)
            if path:
                # keep the reference: a placeholder that points at the original file (Blender
                # shows it pink), so the material still exports with its texture
                img = bpy.data.images.new(os.path.basename(path.replace('\\', '/')) or 'missing', 8, 8)
                img.source = 'FILE'
                img.filepath = path
                img['pt_missing'] = True
        self.images[path] = img
        return img


# --------------------------------------------------------------------------- shader graph
STAGE_OPS = {'BS_MODULATE2X:': ('MULTIPLY', 2.0), 'BS_MODULATE4X:': ('MULTIPLY', 4.0),
             'BS_ADD:': ('ADD', 1.0), 'BS_ADDSIGNED:': ('LINEAR_LIGHT', 1.0),
             'BS_ADDSIGNED2X:': ('LINEAR_LIGHT', 1.0), 'BS_SUBTRACT:': ('SUBTRACT', 1.0),
             'BS_MODULATE:': ('MULTIPLY', 1.0)}


def _layer_op(map_name):
    for k, v in STAGE_OPS.items():
        if k in map_name:
            return v
    return ('MULTIPLY', 1.0)


class MaterialBuilder(object):
    def __init__(self, images, mode, use_vcol, prefix, lightmaps=True):
        self.images = images
        self.mode = mode
        self.use_vcol = use_vcol
        self.prefix = prefix
        self.lightmaps = lightmaps
        self.cache = {}

    def get(self, md, uv_names, has_vcol):
        key = (id(md), tuple(uv_names), has_vcol)
        if key in self.cache:
            return self.cache[key]
        mat = self._build(md, uv_names, has_vcol)
        self.cache[key] = mat
        return mat

    def _uv_node(self, nt, uv_names, channel, x, y, mp=None):
        n = nt.nodes.new('ShaderNodeUVMap')
        n.location = (x, y)
        idx = max(0, min(len(uv_names) - 1, channel - 1)) if uv_names else 0
        if uv_names:
            n.uv_map = uv_names[idx]
        out = n.outputs['UV']
        if mp is not None and mp.has_xform():
            # Max UVW transform: tiling+offset, then rotation about the map centre
            m = nt.nodes.new('ShaderNodeMapping')
            m.location = (x + 180, y)
            m.vector_type = 'POINT'
            m.inputs['Location'].default_value = (mp.u_off, mp.v_off, 0.0)
            m.inputs['Rotation'].default_value = (0.0, 0.0, -mp.angle)
            m.inputs['Scale'].default_value = (mp.u_tile, mp.v_tile, 1.0)
            nt.links.new(out, m.inputs['Vector'])
            out = m.outputs['Vector']
        return out

    def _tex(self, nt, path, uv_out, x, y, role='diffuse', mp=None):
        img = self.images.get(path)
        if img is None:
            return None
        t = nt.nodes.new('ShaderNodeTexImage')
        t.location = (x, y)
        t.image = img
        # remembered for the ASE exporter
        t.label = 'PT ' + role
        t['ase_role'] = role
        t['ase_bitmap'] = path
        t['ase_image'] = img.name
        if mp is not None:
            t['ase_map_name'] = mp.name
            t['ase_channel'] = mp.channel
        t.interpolation = 'Linear'
        nt.links.new(uv_out, t.inputs['Vector'])
        return t

    def _mix(self, nt, op, a, b, x, y, fac=1.0):
        m = nt.nodes.new('ShaderNodeMix')
        m.location = (x, y)
        m.data_type = 'RGBA'
        m.blend_type = op
        _sock(m.inputs, 'Factor_Float').default_value = fac
        nt.links.new(a, _sock(m.inputs, 'A_Color'))
        if isinstance(b, (tuple, list)):
            _sock(m.inputs, 'B_Color').default_value = tuple(b) + (1.0,) * (4 - len(b))
        else:
            nt.links.new(b, _sock(m.inputs, 'B_Color'))
        return _sock(m.outputs, 'Result_Color')

    def _build(self, md, uv_names, has_vcol):
        name = '%s%s' % (self.prefix, md.name if md else 'default')
        mat = bpy.data.materials.new(name[:63])
        mat['pt_source'] = md.label if md else ''
        if md is not None:
            mat['ase_name'] = md.name
            mat['ase_diffuse'] = list(md.diffuse)
            mat['ase_transparency'] = md.transparency
            mat['ase_selfillum'] = md.self_illum
            mat['ase_two_sided'] = md.two_sided
            mat['ase_additive'] = md.additive
            if md.opacity_map is not None and md.opacity_map.bitmap:
                mat['ase_opacity_same'] = (md.diffuse_map is not None and
                                           os.path.basename(md.opacity_map.bitmap).lower() ==
                                           os.path.basename(md.diffuse_map.bitmap).lower())
        if md is None:
            mat.diffuse_color = (0.6, 0.6, 0.6, 1)
            return mat
        if hasattr(mat, 'use_nodes'):
            try:
                mat.use_nodes = True
            except Exception:
                pass
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        out.location = (1400, 0)

        color = None
        alpha = None
        tex0 = None
        if md.diffuse_map and md.diffuse_map.bitmap:
            uv = self._uv_node(nt, uv_names, md.diffuse_map.channel, -900, 200, md.diffuse_map)
            tex0 = self._tex(nt, md.diffuse_map.bitmap, uv, -500, 200, 'diffuse', md.diffuse_map)
        if tex0 is not None:
            color = tex0.outputs['Color']
        y = -150
        if self.lightmaps:
            for k, lay in enumerate(md.layers):
                if not lay.bitmap:
                    continue
                uv = self._uv_node(nt, uv_names, lay.channel, -900, y, lay)
                t = self._tex(nt, lay.bitmap, uv, -500, y, 'layer', lay)
                if t is not None and color is not None:
                    op, gain = _layer_op(lay.name)
                    src = t.outputs['Color']
                    if gain != 1.0:
                        src = self._mix(nt, 'MULTIPLY', src, (gain, gain, gain), -250, y)
                    color = self._mix(nt, op, color, src, -100, y + 100)
                y -= 300
        if color is None:
            rgb = nt.nodes.new('ShaderNodeRGB')
            rgb.location = (-500, 200)
            rgb.outputs[0].default_value = tuple(md.diffuse) + (1.0,)
            color = rgb.outputs[0]
        if has_vcol and self.use_vcol:
            vc = nt.nodes.new('ShaderNodeVertexColor')
            vc.location = (-500, -500)
            vc.layer_name = 'Col'
            color = self._mix(nt, 'MULTIPLY', color, vc.outputs['Color'], 100, 0)

        # alpha
        if md.opacity_map and md.opacity_map.bitmap and tex0 is not None:
            same = os.path.basename(md.opacity_map.bitmap).lower() == os.path.basename(md.diffuse_map.bitmap).lower()
            if same:
                alpha = tex0.outputs['Alpha']
            else:
                uv = self._uv_node(nt, uv_names, md.opacity_map.channel, -900, -800, md.opacity_map)
                ot = self._tex(nt, md.opacity_map.bitmap, uv, -500, -800, 'opacity', md.opacity_map)
                if ot is not None:
                    alpha = ot.outputs['Color']        # mask bitmap: luminance = alpha
        elif tex0 is not None and tex0.image is not None and tex0.image.depth == 32:
            alpha = tex0.outputs['Alpha']
        if md.transparency > 0.02:
            mul = nt.nodes.new('ShaderNodeMath')
            mul.operation = 'MULTIPLY'
            mul.location = (300, -400)
            mul.inputs[1].default_value = 1.0 - md.transparency
            if alpha is not None:
                nt.links.new(alpha, mul.inputs[0])
            else:
                mul.inputs[0].default_value = 1.0
            alpha = mul.outputs[0]

        if self.mode == 'GAME':
            em = nt.nodes.new('ShaderNodeEmission')
            em.location = (700, 100)
            nt.links.new(color, em.inputs['Color'])
            em.inputs['Strength'].default_value = 1.0
            shader = em.outputs[0]
        else:
            bs = nt.nodes.new('ShaderNodeBsdfPrincipled')
            bs.location = (650, 100)
            nt.links.new(color, bs.inputs['Base Color'])
            bs.inputs['Roughness'].default_value = 0.9
            if md.self_illum > 0.01:
                nt.links.new(color, bs.inputs['Emission Color'])
                bs.inputs['Emission Strength'].default_value = md.self_illum
            shader = bs.outputs[0]
        if md.additive:
            # PT BLEND_LAMP / ADDCOLOR: dest + src * alpha  (alpha = texture alpha,
            # or brightness for textures without alpha)
            tr = nt.nodes.new('ShaderNodeBsdfTransparent')
            tr.location = (900, 300)
            add = nt.nodes.new('ShaderNodeAddShader')
            add.location = (1150, 100)
            nt.links.new(tr.outputs[0], add.inputs[0])
            nt.links.new(shader, add.inputs[1])
            shader = add.outputs[0]
            if alpha is not None:
                mx = nt.nodes.new('ShaderNodeMixShader')
                mx.location = (1300, 100)
                tr2 = nt.nodes.new('ShaderNodeBsdfTransparent')
                tr2.location = (1150, 300)
                nt.links.new(alpha, mx.inputs[0])
                nt.links.new(tr2.outputs[0], mx.inputs[1])
                nt.links.new(shader, mx.inputs[2])
                shader = mx.outputs[0]
            _render_method(mat, 'BLENDED')
        elif alpha is not None:
            tr = nt.nodes.new('ShaderNodeBsdfTransparent')
            tr.location = (900, 300)
            mx = nt.nodes.new('ShaderNodeMixShader')
            mx.location = (1150, 100)
            nt.links.new(alpha, mx.inputs[0])
            nt.links.new(tr.outputs[0], mx.inputs[1])
            nt.links.new(shader, mx.inputs[2])
            shader = mx.outputs[0]
            _render_method(mat, 'DITHERED')
        nt.links.new(shader, out.inputs['Surface'])
        mat.use_backface_culling = not md.two_sided
        mat.diffuse_color = tuple(md.diffuse) + (1.0,)
        return mat


def _render_method(mat, m):
    if hasattr(mat, 'surface_render_method'):
        try:
            mat.surface_render_method = m
        except TypeError:
            pass


# --------------------------------------------------------------------------- geometry
def _node_tm(node):
    tm = find(node, '*NODE_TM')
    if tm is None:
        return Matrix.Identity(4)
    r0 = _floats(val(tm, '*TM_ROW0', '1 0 0'), 3)
    r1 = _floats(val(tm, '*TM_ROW1', '0 1 0'), 3)
    r2 = _floats(val(tm, '*TM_ROW2', '0 0 1'), 3)
    r3 = _floats(val(tm, '*TM_ROW3', '0 0 0'), 3)
    return Matrix(((r0[0], r1[0], r2[0], r3[0]),
                   (r0[1], r1[1], r2[1], r3[1]),
                   (r0[2], r1[2], r2[2], r3[2]),
                   (0.0, 0.0, 0.0, 1.0)))


def _tm_rows(node):
    tm = find(node, '*NODE_TM')
    if tm is None:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]
    return [_floats(val(tm, '*TM_ROW0', '1 0 0'), 3), _floats(val(tm, '*TM_ROW1', '0 1 0'), 3),
            _floats(val(tm, '*TM_ROW2', '0 0 1'), 3), _floats(val(tm, '*TM_ROW3', '0 0 0'), 3)]


def _det3(r):
    return (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1]) - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
            + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))


def _plain_rows(rows):
    """A pivot Blender can hold exactly.  A flat or broken NODE_TM (some converted monsters
    carried one) becomes an identity pivot; a skewed one (rows not at right angles, e.g. the
    inverse of an 8.8 fixed-point matrix) gets square axes of the same lengths, because an
    object transform has no skew: without this the mesh would sit off its bones.  The
    vertices are world space, so they are simply made local to the pivot used here.
    Even the tiny skew of rows written with 4 decimals matters: a scaled-down object whose
    vertices lie far from its pivot (a long plane in a 2012 map) moved 17 units with it."""
    ident = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    t = rows[3] if all(math.isfinite(x) for x in rows[3]) else [0.0, 0.0, 0.0]
    r = rows[:3]
    if not all(math.isfinite(x) for row in r for x in row) or abs(_det3(r)) < 1e-9:
        return ident + [list(t)]

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    ln = [math.sqrt(dot(row, row)) for row in r]
    u = [[x / ln[i] for x in r[i]] for i in range(3)]
    if max(abs(dot(u[0], u[1])), abs(dot(u[0], u[2])), abs(dot(u[1], u[2]))) < 1e-12:
        return [list(row) for row in r] + [list(t)]
    d = dot(u[1], u[0])
    v1 = [u[1][k] - d * u[0][k] for k in range(3)]
    n1 = math.sqrt(dot(v1, v1))
    v1 = [x / n1 for x in v1]
    v2 = [u[0][1] * v1[2] - u[0][2] * v1[1], u[0][2] * v1[0] - u[0][0] * v1[2], u[0][0] * v1[1] - u[0][1] * v1[0]]
    if dot(v2, u[2]) < 0:
        v2 = [-x for x in v2]
    return [[x * ln[0] for x in u[0]], [x * ln[1] for x in v1], [x * ln[2] for x in v2], list(t)]


def _is_identity3(r):
    ident = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    return all(abs(r[i][j] - ident[i][j]) < 1e-7 for i in range(3) for j in range(3))


def _inv3(r):
    a, b, c = r[0]
    d, e, f = r[1]
    g, h, i = r[2]
    A, B, C = e * i - f * h, -(d * i - f * g), d * h - e * g
    det = a * A + b * B + c * C
    if abs(det) < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
            [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
            [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]]


def _dbl_rows(flat):
    """ob['ase_tm'] (12 floats, ASE rows) -> column-vector 4x4 as nested doubles."""
    f = list(flat)
    return [[f[0], f[3], f[6], f[9]], [f[1], f[4], f[7], f[10]], [f[2], f[5], f[8], f[11]], [0.0, 0.0, 0.0, 1.0]]


def _tm_list(flat):
    """ob['ase_tm'] (12 floats) -> 4 rows."""
    f = list(flat)
    return [f[0:3], f[3:6], f[6:9], f[9:12]]


def _rows_matrix(r):
    return Matrix(((r[0][0], r[1][0], r[2][0], r[3][0]),
                   (r[0][1], r[1][1], r[2][1], r[3][1]),
                   (r[0][2], r[1][2], r[2][2], r[3][2]),
                   (0.0, 0.0, 0.0, 1.0)))


def _read_uv_block(block):
    tl = find(block, '*MESH_TVERTLIST')
    tf = find(block, '*MESH_TFACELIST')
    if tl is None or tf is None or not tl[2] or not tf[2]:
        return None
    tv = [_floats(c[1], 4)[1:3] for c in tl[2]]
    faces = []
    for c in tf[2]:
        p = c[1].split()
        faces.append((int(p[1]), int(p[2]), int(p[3])))
    return tv, faces


def build_mesh_steps(node, name, mats, mref, mb, opts, raw_pivot=False):
    """Generator: yields progress 0..1 while building; returns the object (or None)."""
    m = find(node, '*MESH')
    if m is None:
        return None
    vl = find(m, '*MESH_VERTEX_LIST')
    fl = find(m, '*MESH_FACE_LIST')
    verts = [_floats(c[1], 4)[1:4] for c in (vl[2] or [])] if vl else []
    faces, mtl = [], []
    for c in (fl[2] or []) if fl else []:
        s = c[1]
        try:
            a = int(s.split('A:')[1].split()[0])
            b = int(s.split('B:')[1].split()[0])
            cc = int(s.split('C:')[1].split()[0])
        except (IndexError, ValueError):
            continue
        k = s.find('*MESH_MTLID')
        mid = int(s[k + 11:].split()[0]) if k >= 0 else 0
        faces.append((a, b, cc))
        mtl.append(mid)
    if not verts or not faces:
        return None
    # Blender can't hold two faces on the same three vertices, but PT models use them on purpose
    # (back faces of two-sided capes, overlays drawn twice with another material): such a face
    # gets its own copies of the vertices, which keep their bone (ase_dup_src).
    used = set()
    dup_src = []
    for i, f in enumerate(faces):
        if len(set(f)) < 3:
            continue                                  # zero-area face: invisible, Blender drops it
        key = frozenset(f)
        if key in used:
            nf = []
            for v in f:
                dup_src.append((len(verts), v))
                nf.append(len(verts))
                verts.append(verts[v])
            faces[i] = tuple(nf)
        else:
            used.add(key)
    yield 0.25

    # Transforms are done in Python doubles: Blender stores coordinates as 32-bit floats, which
    # only resolve ~0.008 units at PT map coordinates (~100000).  Vertices are kept small
    # (relative to the pivot) and the exact pivot is remembered for the exporter.
    raw = _tm_rows(node)
    if raw_pivot and all(math.isfinite(x) for row in raw for x in row) and abs(_det3(raw)) > 1e-9:
        # an animated object (or a parent of one): its keys turn it about its own NODE_TM, so
        # the mesh must stay relative to exactly that pivot (a skew is absorbed by the mesh; a
        # mirror becomes a negative object scale, as 3ds Max keeps it next to the rotation keys)
        rows = [list(r) for r in raw]
    else:
        raw_pivot = False
        rows = _plain_rows(raw)
    if _det3(rows) < 0 and not raw_pivot:
        # Mirrored pivot: ASE vertices are world space and their winding is what the
        # game draws.  Re-applying a negative-scale matrix would flip the faces, so
        # keep world-space vertices with an identity pivot instead.
        rows = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]
    if _is_identity3(rows) and not raw_pivot:
        # no rotation: put the pivot at the (rounded) centre so coordinates stay small
        lo = [min(v[i] for v in verts) for i in range(3)]
        hi = [max(v[i] for v in verts) for i in range(3)]
        rows[3] = [float(round((lo[i] + hi[i]) * 0.5)) for i in range(3)]
    inv = _inv3(rows)
    t = rows[3]
    verts = [((v[0] - t[0]) * inv[0][0] + (v[1] - t[1]) * inv[1][0] + (v[2] - t[2]) * inv[2][0],
              (v[0] - t[0]) * inv[0][1] + (v[1] - t[1]) * inv[1][1] + (v[2] - t[2]) * inv[2][1],
              (v[0] - t[0]) * inv[0][2] + (v[1] - t[1]) * inv[1][2] + (v[2] - t[2]) * inv[2][2])
             for v in verts]
    world = _rows_matrix(rows)

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    yield 0.4

    # UV channels: main list = channel 1, MESH_MAPPINGCHANNEL n = channel n
    chans = {}
    main = _read_uv_block(m)
    if main:
        chans[1] = main
    for mc in find_all(m, '*MESH_MAPPINGCHANNEL'):
        try:
            n = int(mc[1].split()[0])
        except (ValueError, IndexError):
            continue
        blk = _read_uv_block(mc)
        if blk and n > 0:
            chans[n] = blk
    uv_names = []
    nf = len(faces)
    for n in range(1, (max(chans) if chans else 0) + 1):
        lname = 'UVMap' if n == 1 else 'UVChannel_%d' % n
        uv_names.append(lname)
        layer = me.uv_layers.new(name=lname)
        blk = chans.get(n)
        flat = [0.0] * (nf * 6)
        if blk:
            tv, tf = blk
            ntv = len(tv)
            for i in range(min(nf, len(tf))):
                for j in range(3):
                    t = tf[i][j]
                    if 0 <= t < ntv:
                        flat[i * 6 + j * 2] = tv[t][0]
                        flat[i * 6 + j * 2 + 1] = tv[t][1]
        layer.data.foreach_set('uv', flat)
        yield 0.4 + 0.3 * n / max(chans)

    # vertex colours (per corner)
    has_vcol = False
    cl = find(m, '*MESH_CVERTLIST')
    cf = find(m, '*MESH_CFACELIST')
    if opts.vertex_colors and cl and cf and cl[2] and cf[2]:
        cv = [_floats(c[1], 4)[1:4] for c in cl[2]]
        cols = [1.0] * (nf * 12)
        ncv = len(cv)
        for i, c in enumerate(cf[2][:nf]):
            p = c[1].split()
            for j in range(3):
                t = int(p[1 + j])
                if 0 <= t < ncv:
                    o = i * 12 + j * 4
                    cols[o:o + 3] = cv[t]
        attr = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
        attr.data.foreach_set('color', cols)
        has_vcol = True

    yield 0.8
    # materials
    used = sorted(set(mtl))
    slot_of = {}
    collision_faces = 0
    for mid in used:
        md = mats[mref].resolve(mid) if 0 <= mref < len(mats) else None
        if md is not None and md.collision:
            collision_faces += mtl.count(mid)
        mat = mb.get(md, uv_names, has_vcol)
        slot_of[mid] = len(me.materials)
        me.materials.append(mat)
    me.polygons.foreach_set('material_index', [slot_of[i] for i in mtl])
    if opts.smooth:
        me.shade_smooth()
    me.validate(clean_customdata=False)
    me.update()

    ob = bpy.data.objects.new(name, me)
    ob['ase_world'] = [v for row in world for v in row]
    if dup_src:
        ob['ase_dup_src'] = [x for pair in dup_src for x in pair]   # (copy, original) vertex pairs
    ob['ase_tm'] = [c for r in rows for c in r]          # exact pivot, game units (doubles)
    ob['pt_collision_faces'] = collision_faces
    ob['pt_is_collision'] = bool(collision_faces) and collision_faces == nf
    return ob


def build_mesh_object(node, name, mats, mref, mb, opts, imp=None):
    return _drain(build_mesh_steps(node, name, mats, mref, mb, opts))


def _drain(gen):
    """Run a step generator to completion and return its result."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def build_light(node, name):
    s = find(node, '*LIGHT_SETTINGS')
    col = _floats(val(s, '*LIGHT_COLOR', '1 1 1'), 3) if s else [1, 1, 1]
    rng = _floats(val(s, '*LIGHT_ATTNEND', '200'), 1)[0] if s else 200.0
    ld = bpy.data.lights.new(name, 'POINT')
    ld.color = col
    ld.energy = max(1.0, rng) * 50.0
    ld.shadow_soft_size = 1.0
    ob = bpy.data.objects.new(name, ld)
    ob['ase_world'] = [v for row in _node_tm(node) for v in row]
    return ob


# --------------------------------------------------------------------------- entry point
class ImportOptions(object):
    def __init__(self, **kw):
        self.scale = 0.01
        self.mode = 'GAME'
        self.vertex_colors = True
        self.lightmaps = True
        self.smooth = True
        self.hide_collision = True
        self.import_lights = False
        self.armature = True          # characters/monsters: bones -> Armature + skinning
        self.animation = True         # False = T-pose (bind pose); True = load the animation
        self.animation_file = ''      # optional *_motions.ase to animate with
        self.texture_dirs = []
        self.cache_dir = os.path.join(tempfile.gettempdir(), 'pt_texture_cache')
        for k, v in kw.items():
            setattr(self, k, v)


def import_ase_steps(context, filepath, opts=None, collection_name=None):
    """Generator: yields (fraction 0..1, label) while importing; returns a result dict.
    Lets the UI redraw a progress bar between steps."""
    opts = opts or ImportOptions()
    t0 = time.time()
    base = collection_name or os.path.splitext(os.path.basename(filepath))[0]
    yield 0.0, 'Reading %s' % os.path.basename(filepath)
    root = parse_ase(filepath)
    yield 0.12, 'Reading materials'

    ml = find(root, '*MATERIAL_LIST')
    mats = [MatDef(m, '%s:%d' % (base, i)) for i, m in enumerate(find_all(ml, '*MATERIAL'))] if ml else []
    images = ImageCache(os.path.dirname(os.path.abspath(filepath)), opts.texture_dirs, opts.cache_dir)
    mb = MaterialBuilder(images, opts.mode, opts.vertex_colors, base + ':', opts.lightmaps)

    coll = bpy.data.collections.new(base)
    context.scene.collection.children.link(coll)
    coll_hidden = None

    root_empty = bpy.data.objects.new(base + '_root', None)
    root_empty['pt_ase_root'] = True
    root_empty.empty_display_size = 100
    root_empty.scale = (opts.scale,) * 3
    coll.objects.link(root_empty)

    nodes = _walk_geoms(root, [])
    char = opts.armature and ase_anim.is_character(root)
    # map props with their own animation (windmills, doors): rigid object keys, no skeleton
    rigid_anim = not ase_anim.is_character(root) and any(find(n, '*TM_ANIMATION') is not None
                                                          for n in _walk_geoms(root, []))
    bones = ase_anim.bone_nodes(root) if char else []
    bone_names = {unquote(val(b, '*NODE_NAME', '')) for b in bones}
    # objects with their own keys (map props; rigid parts of a character riding on a bone, Deius'
    # Circle001) and their parents (bones aside) keep their exact NODE_TM pivot (the keys turn about it)
    raw_names = set()
    parent_of = {unquote(val(n, '*NODE_NAME', '')): unquote(val(n, '*NODE_PARENT', '')) for n in nodes}
    for n in nodes:
        nm = unquote(val(n, '*NODE_NAME', ''))
        if find(n, '*TM_ANIMATION') is None or nm in bone_names or ase_anim.physique(n):
            continue
        while nm and nm not in raw_names and nm not in bone_names:
            raw_names.add(nm)
            nm = parent_of.get(nm, '')
    if bone_names:
        nodes = [n for n in nodes if unquote(val(n, '*NODE_NAME', '')) not in bone_names]
    # share the bar between objects by face count (one big terrain mesh dominates)
    weights = []
    for node in nodes:
        msh = find(node, '*MESH')
        weights.append(max(1, int(_floats(val(msh, '*MESH_NUMFACES', '1'), 1)[0])) if msh else 1)
    wsum = float(sum(weights)) or 1.0
    acc = 0.0

    by_name = {}
    created = []
    node_of = {}
    missing_anim = ''
    for node, w in zip(nodes, weights):
        lo = 0.15 + 0.8 * acc / wsum
        acc += w
        hi = 0.15 + 0.8 * acc / wsum
        name = unquote(val(node, '*NODE_NAME', 'Object'))
        if node[0] == '*GEOMOBJECT':
            mref = int(_floats(val(node, '*MATERIAL_REF', '-1'), 1)[0])
            gen = build_mesh_steps(node, name, mats, mref, mb, opts, raw_pivot=name in raw_names)
            ob = None
            try:
                while True:
                    f = next(gen)
                    yield lo + (hi - lo) * f, 'Building %s' % name
            except StopIteration as e:
                ob = e.value
        elif node[0] == '*LIGHTOBJECT':
            if not opts.import_lights:
                continue
            ob = build_light(node, name)
        else:
            continue
        if ob is None:
            continue
        is_coll = name.endswith('__collision') or ob.get('pt_is_collision', False)
        if is_coll and opts.hide_collision:
            if coll_hidden is None:
                coll_hidden = bpy.data.collections.new(base + '_collision')
                coll.children.link(coll_hidden)
                coll_hidden.hide_render = True
                coll_hidden.hide_viewport = True
            coll_hidden.objects.link(ob)
        else:
            coll.objects.link(ob)
        # the ASE name and position, so duplicate names (several meshes called "lizardfolk")
        # stay apart: Blender renames the copies (.001 ...), the exporter writes the ASE name back
        ob['ase_name'] = name
        ob['ase_import_name'] = ob.name             # what Blender called it (an empty ASE name too)
        ob['ase_index'] = len(created)
        ob['ase_node_parent'] = unquote(val(node, '*NODE_PARENT', ''))
        by_name.setdefault(name, ob)
        created.append((ob, unquote(val(node, '*NODE_PARENT', ''))))
        node_of[ob.name] = node
        yield hi, 'Building %s' % name

    # skeleton: Armature + skinning (characters / monsters)
    arm_ob = None
    skinned = {}
    anim_info = None
    tracks, motions, bind_override = {}, [], {}
    if bones and opts.animation:
        anim_info = ase_anim.pt_animation(root)
        tracks = ase_anim.tracks_from(root)
        motions = anim_info[2] if anim_info else []
        # A file's own keys count only when they move most of the skeleton: original costume
        # files sometimes carry a stray few-frame test animation on their hair/tail bones.
        own_ok = len(tracks) >= 0.5 * len(bones)
        if opts.animation_file or not own_ok:
            # 1) the file picked in the import options, 2) the shared file a converted
            # character names, 3) the class file from the name (TfbF01 -> m8_motions.ase)
            ap, wanted = ase_anim.animation_source(filepath, anim_info, opts.animation_file, opts.texture_dirs)
            if ap:
                yield 0.93, 'Reading animation %s' % os.path.basename(ap)
                aroot = parse_ase(ap)
                tracks = ase_anim.tracks_from(aroot)
                ai = ase_anim.pt_animation(aroot)
                if ai and ai[2]:
                    motions = ai[2]
                # The game skins a character on its class skeleton, not on the bones saved in
                # the character's own file (costume files often have older, slightly different
                # bones), so the rest pose comes from the animation file too.
                bind_override = ase_anim.bind_from(aroot)
            else:
                missing_anim = wanted
    if bones:
        yield 0.95, 'Building skeleton'
        arm_ob, bind, bone_parent = ase_anim.build_armature(context, coll, base + '_rig', bones, root_empty,
                                                            bind_override)
        # where the keys came from: the exporter writes a file's own animation back (monsters),
        # but not a shared class animation (player armour gets it from the game's class .smb)
        arm_ob['pt_anim_source'] = ('shared' if bind_override else 'own') if tracks else ''
        if tracks and ase_anim.separate_motion_file(root):
            arm_ob['pt_anim_source'] = 'shared'     # the game keeps it in its own motion file
        # animated: skinned vertices carry the difference between the written bind pose and
        # Blender's rigid rest pose, so the animation is exactly the game's (ase_anim.bind_maps)
        maps = ase_anim.bind_maps(bind, ase_anim.raw_worlds(arm_ob)) if tracks else {}
        for ob, _p in created:                     # each mesh with its own node's skin
            node = node_of.get(ob.name)
            ph = ase_anim.physique(node) if node is not None else None
            if ph and ob.type == 'MESH':
                full = ase_anim.skin_mesh(ob, arm_ob, ph)
                skinned[ob.name] = True
                if maps and ase_anim.apply_bind_maps(ob, full, maps, _dbl_rows(ob['ase_tm'])):
                    ob['pt_bind_fixed'] = True
            elif ph is not None and ob.type == 'MESH':
                ob['pt_physique_empty'] = True      # an empty *PHYSIQUE: a rigid part, kept on export

    # hierarchy (ASE TMs are world space; keep world placement)
    def wmat(o):
        f = list(o['ase_world'])
        return Matrix((f[0:4], f[4:8], f[8:12], f[12:16]))
    bone_kids = []
    for ob, parent in created:
        if arm_ob is not None and (ob.name in skinned or parent in bone_names):
            w = wmat(ob)
            ob.parent = arm_ob
            ob.matrix_parent_inverse = Matrix.Identity(4)
            ob.matrix_basis = w
            if parent in bone_names and ob.name not in skinned:
                bone_kids.append((ob, parent, w))
            ob['ase_basis'] = [v for row in ob.matrix_basis for v in row]
            ob['ase_parent'] = arm_ob.name
            continue
        par = by_name.get(parent) if parent else None
        w = wmat(ob)
        ob.parent = par or root_empty
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.matrix_basis = w if par is None else wmat(par).inverted_safe() @ w
        ob['ase_basis'] = [v for row in ob.matrix_basis for v in row]
        ob['ase_parent'] = ob.parent.name if ob.parent else ''
    for ob, _parent in created:              # only now: a child may come after its parent
        if 'ase_world' in ob:
            del ob['ase_world']
    context.view_layer.update()
    # rigid parts that ride on a bone (weapons, armour pieces): bone parenting
    for ob, bone, w in bone_kids:
        ob.parent_type = 'BONE'
        ob.parent_bone = bone
        context.view_layer.update()
        ob.matrix_world = arm_ob.matrix_world @ w
    if arm_ob is not None:
        if tracks:
            gen = ase_anim.build_action_steps(arm_ob, bind, bone_parent, tracks, base + '_motions')
            try:
                while True:
                    f = next(gen)
                    yield 0.96 + 0.04 * f, 'Animating bones'
            except StopIteration as e:
                action = e.value
            ase_anim.set_motions(context, arm_ob, motions, action.get('pt_last_frame', 1.0))
        elif motions:
            ase_anim.set_motions(context, arm_ob, motions, max(m[2] for m in motions))
        if tracks:
            # rigid parts with their own keys, relative to their bone: Blender hangs a child on
            # the bone's tail in Blender bone axes, so the parent inverse undoes those two
            axes = ase_anim.bone_axes(arm_ob)
            raw_w = ase_anim.raw_worlds(arm_ob)
            for ob, bone, _w in bone_kids:
                node = node_of.get(ob.name)
                if node is None or find(node, '*TM_ANIMATION') is None or bone not in arm_ob.data.bones:
                    continue
                tr = ase_anim.Track(node)
                if not tr.ticks():
                    continue
                b = arm_ob.data.bones[bone]
                ob.matrix_parent_inverse = Matrix.Translation((0.0, b.length, 0.0)).inverted() @ axes[bone].inverted()
                P = raw_w.get(bone, bind.get(bone))
                W = _rows_matrix(_tm_list(ob['ase_tm']))
                rest_local = (P.inverted_safe() @ W) if P is not None else W
                ase_anim.build_object_action(ob, tr, rest_local, '%s_%s' % (base, ob.name))
                ob['ase_anim'] = True
            # ... and those hanging on another such part (FlameMaiden's bip01 Bone004): as map props
            kids = {o.name for o, _b, _w in bone_kids}
            for ob, parent in created:
                node = node_of.get(ob.name)
                par = by_name.get(parent) if parent else None
                if (ob.name in kids or ob.name in skinned or par is None or node is None
                        or find(node, '*TM_ANIMATION') is None):
                    continue
                tr = ase_anim.Track(node)
                if not tr.ticks():
                    continue
                W = _rows_matrix(_tm_list(ob['ase_tm']))
                rest_local = _rows_matrix(_tm_list(par['ase_tm'])).inverted_safe() @ W
                ase_anim.build_object_action(ob, tr, rest_local, '%s_%s' % (base, ob.name))
                ob['ase_anim'] = True
        context.view_layer.update()
    elif rigid_anim:
        # map props with their own keys: object animation, relative to the parent object
        last = 0.0
        for k, (ob, parent) in enumerate(created):
            node = node_of.get(ob.name)
            if node is None or find(node, '*TM_ANIMATION') is None:
                continue
            tr = ase_anim.Track(node)
            if not tr.ticks():
                continue
            W = _rows_matrix(_tm_list(ob['ase_tm']))
            par = by_name.get(parent) if parent else None
            rest_local = (_rows_matrix(_tm_list(par['ase_tm'])).inverted_safe() @ W) if par is not None else W
            act = ase_anim.build_object_action(ob, tr, rest_local, '%s_%s' % (base, ob.name))
            ob['ase_anim'] = True
            last = max(last, act.get('pt_last_frame', 0.0))
            yield 0.96 + 0.04 * (k + 1) / len(created), 'Animating %s' % ob.name
        if last > 0:
            sc = context.scene
            sc.frame_start = 0
            sc.frame_end = max(sc.frame_end if sc.frame_end > 250 else 0, int(math.ceil(last)))
        context.view_layer.update()
    yield 1.0, 'Done'
    hidden = set(coll_hidden.objects.keys()) if coll_hidden else set()
    visible = [ob for ob, _p in created if ob.name not in hidden]
    if arm_ob is not None:
        visible.append(arm_ob)
    return dict(objects=len(created), materials=len(mb.cache), missing=sorted(images.missing),
                seconds=time.time() - t0, collection=coll, visible=visible,
                bones=len(bone_names), armature=arm_ob, missing_animation=missing_anim)


def import_ase(context, filepath, opts=None, collection_name=None):
    """Blocking import (scripts / batch use)."""
    return _drain(import_ase_steps(context, filepath, opts, collection_name))


# --------------------------------------------------------------------------- viewport helpers
def frame_objects(context, objects, material_preview=True):
    """Select the objects and frame them in every 3D viewport of the current screen."""
    objects = [o for o in objects if o and o.name in context.view_layer.objects]
    if not objects:
        return False
    for o in context.view_layer.objects:
        if o.select_get():
            o.select_set(False)
    for o in objects:
        try:
            o.select_set(True)
        except RuntimeError:
            pass
    context.view_layer.objects.active = objects[0]
    mn = [1e30] * 3
    mx = [-1e30] * 3
    for o in objects:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                mn[i] = min(mn[i], w[i])
                mx[i] = max(mx[i], w[i])
    size = max(mx[i] - mn[i] for i in range(3))
    window = context.window
    screen = window.screen if window else None
    if screen is None:
        return False
    framed = False
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        # big maps would otherwise be cut off by the default clip range
        space.clip_end = max(space.clip_end, size * 20.0)
        if material_preview and space.shading.type in ('SOLID', 'WIREFRAME'):
            space.shading.type = 'MATERIAL'
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        framed = True
    return framed
