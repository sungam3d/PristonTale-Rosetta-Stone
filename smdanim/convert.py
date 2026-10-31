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
from .motion import find_rig, find_rig_for_smb, smb_segments


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
    sc = [math.sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2]) or 1.0 for r in rows]
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
    """Node TM rotation (TM_ROTAXIS / TM_ROTANGLE) - unchanged from the map converter."""
    x, y, z, w = q
    w = max(-1.0, min(1.0, w))
    ang = 2.0 * math.acos(w)
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-7:
        return (0.0, 0.0, 0.0), 0.0
    return (x / s, y / s, z / s), ang


def _key_axis_angle(q):
    """Animation key.  atan2 rather than acos(w): the deltas are tiny turns whose
    w is within float32 rounding of 1.0, so the angle must come from x, y, z."""
    x, y, z, w = q
    s = math.sqrt(x * x + y * y + z * z)
    if s < 1e-12:
        return (0.0, 0.0, 0.0), 0.0
    return (x / s, y / s, z / s), 2.0 * math.atan2(s, w)


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
        self.kind = 'mesh'         # mesh | bone
        self.physique = None       # per-vertex bone name (skinned meshes)


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
        self.anim_mode = 'none'    # embed | shared | none
        self.anim_file = ''        # shared motion file (class skeletons)
        self.motion_file = ''      # the game's separate motion file of a monster (mGknight.ASE ...)
        self.skeleton_file = ''
        self.motions = []          # motion.Motion list (absolute frames)


# ----------------------------------------------------------------------------- options
class Options(object):
    def __init__(self, **kw):
        self.game_root = None          # root folder that contains 'Field', 'char', ...
        self.texture_out = None        # copy+decrypt textures here (None = reference in place)
        self.texture_dir_override = None  # use this folder (flat) for every BITMAP path
        self.split_collision = True
        self.drop_collision = False
        self.split_objects = True      # maps: one object per original part (False = one mesh)
        self.compact_materials = True
        self.vertex_colors = True
        self.clamp_colors = True
        self.color_scale = 1.0
        self.animation = 'auto'        # auto | embed | shared | none
        self.lod = 'high'              # high | all  (monster detail levels)
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

    coll = []
    parts = []
    for part in (_stage_parts(st) if opt.split_objects else [list(range(len(st.faces)))]):
        keep = []
        for fi in part:
            m = mats[st.faces[fi][3]] if st.faces[fi][3] < nmat else None
            if opt.split_collision and (m is None or m.is_collision):
                coll.append(fi)
            else:
                keep.append(fi)
        if keep:
            parts.append(keep)
    if len(parts) <= 1:
        parts = parts or [[]]
        groups = [('', parts[0])]
    else:
        groups = [('_%03d%s' % (k + 1, _part_label(st, fidx)), fidx) for k, fidx in enumerate(parts)]
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
        if opt.split_objects and go.verts:
            # pivot in the middle of the object (vertices stay in world space), so moving
            # one object in the editor shows the gizmo on it, not at the world origin.  Whole
            # units: editors keep vertices in single precision relative to the pivot, and a
            # whole-unit pivot gives back every world position exactly.
            go.pos = tuple(float(math.floor((min(v[j] for v in go.verts) + max(v[j] for v in go.verts)) / 2.0 + 0.5))
                           for j in range(3))
        sc.objects.append(go)

    if opt.include_lights:
        sc.lights = st.lights
    sc.stage = st
    return sc


PART_MERGE_DISTANCE = 300.0
PART_LOOKBACK = 1


