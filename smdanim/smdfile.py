"""Reader for Priston Tale SMD / SMB binary files.

Supports
  * "SMD Stage data Ver 0.72"  - field/terrain meshes (one merged mesh per map)
  * "SMD Model data Ver 0.62"  - objects (animated map props, characters) and
                                 .smb bone files (same container format)

Both the 2012-era files and the current KPT client files share this layout;
the only differences are uninitialised padding bytes and the trailing
collision-grid section (which we do not need).  Nothing here is encrypted.

All numbers verified against the original 3ds Max ASE exports that were used
to build the SMD files (see verify_against_ase.py).

Coordinate conventions
  * Stage vertices are stored as int(x*256), int(z*256), int(y*256) of the
    3ds Max world position (Y and Z swapped: the game is Y-up).
  * Model vertices are stored in the object's local space (Max axes, x256)
    and must be multiplied back by the inverse of the stored TmInvert matrix.
"""

import os
import struct

STAGE_HEADER = b'SMD Stage data Ver 0.72'
MODEL_HEADER = b'SMD Model data Ver 0.62'

FILE_HEADER_SIZE = 0x22C          # smDFILE_HEADER
MATGROUP_HEADER_SIZE = 88         # smMATERIAL_GROUP
MATERIAL_SIZE = 320               # smMATERIAL

# --- stage (smSTAGE3D) absolute offsets -------------------------------------------
ST_TEXLINK_PTR = 0x4024C          # original memory address of TexLink array
ST_NVERTEX = 0x40260
ST_NFACE = 0x40264
ST_NTEXLINK = 0x40268
ST_NLIGHT = 0x4026C
ST_CONTRAST = 0x40274
ST_BRIGHT = 0x40278
ST_VECTLIGHT = 0x4027C            # 3 ints
ST_MATGROUP = 0x402A0             # smMATERIAL_GROUP header (88 bytes)
ST_MATCOUNT = 0x402A8

# --- model object (smOBJ3D) relative offsets ---------------------------------------
OBJ_SIZE = 2236
OB_TEXLINK_PTR = 12
OB_PHYSIQUE = 16
OB_NFACE = 80
OB_NVERTEX = 84
OB_NTEXLINK = 92
OB_NAME = 172
OB_PARENT = 204
OB_TM = 240                       # smMATRIX (int, 8.8 fixed) world transform
OB_TMINV = 304                    # smMATRIX (int) inverse world transform
OB_QUAT = 628                     # float qx,qy,qz,qw   (local, relative to parent)
OB_SCALE = 644                    # int sx,sy,sz (8.8)
OB_POS = 656                      # int px,py,pz (8.8)
OB_NROT = 684
OB_NPOS = 688
OB_NSCALE = 692

# --- PT material keyword tables (from the game's ASE loader) ----------------------
USE_STATE_NAMES = [
    (0x1, 'wind:'), (0x2, 'anim2:'), (0x4, 'anim4:'), (0x8, 'anim8:'), (0x10, 'anim16:'),
    (0x20, 'wind_z1:'), (0x40, 'wind_z2:'), (0x80, 'wind_x1:'), (0x100, 'wind_x2:'),
    (0x200, 'water:'), (0x400, 'wall:'), (0x800, 'pass:'), (0x1000, 'notpass:'),
    (0x2000, 'render_latter:'), (0x4000, 'BLINK_COLOR:'), (0x8000, 'ice:'),
    (0x10000, 'orgwater:'),
]
BLEND_NAMES = {2: 'BLEND_COLOR:', 3: 'BLEND_SHADOW:', 4: 'BLEND_LAMP:', 5: 'BLEND_ADDCOLOR:'}
BLEND_TYPE_NAMES = {0: 'none', 1: 'alpha', 2: 'color', 3: 'shadow', 4: 'lamp', 5: 'addcolor'}
STAGE_STATE_NAMES = {4: 'BS_MODULATE:', 5: 'BS_MODULATE2X:', 6: 'BS_MODULATE4X:', 7: 'BS_ADD:',
                     8: 'BS_ADDSIGNED:', 9: 'BS_ADDSIGNED2X:', 10: 'BS_SUBTRACT:'}
FORM_STATE_NAMES = ['FS_NONE:', 'FS_FORMX:', 'FS_FORMY:', 'FS_FORMZ:', 'FS_SCROLL:', 'FS_REFLEX:',
                    'FS_SCROLL2:', 'FS_SCROLL3:', 'FS_SCROLL4:', 'FS_SCROLL5:', 'FS_SCROLL6:',
                    'FS_SCROLL7:', 'FS_SCROLL8:', 'FS_SCROLL9:', 'FS_SCROLL10:',
                    'FS_SCROLLSLOW1:', 'FS_SCROLLSLOW2:', 'FS_SCROLLSLOW3:', 'FS_SCROLLSLOW4:']
