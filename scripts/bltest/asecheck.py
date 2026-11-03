"""Independent ASE reader and face-by-face comparison for the Blender add-on tests.

Deliberately does not reuse the add-on's code, so a bug there can't hide itself here.

  load(path)            -> Scene: objects (meshes, bones, lights) and materials
  compare(orig, other)  -> dict of differences (positions, UVs, colours, textures, materials,
                           pivots, parents), matching objects by name and faces in order
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from smdanim.aseparse import parse_ase, find, find_all, val, unquote   # noqa: E402


def _fl(s, n):
    out = []
    for t in (s or '').split():
        try:
            out.append(float(t))
        except ValueError:
            out.append(0.0)
    return (out + [0.0] * n)[:n]


class Mat(object):
    def __init__(self, node):
        self.name = unquote(val(node, '*MATERIAL_NAME', ''))
        self.cls = unquote(val(node, '*MATERIAL_CLASS', 'Standard'))
        self.two_sided = find(node, '*MATERIAL_TWOSIDED') is not None
        self.transparency = _fl(val(node, '*MATERIAL_TRANSPARENCY', '0'), 1)[0]
        self.self_illum = _fl(val(node, '*MATERIAL_SELFILLUM', '0'), 1)[0]
        self.additive = val(node, '*MATERIAL_XP_TYPE', '') == 'Additive'
        self.maps = {}
        for c in node[2] or ():
            if c[0] in ('*MAP_DIFFUSE', '*MAP_SELFILLUM', '*MAP_OPACITY'):
                bm = self._bitmap(c)
                if bm is not None:
                    self.maps.setdefault(c[0], []).append(bm)
        self.subs = {}
        self.num = int(_fl(val(node, '*NUMSUBMTLS', '0'), 1)[0])
        for s in find_all(node, '*SUBMATERIAL'):
            try:
                self.subs[int(s[1].split()[0])] = Mat(s)
            except (ValueError, IndexError):
                pass

    @staticmethod
    def _bitmap(node):
        b = val(node, '*BITMAP')
        if b is not None:
            path = unquote(b)
            name = os.path.basename(path.replace('\\', '/')).lower()
            return (os.path.splitext(name)[0], unquote(val(node, '*MAP_NAME', '')),
                    int(_fl(val(node, '*MAP_CHANNEL', '1'), 1)[0]) or 1)
        for c in node[2] or ():
            if c[2]:
                r = Mat._bitmap(c)
                if r is not None:
                    return r
        return None

    def resolve(self, mtlid):
        m = self
        while m.cls == 'Shell Material' and m.subs:
            m = m.subs.get(0) or list(m.subs.values())[0]
        if m.subs or m.num:
            n = m.num or (max(m.subs) + 1)
            s = m.subs.get(mtlid % n if n else 0)
            return s.resolve(0) if s is not None and (s.subs or s.cls == 'Shell Material') else s
        return m

    def signature(self):
        """What the game reads from a material (texture file names without folder/extension)."""
        d = self.maps.get('*MAP_DIFFUSE', [])
        lay = self.maps.get('*MAP_SELFILLUM', [])
        return dict(name=self.name, diffuse=d[0][0] if d else '', layers=tuple(x[0] for x in lay),
                    layer_names=tuple(x[1] for x in lay), two_sided=self.two_sided,
                    transparency=round(self.transparency, 3), additive=self.additive)


class Obj(object):
    pass


class Scene(object):
    pass


def _uv_block(blk):
    tl, tf = find(blk, '*MESH_TVERTLIST'), find(blk, '*MESH_TFACELIST')
    if tl is None or tf is None:
        return None
    tv = [_fl(c[1], 4)[1:3] for c in tl[2] or []]
    fs = [tuple(int(x) for x in c[1].split()[1:4]) for c in tf[2] or []]
    return tv, fs


def read_physique(ph):
    """{vertex: bone} as the game's ASE reader takes it: lines at any depth; a blended vertex
    uses the node listed first (number 0)."""
    out = {}
    if ph is None:
        return out
    cur = [None]

    def walk(n):
        for c in n[2] or ():
            if c[0] == '*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE':
                p = c[1].split(None, 1)
                try:
                    out[int(p[0])] = unquote(p[1].strip())
                except (ValueError, IndexError):
                    pass
            elif c[0] == '*PHYSIQUE_VERTEXASSIGNMENT_BLENDED_RIGIDTYPE':
                try:
                    cur[0] = int(c[1].split()[0])
                except (ValueError, IndexError):
                    cur[0] = None
            elif c[0] == '*PHYSIQUE_VERTEXASSIGNMENT_NODE' and cur[0] is not None:
                p = c[1].split(None, 2)
                if len(p) == 3 and p[0] == '0':
                    out[cur[0]] = unquote(p[2].strip())
            if c[2]:
                walk(c)
    walk(ph)
    return out


def load(path):
    root = parse_ase(path)
    sc = Scene()
    sc.path = path
    ml = find(root, '*MATERIAL_LIST')
    sc.mats = [Mat(m) for m in find_all(ml, '*MATERIAL')] if ml else []
    sc.objects = []
    sc.pt_animation = None
    pa = find(root, '*PT_ANIMATION')
    if pa is not None:
        sc.pt_animation = [(c[0], c[1]) for c in pa[2] or []]

    def walk(n):
        for c in n[2] or ():
            if c[0] in ('*GEOMOBJECT', '*HELPEROBJECT', '*LIGHTOBJECT'):
                yield c
            elif c[0] == '*GROUP':
                for x in walk(c):
                    yield x
    for g in walk(root):
        o = Obj()
        o.kind = g[0]
        o.name = unquote(val(g, '*NODE_NAME', ''))
        o.parent = unquote(val(g, '*NODE_PARENT', ''))
        tm = find(g, '*NODE_TM')
        o.rows = [_fl(val(tm, '*TM_ROW%d' % k, ''), 3) for k in range(4)] if tm else None
        o.mref = int(_fl(val(g, '*MATERIAL_REF', '-1'), 1)[0]) if val(g, '*MATERIAL_REF') is not None else None
        o.anim = find(g, '*TM_ANIMATION') is not None
        m = find(g, '*MESH')
        o.verts, o.faces, o.uv, o.col = [], [], {}, None
        if m is not None:
            vl = find(m, '*MESH_VERTEX_LIST')
            o.verts = [_fl(c[1], 4)[1:4] for c in (vl[2] or [])] if vl else []
            fl = find(m, '*MESH_FACE_LIST')
            for c in (fl[2] or []) if fl else []:
                s = c[1]
                try:
                    a = int(s.split('A:')[1].split()[0])
                    b = int(s.split('B:')[1].split()[0])
                    cc = int(s.split('C:')[1].split()[0])
                except (IndexError, ValueError):
                    continue
                k = s.find('*MESH_MTLID')
                o.faces.append((a, b, cc, int(s[k + 11:].split()[0]) if k >= 0 else 0))
            main = _uv_block(m)
            if main:
                o.uv[1] = main
            for mc in find_all(m, '*MESH_MAPPINGCHANNEL'):
                try:
                    ch = int(mc[1].split()[0])
                except (ValueError, IndexError):
                    continue
                b = _uv_block(mc)
                if b:
                    o.uv[ch] = b
            cl, cf = find(m, '*MESH_CVERTLIST'), find(m, '*MESH_CFACELIST')
            if cl is not None and cf is not None:
                o.col = ([_fl(c[1], 4)[1:4] for c in cl[2] or []],
                         [tuple(int(x) for x in c[1].split()[1:4]) for c in cf[2] or []])
        o.physique = read_physique(find(g, '*PHYSIQUE'))
        sc.objects.append(o)
    return sc


def is_mesh(o, char):
    """A drawable mesh (not a bone): has faces and, in character files, a material."""
    if o.kind != '*GEOMOBJECT' or not o.faces:
        return False
    return o.mref is not None or not char or bool(o.physique)


def is_char(sc):
    return any(o.physique for o in sc.objects)


def kept_faces(o):
    """Faces the add-on keeps (Blender drops faces that use a vertex twice)."""
    return [i for i, f in enumerate(o.faces) if len({f[0], f[1], f[2]}) == 3]


def _corner_uv(o, ch, fi, j):
    blk = o.uv.get(ch)
    if not blk:
        return None
    tv, tf = blk
    if fi >= len(tf):
        return None
    t = tf[fi][j]
    return tv[t] if 0 <= t < len(tv) else None


def _corner_col(o, fi, j):
    if not o.col:
        return None
    cv, cf = o.col
    if fi >= len(cf):
        return None
    t = cf[fi][j]
    return cv[t] if 0 <= t < len(cv) else None


def mat_sig(sc, o, mtlid):
    if o.mref is None or not (0 <= o.mref < len(sc.mats)):
        return None
    m = sc.mats[o.mref].resolve(mtlid)
    return m.signature() if m is not None else None


def compare(a, b, check_uv=True, check_col=True, check_mat=True, names=None, all_faces=False):
    """Compare scene b (e.g. exported) with scene a (original), object by object.
    names: optional {original name: name in b}.  all_faces: b keeps the faces that use a vertex
    twice (3ds Max does, Blender drops them)."""
    char = is_char(a)
    res = dict(objects=0, missing=[], extra=[], face_count=[], pos=0.0, uv=0.0, col=0.0,
               col_missing=0, uv_missing=0, mat_diff=0, mat_examples=[], winding=0, parent_diff=[],
               faces=0)
    bmap = {}
    for o in b.objects:
        if is_mesh(o, is_char(b)):
            bmap.setdefault(o.name, []).append(o)
    am = [o for o in a.objects if is_mesh(o, char)]
    seen = set()
    nth = {}
    for oa in am:
        nb = (names or {}).get(oa.name, oa.name)
        k = nth.get(nb, 0)                      # duplicate names pair up in order
        nth[nb] = k + 1
        lst = bmap.get(nb, [])
        ob = lst[k] if k < len(lst) else None
        if ob is None:
            res['missing'].append(oa.name)
            continue
        seen.add(id(ob))
        res['objects'] += 1
        ka = list(range(len(oa.faces))) if all_faces else kept_faces(oa)
        if len(ka) != len(ob.faces):
            res['face_count'].append((oa.name, len(ka), len(ob.faces)))
            continue
        res['faces'] += len(ka)
        for fb, fa in enumerate(ka):
            A, B = oa.faces[fa], ob.faces[fb]
            pa = [oa.verts[A[j]] for j in range(3)]
            pb = [ob.verts[B[j]] for j in range(3)]
            # same corners, maybe rotated (never mirrored)
            best, rot = None, 0
            for r in range(3):
                d = max(abs(pa[j][k] - pb[(j + r) % 3][k]) for j in range(3) for k in range(3))
                if best is None or d < best:
                    best, rot = d, r
            rev = max(abs(pa[j][k] - pb[(2 - j) % 3][k]) for j in range(3) for k in range(3))
            if rev + 1e-6 < best and best > 0.01:
                res['winding'] += 1
            res['pos'] = max(res['pos'], best)
            if check_uv:
                for ch in oa.uv:
                    for j in range(3):
                        ua = _corner_uv(oa, ch, fa, j)
                        ub = _corner_uv(ob, ch, fb, (j + rot) % 3)
                        if ua is None:
                            continue
                        if ub is None:
                            res['uv_missing'] += 1
                            continue
                        res['uv'] = max(res['uv'], abs(ua[0] - ub[0]), abs(ua[1] - ub[1]))
            if check_col and oa.col:
                for j in range(3):
                    ca = _corner_col(oa, fa, j)
                    cb = _corner_col(ob, fb, (j + rot) % 3)
                    if ca is None:
                        continue
                    if cb is None:
                        res['col_missing'] += 1
                        continue
                    res['col'] = max(res['col'], max(abs(ca[k] - cb[k]) for k in range(3)))
            if check_mat:
                sa, sb = mat_sig(a, oa, A[3]), mat_sig(b, ob, B[3])
                if sa is not None and sa != sb:
                    res['mat_diff'] += 1
                    if len(res['mat_examples']) < 3:
                        res['mat_examples'].append((oa.name, sa, sb))
        if (oa.parent or '') != (ob.parent or ''):
            res['parent_diff'].append((oa.name, oa.parent, ob.parent))
    res['extra'] = [o.name for o in b.objects if is_mesh(o, is_char(b)) and id(o) not in seen]
    return res