def _stage_parts(st):
    """Split a map's faces into the objects it was built from, as far as the file still tells.

    The game appends every ASE object's vertex list as is and keeps the faces in
    object order, so a real object boundary always lies where every vertex used
    before a face is lower than every vertex used from it on.  Those cuts also fall
    between loose parts of one object, so a part joins the object before it when they
    share a material and lie within PART_MERGE_DISTANCE of each other; it may also
    join the object PART_LOOKBACK places back (taking the ones in between along),
    for objects whose parts alternate between materials.  The names are not in the
    file.  scripts/score_stage_parts.py measures this against the original 2012 files:
    about as many objects as the originals, ~85% of the faces where they were.
    Returns lists of face indices, in file order."""
    faces = st.faces
    n = len(faces)
    if not n:
        return [[]]
    suf = [0] * n
    lo = 1 << 30
    for i in range(n - 1, -1, -1):
        a, b, c = faces[i][0], faces[i][1], faces[i][2]
        lo = min(lo, a, b, c)
        suf[i] = lo
    bounds = [0]
    hi = -1
    for i in range(1, n):
        a, b, c = faces[i - 1][0], faces[i - 1][1], faces[i - 1][2]
        hi = max(hi, a, b, c)
        if hi < suf[i]:
            bounds.append(i)
    bounds.append(n)
    P = st.positions
    d = PART_MERGE_DISTANCE
    groups = []                     # [first face, end face, materials, box]
    for k in range(len(bounds) - 1):
        mats = set()
        bb = None
        for fi in range(bounds[k], bounds[k + 1]):
            f = faces[fi]
            mats.add(f[3])
            for v in (f[0], f[1], f[2]):
                p = P[v]
                if bb is None:
                    bb = [p[0], p[1], p[2], p[0], p[1], p[2]]
                else:
                    for j in range(3):
                        if p[j] < bb[j]:
                            bb[j] = p[j]
                        if p[j] > bb[j + 3]:
                            bb[j + 3] = p[j]
        hit = -1
        for g in range(len(groups) - 1, max(-1, len(groups) - 2 - PART_LOOKBACK), -1):
            gm, gb = groups[g][2], groups[g][3]
            if (gm & mats) and all(gb[j] <= bb[j + 3] + d and bb[j] <= gb[j + 3] + d for j in range(3)):
                hit = g
                break
        if hit < 0:
            groups.append([bounds[k], bounds[k + 1], mats, bb])
            continue
        while len(groups) - 1 > hit:            # the groups in between become part of it too
            last = groups.pop()
            mats |= last[2]
            bb = [min(bb[j], last[3][j]) for j in range(3)] + [max(bb[j + 3], last[3][j + 3]) for j in range(3)]
        g = groups[hit]
        g[1] = bounds[k + 1]
        g[2] |= mats
        g[3] = [min(g[3][j], bb[j]) for j in range(3)] + [max(g[3][j + 3], bb[j + 3]) for j in range(3)]
    return [list(range(g[0], g[1])) for g in groups]


def _part_label(st, fidx):
    """'_jandi': the texture most of a part's faces use (helps to find parts in the editor)."""
    count = {}
    for fi in fidx:
        m = st.faces[fi][3]
        count[m] = count.get(m, 0) + 1
    best = None
    for m in sorted(count):
        if best is None or count[m] > count[best]:
            best = m
    if best is None or best >= len(st.materials) or not st.materials[best].textures:
        return ''
    name = st.materials[best].textures[0][0].replace('\\', '/').split('/')[-1]
    if '.' in name:
        name = name[:name.rindex('.')]
    name = ''.join(ch if (ch.isalnum() and ord(ch) < 128) or ch in '-_' else '_' for ch in name)[:24]
    return '_' + name if name else ''


def _model_world(o):
    """World rows & translation for a model object (exactly what PT used to
    convert the original world-space vertices to local space)."""
    ti = [[o.tminv[r][c] / 256.0 for c in range(3)] for r in range(3)]
    t = (o.tm[3][0] / 256.0, o.tm[3][1] / 256.0, o.tm[3][2] / 256.0)
    if not _sane_tm(o.tminv):
        # some files leave junk (uninitialised memory or zeros) in TmInvert; the game never
        # uses it for a skinned mesh (every vertex rides on its bone): plain pivot
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], t
    return _inv3(ti), t


def _sane_tm(m):
    """A real 8.8 fixed-point smMATRIX: last column 0 0 0 256, sensible size, not flat."""
    if m[0][3] != 0 or m[1][3] != 0 or m[2][3] != 0 or m[3][3] != 256:
        return False
    if any(abs(m[r][c]) > 65536 for r in range(3) for c in range(3)):
        return False
    a = [[m[r][c] / 256.0 for c in range(3)] for r in range(3)]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    return 1e-4 < abs(det) < 1e4


def _dedupe_motions(motions):
    seen = set()
    out = []
    for m in motions:
        k = (m.start, m.end)
        if k not in seen:
            seen.add(k)
            out.append(m)
    out.sort(key=lambda m: (m.start, m.end))
    count = {}
    for m in out:                                   # renumber: walk_01, walk_02 ...
        label = m.name.rsplit('_', 1)[0]
        count[label] = count.get(label, 0) + 1
        m.name = '%s_%02d' % (label, count[label])
    return out