LIGHT_FLAG_NAMES = [(0x1, 'night:'), (0x2, 'lens:'), (0x8, 'obj:')]


class SMDError(Exception):
    pass


def _cstr(b):
    return b.split(b'\0', 1)[0].decode('latin-1')


def _valid_tex_name(s):
    if not s or '.' not in s:
        return False
    return all(32 <= ord(ch) < 127 for ch in s)


def _clean_pair(names, k):
    """Texture (Name, NameA) with PT's quirks removed.

    PT marks "alpha comes from Name itself" by overwriting NameA[0] with 0x01,
    leaving stale bytes behind ('\\x01ield\\forest\\x.tga').  Garbage
    fragments (uninitialised buffer tails) are dropped."""
    n = names[k] if k < len(names) else ''
    na = names[k + 1] if k + 1 < len(names) else ''
    self_alpha = bool(na) and na[0] == '\x01'
    if self_alpha:
        na = ''
    if not _valid_tex_name(n):
        n = ''
    if not _valid_tex_name(na):
        na = ''
    return n, na, self_alpha


class Material(object):
    """One smMATERIAL entry."""

    def __init__(self, index, raw, strings):
        self.index = index
        i = struct.unpack_from('<80i', raw)
        f = struct.unpack_from('<80f', raw)
        self.raw = raw
        self.in_use = i[0]                      # 0 = unused slot, otherwise use count + 1
        self.tex_count = i[1]
        self.stage_state = list(i[10:18])       # per texture layer blend op (BS_*)
        self.form_state = list(i[18:26])        # per texture layer UV animation (FS_*)
        self.reform = i[26]
        self.map_opacity = i[27]
        self.texture_type = i[28]               # 0 = multi-mix, 1 = animated sequence
        self.blend_type = i[29]
        self.shade = i[30]
        self.two_sided = i[31]
        self.serial = i[32]
        self.diffuse = (f[33], f[34], f[35])
        self.transparency = f[36]
        self.self_illum = f[37]
        self.texture_swap = i[38]
        self.mat_frame = i[39]
        self.texture_clip = i[40]
        self.use_state = i[41]
        self.mesh_state = i[42]
        self.wind_bottom = i[43]
        self.anim_count = i[76]
        self.anim_frame_mask = i[77]
        self.anim_speed_shift = i[78]
        self.anim_frame = i[79]
        # texture names: (Name, NameA) pairs for each layer, then for each anim frame
        parts = strings.split(b'\0') if strings else []
        names = [p.decode('latin-1') for p in parts]
        self.textures = []
        self.anim_textures = []
        self.alpha_from_self = []       # per layer: NameA flagged 0x01 (alpha channel of Name itself)
        k = 0
        for _ in range(self.tex_count):
            n, na, selfa = _clean_pair(names, k)
            self.textures.append((n, na))
            self.alpha_from_self.append(selfa)
            k += 2
        for _ in range(self.anim_count):
            n, na, _s = _clean_pair(names, k)
            self.anim_textures.append((n, na))
            k += 2

    # ---- derived helpers ----
    @property
    def flags(self):
        return [n for bit, n in USE_STATE_NAMES if self.use_state & bit]

    @property
    def is_collision(self):
        """Invisible-in-game geometry: 'wall:' collision walls (often carrying a
        checkerboard placeholder texture) and untextured helper faces.
        ('pass:'/'notpass:' only change walkability and are rendered.)"""
        return bool(self.use_state & 0x400) or (self.tex_count == 0 and self.anim_count == 0)

    def anim_pattern(self):
        """'flame0.tga'..'flame7.tga' -> 'flame%d.tga' (PT 'animN:' naming)."""
        if not self.anim_textures:
            return ''
        names = [os.path.basename(n.replace('\\', '/')) for n, _ in self.anim_textures]
        first = names[0]
        if len(names) == 1:
            return first
        pre = os.path.commonprefix(names)
        suf = os.path.commonprefix([n[::-1] for n in names])[::-1]
        # trim digits that belong to the frame number out of prefix/suffix
        while pre and pre[-1].isdigit():
            pre = pre[:-1]
        while suf and suf[0].isdigit():
            suf = suf[1:]
        return pre + '%d' + suf

    def pt_name(self):
        """Reconstruct a material name carrying PT's keyword flags."""
        s = ''.join(self.flags)
        s += BLEND_NAMES.get(self.blend_type, '')
        if self.texture_type == 1 and self.anim_count:
            s = 'anim%d:%s:%d' % (self.anim_count, self.anim_pattern(), self.anim_speed_shift) + \
                (':' + s if s else '')
        return s

    def layer_map_name(self, layer):
        s = STAGE_STATE_NAMES.get(self.stage_state[layer], '')
        fs = self.form_state[layer]
        if 0 < fs < len(FORM_STATE_NAMES):
            s += FORM_STATE_NAMES[fs]
        return s


class Light(object):
    def __init__(self, raw):
        t, x, y, z, rng = struct.unpack_from('<5i', raw)
        r, g, b, a = struct.unpack_from('<4h', raw, 20)
        self.type = t
        self.pos = (x / 256.0, z / 256.0, y / 256.0)       # back to Max axes
        self.range = rng / 256.0
        self.color = (r, g, b)

    def name(self):
        s = ''.join(n for bit, n in LIGHT_FLAG_NAMES if self.type & bit)
        return s or 'dynamic:'


def _read_materials(b, off, count):
    mats = []
    for m in range(count):
        if off + MATERIAL_SIZE > len(b):
            raise SMDError('material table truncated at #%d' % m)
        raw = b[off:off + MATERIAL_SIZE]
        in_use = struct.unpack_from('<i', b, off)[0]
        off += MATERIAL_SIZE
        strings = b''
        if in_use:
            sz = struct.unpack_from('<i', b, off)[0]
            off += 4
            strings = b[off:off + sz]
            off += sz
        mats.append(Material(m, raw, strings))
    return mats, off


class TexLayerFace(object):
    __slots__ = ('u', 'v')


def _walk_texlinks(texlinks, base_ptr, ptr, max_layers=8):
    """Follow a face's TexLink chain. Returns list of (u0,u1,u2,v0,v1,v2)."""
    out = []
    n = len(texlinks)
    while ptr and len(out) < max_layers:
        idx = (ptr - base_ptr) // 32
        if idx < 0 or idx >= n or (ptr - base_ptr) % 32:
            break
        t = texlinks[idx]
        out.append(t[:6])
        ptr = t[7]
    return out