def _quat_from_matrix(m):
    """(x, y, z, w) of the rotation whose standard (column-vector) matrix is m."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        q = ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        q = (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        q = ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        q = ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])   # (not sum(): it compensates since Python 3.12)
    return tuple(c / n for c in q)


def _qmul_xyzw(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def _rotation_keys(o):
    """ASE rotation samples (tick, axis, angle) that reproduce the rotation the
    game actually uses at every key (its TmPrevRot cache).

    ASE keys are deltas: orientation_i = orientation_{i-1} turned by key i.
    The .smb keys are the same deltas, except that glued motion files
    (m1.smb ...) restart some bones at the first key of each motion piece;
    the cache has the true orientation, so each delta is rebuilt from it:
        q_i = conj(p_{i-1}) * p_i      (p = quaternion of the cached rows)
    always the shortest way round (a few keys store "no turn" as w = -1)."""
    prev = getattr(o, 'prev_rot', None)
    if not prev or len(prev) != len(o.rot_keys):
        return [(k[0],) + _key_axis_angle(k[1:5]) for k in o.rot_keys]
    out = []
    last = (0.0, 0.0, 0.0, 1.0)
    for (t, x, y, z, w), f in zip(o.rot_keys, prev):
        p = _quat_from_matrix([[f[0], f[1], f[2]], [f[4], f[5], f[6]], [f[8], f[9], f[10]]])
        q = _qmul_xyzw((-last[0], -last[1], -last[2], last[3]), p)
        if q[3] < 0.0:
            q = (-q[0], -q[1], -q[2], -q[3])
        out.append((t,) + _key_axis_angle(q))
        last = p
    return out


def _pieces(o):
    """[(start, end, rot(idx, n), pos(idx, n), scale(idx, n))] of the glued motion
    pieces that have length, or None for a plain single-timeline file."""
    fr = getattr(o, 'frames', None)
    if not fr or not fr[0]:
        return None
    out = []
    for r, p, s in zip(*fr):
        if r[1] > r[0] and r[0] >= 0:
            out.append((r[0], r[1], (r[2], r[3]), (p[2], p[3]), (s[2], s[3])))
    return out or None


def _piece_track(pieces, which, keys, static):
    """Absolute values per piece -> one continuous track (tick, value, key index).

    The game looks up keys only inside the piece being played; a piece without
    keys shows the bone's static transform.  Each piece is therefore held flat
    up to its edges (1 tick before the next piece starts) so nothing blends
    from one motion into the next."""
    out = []
    for pc in pieces:
        s, e = pc[0], pc[1]
        idx, n = pc[2 + which]
        if n <= 0 or idx < 0 or idx + n > len(keys):
            out.append((s, static, None))
            out.append((e - 1, static, None))
            continue
        seg = [(keys[j][0], j) for j in range(idx, idx + n)]
        if seg[0][0] > s:
            out.append((s, None, seg[0][1]))                       # hold the first key
        for t, j in seg:
            t = min(t, e - 1)
            if out and out[-1][0] >= max(t, s):
                out[-1] = (out[-1][0], None, j)                      # same tick: later key wins
                continue
            out.append((t, None, j))
        if out[-1][0] < e - 1:
            out.append((e - 1, None, seg[-1][1]))                  # hold the last key
    return out


def _anim_keys(o):
    """(pos_keys, rot_keys, scale_keys) for the ASE writer, reproducing what the
    game shows at every tick.  Rotation keys are rebuilt from the TmPrevRot cache
    (see _rotation_keys)."""
    pieces = _pieces(o)
    if pieces is None:
        return list(o.pos_keys), _rotation_keys(o), list(o.scale_keys)
    pos = scl = rot = []
    if o.pos_keys:
        pos = [(t, ) + tuple(v if v is not None else o.pos_keys[j][1:4])
               for t, v, j in _piece_track(pieces, 1, o.pos_keys, o.pos)]
    if o.scale_keys:
        scl = [(t, ) + tuple(v if v is not None else o.scale_keys[j][1:4])
               for t, v, j in _piece_track(pieces, 2, o.scale_keys, o.scale)]
    if o.rot_keys:
        prev = o.prev_rot
        x, y, z, w = o.quat
        n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
        static = tuple(c / n for c in o.quat)

        def absolute(j):
            f = prev[j]
            return _quat_from_matrix([[f[0], f[1], f[2]], [f[4], f[5], f[6]], [f[8], f[9], f[10]]])
        last = (0.0, 0.0, 0.0, 1.0)
        rot = []
        for t, v, j in _piece_track(pieces, 0, o.rot_keys, static):
            p = v if v is not None else absolute(j)
            q = _qmul_xyzw((-last[0], -last[1], -last[2], last[3]), p)
            if q[3] < 0.0:
                # shortest way round: some keys store "no turn" as w = -1, which
                # read literally would spin the bone a full circle
                q = (-q[0], -q[1], -q[2], -q[3])
            rot.append((t,) + _key_axis_angle(q))
            last = p
    return pos, rot, scl


def _bone_object(b, keys=True):
    go = GeomObject(b.name)
    go.kind = 'bone'
    go.parent = b.parent
    go.rows, go.pos = _model_world(b)
    if b.faces:
        # the bone's own Biped shape, when the .smb still has it
        go.verts = [_xform(v, go.rows, go.pos) for v in b.local_verts]
        go.faces = [(f[0], f[1], f[2], 0) for f in b.faces]
    else:
        # the small diamond 3ds Max Biped gives a bone (6 vertices, 8 faces)
        x, y, z = go.pos
        r = 0.5
        go.verts = [(x, y, z + r), (x, y - r, z), (x + r, y, z), (x, y + r, z), (x - r, y, z), (x, y, z - r)]
        go.faces = [(0, 1, 2, 0), (0, 2, 3, 0), (0, 3, 4, 0), (0, 4, 1, 0),
                    (5, 4, 3, 0), (5, 3, 2, 0), (5, 2, 1, 0), (5, 1, 4, 0)]
    if keys:
        go.pos_keys, go.rot_keys, go.scale_keys = _anim_keys(b)
    return go


def _skeleton_motions(rig_info, smb_path):
    if rig_info is None:
        return []
    return _dedupe_motions(rig_info.motions(smb_segments(smb_path)))


def build_model_scene(path, opt):
    """Objects, characters and monsters (.smd), or a skeleton/motion file (.smb)."""
    md = Model(path)
    name = os.path.splitext(os.path.basename(path))[0]
    sc = Scene(name)
    sc.kind = 'model'
    sc.source = path
    is_smb = path.lower().endswith('.smb')

    # ---- skeleton -------------------------------------------------------------
    needs = set()
    for o in md.objects:
        if o.physique:
            needs.update(n for n in o.physique if n)
    skel = None
    rig = None
    if is_smb:
        skel = md
        rig = find_rig_for_smb(path)
    elif needs:
        rig = find_rig(path, sorted(needs))
        if rig.smb:
            skel = Model(rig.smb)
    bones = {b.name: _model_world(b) for b in skel.objects} if skel else {}
    sc.rig = rig
    sc.missing_bones = sorted(n for n in needs if n not in bones)

    # ---- animation placement ----------------------------------------------------
    mode = opt.animation
    if skel is not None and mode == 'auto':
        mode = 'shared' if (rig and rig.shared and not is_smb) else 'embed'
    sc.anim_mode = mode if skel is not None else 'none'
    if skel is not None:
        sc.skeleton_file = os.path.basename(rig.smb if (rig and rig.smb) else path)
        sc.motions = _skeleton_motions(rig and rig.info, rig.smb if (rig and rig.smb) else path)
        if sc.anim_mode == 'shared':
            sc.anim_file = os.path.splitext(sc.skeleton_file)[0] + '_motions.ase'
        elif (not is_smb and sc.anim_mode == 'embed'
              and os.path.splitext(sc.skeleton_file)[0].lower() != name.lower()):
            # the game keeps this monster's animation in its own motion file (mGknight ...):
            # the animation is included for viewing, but it does not belong in the model file
            sc.motion_file = os.path.splitext(sc.skeleton_file)[0] + '.ASE'

    # ---- detail levels: keep the high one ------------------------------------------
    drop = set()
    if rig and rig.info and opt.lod == 'high':
        high = {n.lower() for n in rig.info.lod[0]}
        for n in rig.info.lod[1] + rig.info.lod[2]:
            if n.lower() not in high:
                drop.add(n.lower())
    meshes = [o for o in md.objects if o.name.lower() not in drop and (o.faces or not skel)]
    if is_smb:
        meshes = []

    mats = md.materials
    nmat = len(mats)
    used = set()
    for o in meshes:
        for f in o.faces:
            if f[3] < nmat:
                used.add(f[3])
    sc.materials, remap = _material_remap(mats, used, opt.compact_materials)

    if skel is not None:
        for b in skel.objects:
            sc.objects.append(_bone_object(b, keys=sc.anim_mode == 'embed'))
    for o in meshes:
        rows, t = _model_world(o)
        go = GeomObject(o.name)
        go.parent = o.parent if (o.parent in bones or any(m.name == o.parent for m in meshes)) else ''
        go.rows, go.pos = rows, t
        if o.physique:
            go.verts = [_xform(lv, *bones.get(bn, (rows, t))) for lv, bn in zip(o.local_verts, o.physique)]
            go.physique = list(o.physique)
        else:
            go.verts = [_xform(v, rows, t) for v in o.local_verts]
        go.faces = [(a, b_, c, remap.get(m, 0)) for (a, b_, c, m) in o.faces]
        nl = max([len(l) for l in o.face_uvs] or [0])
        go.channels = _channels_from_layers(o.face_uvs, nl, 'one_minus')
        go.pos_keys, go.rot_keys, go.scale_keys = _anim_keys(o)
        sc.objects.append(go)

    ticks = md.last_frame_ticks()
    if skel is not None:
        ticks = max(ticks, skel.last_frame_ticks())
    sc.last_frame = max(1, ticks // 160) if ticks else 100
    sc.model = md
    sc.skeleton = skel
    return sc


def build_anim_scene(sc):
    """The shared motion file of a class skeleton: bones + every animation key."""
    skel = sc.skeleton
    an = Scene(os.path.splitext(sc.anim_file)[0])
    an.kind = 'motion'
    an.source = skel.path
    an.anim_mode = 'embed'
    an.skeleton_file = sc.skeleton_file
    an.motions = sc.motions
    an.objects = [_bone_object(b) for b in skel.objects]
    an.last_frame = max(1, skel.last_frame_ticks() // 160)
    return an


def build_scene(path, opt):
    kind = file_kind(path)
    if kind == 'stage':
        return build_stage_scene(path, opt)
    if kind == 'model':
        return build_model_scene(path, opt)
    raise SMDError('%s: unknown file type' % path)


# ----------------------------------------------------------------------------- textures
def _ancestors(path):
    d = os.path.dirname(os.path.abspath(path))
    while True:
        yield d
        parent = os.path.dirname(d)
        if parent == d:
            return
        d = parent


def find_texture(rel, smd_path, root=None):
    """Locate a texture named in an SMD ('char\\monster\\Tees\\Tees.tga').

    Paths are relative to the game folder, which is whichever ancestor of the
    SMD makes the path exist (works for Field, char, effect ... and copies of
    single folders).  Last resort: the bare file name next to the SMD.
    Returns (real_path, root_used) or (None, None)."""
    rel = rel.replace('\\', '/')
    tried = [root or guess_game_root(smd_path)]
    tried.extend(_ancestors(smd_path))
    for r in tried:
        src = resolve_case_insensitive(r, rel)
        if src:
            return src, r
    folder = os.path.dirname(os.path.abspath(smd_path))
    src = resolve_case_insensitive(folder, os.path.basename(rel))
    if src:
        return src, None
    return None, None


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
        src, used_root = find_texture(n, smd_path, opt.game_root)
        if src is None and opt.texture_log is not None:
            opt.texture_log.setdefault(n, set()).add(os.path.basename(smd_path))
        if opt.texture_dir_override:
            out = os.path.join(opt.texture_dir_override, os.path.basename(src or rel))
            if src and opt.texture_out and not os.path.isfile(out):
                decode_texture_file(src, out)
        elif opt.texture_out:
            relpath = os.path.relpath(src, used_root) if (src and used_root) else \
                (os.path.basename(src) if src else rel)
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


def _f9(x):
    s = '%.9f' % x
    return '0.000000000' if s == '-0.000000000' else s


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
    _write_anim(w, go)
    w('\t*MATERIAL_REF 0')
    if go.physique:
        # One bone per vertex - exactly what 3ds Max Physique exported for PT
        # (a few monsters leave vertices without a bone: they stay put, so they
        # are simply not assigned)
        assigned = [(i, bn) for i, bn in enumerate(go.physique) if bn]
        w('\t*PHYSIQUE {')
        w('\t\t*PHYSIQUE_NUMVERTEXASSIGNMENT\t%d' % len(assigned))
        for i, bn in assigned:
            w('\t\t*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE %d\t%s' % (i, _q(bn)))
        w('\t}')
    w('}')


def _write_anim(w, go):
    """Keys are written exactly as 3ds Max's ASE exporter wrote them for PT:
    position = parent-relative, rotation = delta from the previous key
    (axis + angle; the first key is absolute), scale = absolute.
    Rotation deltas get nine decimals: a class skeleton chains ~10000 of them."""
    if not (go.pos_keys or go.rot_keys or go.scale_keys):
        return
    w('\t*TM_ANIMATION {')
    w('\t\t*NODE_NAME %s' % _q(go.name))
    if go.pos_keys:
        w('\t\t*CONTROL_POS_TRACK {')
        for (t, x, y, z) in go.pos_keys:
            w('\t\t\t*CONTROL_POS_SAMPLE %d\t%s\t%s\t%s' % (t, _f6(x), _f6(y), _f6(z)))
        w('\t\t}')
    if go.rot_keys:
        w('\t\t*CONTROL_ROT_TRACK {')
        for (t, ax, ang) in go.rot_keys:
            w('\t\t\t*CONTROL_ROT_SAMPLE %d\t%s\t%s\t%s\t%s' % (t, _f9(ax[0]), _f9(ax[1]), _f9(ax[2]), _f9(ang)))
        w('\t\t}')
    if go.scale_keys:
        w('\t\t*CONTROL_SCALE_TRACK {')
        for (t, x, y, z) in go.scale_keys:
            w('\t\t\t*CONTROL_SCALE_SAMPLE %d\t%s\t%s\t%s\t0.0000\t0.0000\t0.0000\t0.0000'
              % (t, _f6(x), _f6(y), _f6(z)))
        w('\t\t}')
    w('\t}')


def _write_bone(w, go):
    """Skeleton bone exactly as 3ds Max Biped exported them for PT: a mesh object
    WITHOUT a material.  The game's builder puts material-less meshes (with their
    animation) into the .smb and ignores helper objects entirely."""
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
        w('\t\t\t*MESH_VERTEX %5d\t%s\t%s\t%s' % (i, _f4(v[0]), _f4(v[1]), _f4(v[2])))
    w('\t\t}')
    w('\t\t*MESH_FACE_LIST {')
    for i, (a, b, c, _m) in enumerate(go.faces):
        w('\t\t\t*MESH_FACE %5d:    A: %5d B: %5d C: %5d AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING 1 \t*MESH_MTLID 0'
          % (i, a, b, c))
    w('\t\t}')
    w('\t\t*MESH_NUMTVERTEX 0')
    w('\t}')
    w('\t*PROP_MOTIONBLUR 0')
    w('\t*PROP_CASTSHADOW 1')
    w('\t*PROP_RECVSHADOW 1')
    _write_anim(w, go)
    w('\t*WIREFRAME_COLOR 0.6510\t0.7922\t0.9412')
    w('}')


def _write_motions(w, sc):
    """PT extension: which skeleton animates this file and the named motions on
    its timeline (from the game's .inx motion table).  Other ASE readers skip it."""
    if sc.anim_mode == 'none' and not sc.motions:
        return
    w('*PT_ANIMATION {')
    w('\t*PT_SKELETON %s' % _q(sc.skeleton_file))
    if sc.anim_file:
        w('\t*PT_ANIMATION_FILE %s' % _q(sc.anim_file))
    if getattr(sc, 'motion_file', ''):
        w('\t*PT_MOTION_FILE %s' % _q(sc.motion_file))
    for m in sc.motions:
        w('\t*PT_MOTION %s\t%d\t%d\t%d' % (_q(m.name), m.start, m.end, 1 if m.loop else 0))
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
    _write_motions(w, sc)
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
        if go.kind == 'bone':
            _write_bone(w, go)
        else:
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
    if sc.anim_file:
        # Shared class animation (m1_motions.ase ...): written once per folder
        ap = os.path.join(os.path.dirname(out_path), sc.anim_file)
        if not os.path.isfile(ap) or os.path.getmtime(ap) < os.path.getmtime(sc.skeleton.path):
            write_ase(build_anim_scene(sc), ap)
    return sc