class Stage(object):
    """A parsed 'SMD Stage data' file.  Geometry is returned in 3ds Max axes."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as fh:
            b = fh.read()
        if not b.startswith(STAGE_HEADER):
            raise SMDError('%s: not a stage SMD' % path)
        I = lambda o: struct.unpack_from('<i', b, o)[0]
        self.n_vertex = I(ST_NVERTEX)
        self.n_face = I(ST_NFACE)
        self.n_texlink = I(ST_NTEXLINK)
        self.n_light = I(ST_NLIGHT)
        self.contrast = I(ST_CONTRAST)
        self.bright = I(ST_BRIGHT)
        self.light_vector = struct.unpack_from('<3i', b, ST_VECTLIGHT)
        n_mat = I(ST_MATCOUNT)
        self.materials, off = _read_materials(b, ST_MATGROUP + MATGROUP_HEADER_SIZE, n_mat)

        need = off + self.n_vertex * 28 + self.n_face * 28 + self.n_texlink * 32 + self.n_light * 28
        if need > len(b):
            raise SMDError('%s: file truncated (need %d, have %d)' % (path, need, len(b)))

        # vertices: DWORD sum, ptr, int x, y, z, short color[4]
        self.positions = []
        self.colors = []
        for (_s, _p, x, y, z, r, g, bl, a) in struct.iter_unpack('<IIiiihhhh', b[off:off + self.n_vertex * 28]):
            self.positions.append((x / 256.0, z / 256.0, y / 256.0))
            self.colors.append((r, g, bl, a))
        off += self.n_vertex * 28

        # faces: DWORD sum, calcsum, WORD v[4] (v0,v1,v2,matid), TexLink*, short normal[4]
        raw_faces = list(struct.iter_unpack('<IIHHHHIhhhh', b[off:off + self.n_face * 28]))
        off += self.n_face * 28
        texlinks = list(struct.iter_unpack('<6fII', b[off:off + self.n_texlink * 32]))
        off += self.n_texlink * 32
        base = I(ST_TEXLINK_PTR) & 0xFFFFFFFF

        self.faces = []        # (a, b, c, mat)
        self.face_uvs = []     # per face: list of layers (u0,u1,u2,v0,v1,v2) in SMD convention
        self.normals = []
        for (_s, _c, v0, v1, v2, mat, tl, nx, ny, nz, _nw) in raw_faces:
            self.faces.append((v0, v1, v2, mat))
            self.face_uvs.append(_walk_texlinks(texlinks, base, tl))
            self.normals.append((nx / 32767.0, nz / 32767.0, ny / 32767.0))

        self.lights = []
        for k in range(self.n_light):
            self.lights.append(Light(b[off:off + 28]))
            off += 28
        self.data_end = off

    def max_layers(self):
        return max([len(l) for l in self.face_uvs] or [0])


class ModelObject(object):
    pass


class Model(object):
    """A parsed 'SMD Model data' file (.smd object / .smb bones)."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as fh:
            b = fh.read()
        if not b.startswith(MODEL_HEADER):
            raise SMDError('%s: not a model SMD' % path)
        I = lambda o: struct.unpack_from('<i', b, o)[0]
        n_obj, n_mat = I(0x18), I(0x1C)
        if n_obj < 0 or n_obj > 10000 or n_mat < 0 or n_mat > 100000:
            raise SMDError('%s: bad header counts' % path)
        self.frame_counter = I(0x28)
        off = FILE_HEADER_SIZE
        self.info = []
        for k in range(n_obj):
            self.info.append((_cstr(b[off:off + 32]), I(off + 32), I(off + 36)))
            off += 40
        self.materials = []
        if n_mat > 0:
            self.materials, off = _read_materials(b, off + MATGROUP_HEADER_SIZE, n_mat)
        self.objects = []
        for k in range(n_obj):
            if b[off:off + 3] != b'DCB':
                raise SMDError('%s: object %d header invalid' % (path, k))
            o = ModelObject()
            o.name = _cstr(b[off + OB_NAME:off + OB_NAME + 32])
            o.parent = _cstr(b[off + OB_PARENT:off + OB_PARENT + 32])
            nV, nF, nT = I(off + OB_NVERTEX), I(off + OB_NFACE), I(off + OB_NTEXLINK)
            nR, nP, nS = I(off + OB_NROT), I(off + OB_NPOS), I(off + OB_NSCALE)
            has_phys = I(off + OB_PHYSIQUE) != 0
            o.tm = [list(struct.unpack_from('<4i', b, off + OB_TM + 16 * r)) for r in range(4)]
            o.tminv = [list(struct.unpack_from('<4i', b, off + OB_TMINV + 16 * r)) for r in range(4)]
            o.quat = struct.unpack_from('<4f', b, off + OB_QUAT)
            o.scale = tuple(v / 256.0 for v in struct.unpack_from('<3i', b, off + OB_SCALE))
            o.pos = tuple(v / 256.0 for v in struct.unpack_from('<3i', b, off + OB_POS))
            base = struct.unpack_from('<I', b, off + OB_TEXLINK_PTR)[0]
            p = off + OBJ_SIZE
            o.local_verts = [(x / 256.0, y / 256.0, z / 256.0)
                             for (x, y, z, _a, _b, _c) in struct.iter_unpack('<6i', b[p:p + nV * 24])]
            p += nV * 24
            raw_faces = list(struct.iter_unpack('<4H6fI', b[p:p + nF * 36]))
            p += nF * 36
            texlinks = list(struct.iter_unpack('<6fII', b[p:p + nT * 32]))
            p += nT * 32
            o.rot_keys = list(struct.iter_unpack('<i4f', b[p:p + nR * 20]))
            p += nR * 20
            o.pos_keys = list(struct.iter_unpack('<i3f', b[p:p + nP * 16]))
            p += nP * 16
            o.scale_keys = [(fr, x / 256.0, y / 256.0, z / 256.0)
                            for (fr, x, y, z) in struct.iter_unpack('<4i', b[p:p + nS * 16])]
            p += nS * 16
            p += nR * 64                                     # TmPrevRot cache (unused)
            o.physique = None
            if has_phys:
                o.physique = [_cstr(b[p + 32 * i:p + 32 * i + 32]) for i in range(nV)]
                p += nV * 32
            o.faces = [(f[0], f[1], f[2], f[3]) for f in raw_faces]
            o.face_uvs = [_walk_texlinks(texlinks, base, f[10]) for f in raw_faces]
            self.objects.append(o)
            off = p
        self.data_end = off

    def last_frame_ticks(self):
        t = 0
        for o in self.objects:
            for keys in (o.rot_keys, o.pos_keys, o.scale_keys):
                if keys:
                    t = max(t, keys[-1][0])
        return t


def file_kind(path):
    with open(path, 'rb') as fh:
        h = fh.read(24)
    if h.startswith(STAGE_HEADER):
        return 'stage'
    if h.startswith(MODEL_HEADER):
        return 'model'
    return None
