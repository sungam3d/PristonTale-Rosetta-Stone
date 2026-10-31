"""Character / monster motion tables and skeleton lookup.

How Priston Tale wires an animated model together
-------------------------------------------------
  * <model>.smd     the skinned mesh.  Every vertex stores the NAME of the one
                    bone it follows (rigid skinning, "physique").  The mesh
                    has no bones of its own.
  * <motion>.smb    the skeleton: every Bip01 bone with its bind pose and ALL
                    animation keys.  The game glues several motion ASE files
                    ("*동작모음") end to end into one timeline; the .smb header
                    keeps the (start, end) tick of every glued piece.
  * <name>.inx      compiled .ini: model file, motion file, death sub-model,
                    detail-level object names and the motion table (state,
                    start/end frame inside a glued piece, event frames, loop).
  * <name>.ini/.in  the same as text (CP949 Korean), shipped for some files.

Player bodies/heads (char\\tmABCD) have no .inx of their own: the class
skeleton files M1Bip.inx .. M8Bip.inx (motion file m1.ase .. m8.ase) are
shared by every armour/head of that class.
"""

import os
import re
import struct

TICKS_PER_FRAME = 160

# CHRMOTION_STATE_* codes used in .inx files
STATE_NAMES = {
    0x40: 'stand', 0x50: 'walk', 0x60: 'run', 0x80: 'fall', 0x100: 'attack', 0x110: 'damage',
    0x120: 'die', 0x130: 'idle', 0x140: 'potion', 0x150: 'skill', 0x170: 'land_small',
    0x180: 'land_big', 0x200: 'restart', 0x210: 'warp', 0x220: 'cheer', 0x300: 'hammer',
}

# Korean .ini keywords -> the same names (used when only the text file exists)
INI_MOTION_WORDS = [
    ('서있기', 'stand'), ('걷는', 'walk'), ('뛰는', 'run'), ('떨어지는', 'fall'), ('공격', 'attack'),
    ('타격', 'damage'), ('죽는', 'die'), ('죽기', 'die'), ('정지', 'idle'), ('물약', 'potion'),
    ('기술', 'skill'), ('작은착지', 'land_small'), ('큰착지', 'land_big'), ('다시시작', 'restart'),
    ('워프', 'warp'), ('만세', 'cheer'), ('망치', 'hammer'), ('대기', 'idle'),
]

# Player class skeletons.  Name scheme: [C] + race(T/M) + sex(m/f) + part(b/h) + class letter
CLASS_SKELETON = {
    ('t', 'a'): 1, ('t', 'b'): 1, ('t', 'c'): 4, ('t', 'd'): 2, ('t', 'e'): 6, ('t', 'f'): 8,
    ('m', 'a'): 1, ('m', 'b'): 2, ('m', 'c'): 5, ('m', 'd'): 3, ('m', 'e'): 7,
}
CLASS_NAMES = {1: 'Knight / Mechanician / Fighter', 2: 'Atalanta / Archer', 3: 'Magician',
               4: 'Pikeman', 5: 'Priestess', 6: 'Assassin', 7: 'Shaman', 8: 'Martial Artist'}
_PLAYER_RE = re.compile(r'^c?([tm])([mf])([bh])[-_]?m?([a-f])', re.I)   # MmbA34, Tfh-D03d, Mfh_B01b, MmbmA01b


class Motion(object):
    def __init__(self, name, state, start, end, events=(), loop=False, piece=0):
        self.name = name          # 'walk_02' ...
        self.state = state        # CHRMOTION_STATE code (0 if unknown)
        self.start = start        # absolute frame on the glued timeline
        self.end = end
        self.events = list(events)  # absolute frames (hit / footstep events)
        self.loop = loop
        self.piece = piece        # 1-based glued-piece index (inx MotionFrame)

    def __repr__(self):
        return 'Motion(%s %d-%d)' % (self.name, self.start, self.end)


class ModelInfo(object):
    """Parsed .inx (or .ini / .in) file."""

    def __init__(self):
        self.path = ''
        self.model_file = ''      # 'char\\monster\\Tees\\Tees.ASE'
        self.motion_file = ''     # '...\\Tees.ASE'  ->  Tees.smb
        self.sub_file = ''        # death model .ini
        self.link_file = ''       # *파일연결 (player body -> M1Bip.in)
        self.lod = ([], [], [])   # high / medium / low object names
        self.raw_motions = []     # (state, piece, start, end, events, loop, label)

    def motions(self, segments):
        """Motion list on the absolute timeline of the matching .smb."""
        out = []
        count = {}
        for state, piece, s, e, ev, loop, label in self.raw_motions:
            base = 0
            if 1 <= piece <= len(segments):
                base = segments[piece - 1][0] // TICKS_PER_FRAME
            label = label or STATE_NAMES.get(state, 'motion')
            count[label] = count.get(label, 0) + 1
            nm = '%s_%02d' % (label, count[label])
            out.append(Motion(nm, state, base + s, base + e, [base + x for x in ev], loop, piece))
        return out


def _frame16(b, o):
    # Frames are stored with a key byte interleaved: value = byte0 | byte2 << 8
    return b[o] | (b[o + 2] << 8)


def _cstr(b):
    return b.split(b'\0', 1)[0].decode('cp949', 'replace')


def read_inx(path):
    with open(path, 'rb') as f:
        b = f.read()
    mi = ModelInfo()
    mi.path = path
    mi.model_file = _cstr(b[0:64])
    mi.motion_file = _cstr(b[0x40:0x80])
    mi.sub_file = _cstr(b[0x80:0xC0])
    for k in range(3):
        o = 0xC0 + 68 * k
        n = struct.unpack_from('<i', b, o)[0]
        mi.lod[k].extend(_cstr(b[o + 4 + 16 * j:o + 20 + 16 * j]) for j in range(max(0, min(n, 4))))
    # 512 smMOTIONINFO records; 120 bytes in 2012 files, 172 bytes in current ones
    for size in (172, 120):
        cnt_off = 0x18C + 512 * size
        if cnt_off + 4 <= len(b):
            count = struct.unpack_from('<i', b, cnt_off)[0]
            if 0 <= count <= 512:
                break
    else:
        return mi
    tail = size - 120              # extra weapon-code bytes in the newer layout
    for k in range(count):
        o = 0x18C + size * k
        state = struct.unpack_from('<I', b, o)[0]
        if not state:
            continue
        s = _frame16(b, o + 4)
        e = _frame16(b, o + 16)
        ev = [x // TICKS_PER_FRAME for x in struct.unpack_from('<4I', b, o + 20) if x]
        loop = struct.unpack_from('<I', b, o + 0x6C + tail)[0] != 0
        piece = struct.unpack_from('<i', b, o + 0x74 + tail)[0]
        mi.raw_motions.append((state, piece, s, e, [s + x for x in ev], loop, ''))
    return mi


def read_ini(path):
    """Text .ini / .in (CP949).  Only what we need for skeleton + motion lookup."""
    with open(path, 'rb') as f:
        text = f.read().decode('cp949', 'replace')
    mi = ModelInfo()
    mi.path = path
    piece = 0
    for line in text.splitlines():
        line = line.split('//')[0].strip()
        if not line.startswith('*'):
            continue
        parts = line.split()
        key, args = parts[0][1:], [a.strip('"') for a in parts[1:]]
        if key == '모양파일' and args:
            mi.model_file = args[0]
        elif key == '동작파일' and args:
            mi.motion_file = args[0]
        elif key == '보조동작파일' and args:
            mi.sub_file = args[0]
        elif key == '파일연결' and args:
            mi.link_file = args[0]
        elif key in ('정밀모양', '보통모양', '저질모양'):
            mi.lod[('정밀모양', '보통모양', '저질모양').index(key)].extend(args)
        elif key == '동작모음':
            piece += 1
        elif key.endswith('동작') or key[-1:].isdigit() or re.search('동작\\d*[a-z]?$', key):
            nums = [int(a) for a in args if a.isdigit()]
            if len(nums) >= 2 and piece:
                label = 'motion'
                for kw, en in INI_MOTION_WORDS:
                    if key.startswith(kw):
                        label = en
                        break
                mi.raw_motions.append((0, piece, nums[0], nums[1], nums[2:6], '반복' in args, label))
    return mi


def read_info(path):
    return read_inx(path) if path.lower().endswith('.inx') else read_ini(path)


def smb_segments(path):
    """(start_tick, end_tick) of every glued motion piece stored in the .smb header."""
    with open(path, 'rb') as f:
        b = f.read(0x22C)
    n = struct.unpack_from('<i', b, 0x28)[0]
    if not 0 <= n <= 32:
        return []
    return [struct.unpack_from('<2i', b, 0x2C + 16 * i) for i in range(n)]


# ----------------------------------------------------------------------------- lookup
def _ci_file(folder, name):
    try:
        for n in os.listdir(folder):
            if n.lower() == name.lower():
                return os.path.join(folder, n)
    except OSError:
        pass
    return None


def _smb_for(folder, ase_name):
    base = os.path.splitext(os.path.basename(ase_name.replace('\\', '/')))[0]
    return _ci_file(folder, base + '.smb')


def player_class(name):
    """Class skeleton number (1..8) from a player body/head/costume file name."""
    m = _PLAYER_RE.match(name)
    if not m:
        return None
    return CLASS_SKELETON.get((m.group(1).lower(), m.group(4).lower()))


class Rig(object):
    """Everything needed to animate one skinned model."""

    def __init__(self):
        self.smb = None           # skeleton / motion file
        self.info = None          # ModelInfo with the motion table (or None)
        self.how = ''             # human-readable reason the skeleton was chosen
        self.lod_high = []        # object names of the high-detail level (empty = all)
        self.shared = False       # True for player class skeletons (m1..m8)


def find_rig(smd_path, bone_names=()):
    """Pick the skeleton (.smb) and motion table for a skinned .smd."""
    folder = os.path.dirname(os.path.abspath(smd_path))
    base = os.path.splitext(os.path.basename(smd_path))[0]
    rig = Rig()

    # 1) an .inx / .ini in the same folder whose model file is this .smd
    infos = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for n in names:
        if n.lower().endswith(('.inx', '.ini')):
            try:
                mi = read_info(os.path.join(folder, n))
            except Exception:
                continue
            infos.append(mi)
    for mi in sorted(infos, key=lambda m: not m.path.lower().endswith('.inx')):
        mf = os.path.splitext(os.path.basename(mi.model_file.replace('\\', '/')))[0]
        if mf.lower() == base.lower() and mi.motion_file:
            smb = _smb_for(folder, mi.motion_file)
            if smb:
                rig.smb, rig.info, rig.lod_high = smb, mi, list(mi.lod[0])
                rig.how = 'motion file of %s' % os.path.basename(mi.path)
                break
        if mf.lower() == base.lower() and mi.link_file:
            link = _ci_file(folder, os.path.splitext(mi.link_file)[0] + '.inx') or \
                _ci_file(folder, mi.link_file)
            if link:
                li = read_info(link)
                smb = _smb_for(folder, li.motion_file)
                if smb:
                    rig.smb, rig.info, rig.lod_high = smb, li, list(mi.lod[0])
                    rig.shared = True
                    rig.how = '%s -> %s' % (os.path.basename(mi.path), os.path.basename(link))
                    break
    # 2) player body / head / costume: shared class skeleton
    if rig.smb is None:
        cls = player_class(base)
        if cls:
            smb = _ci_file(folder, 'm%d.smb' % cls)
            if smb:
                rig.smb = smb
                rig.shared = True
                rig.how = 'class skeleton m%d (%s)' % (cls, CLASS_NAMES[cls])
                for nm in ('M%dBip.inx' % cls, 'M%dBip.in' % cls):
                    p = _ci_file(folder, nm)
                    if p:
                        rig.info = read_info(p)
                        break
    # 3) same-name .smb
    if rig.smb is None:
        smb = _ci_file(folder, base + '.smb')
        if smb:
            rig.smb, rig.how = smb, 'same name'
    # 4) any .smb in the folder that has every bone the mesh needs
    if rig.smb is None and bone_names:
        from .smdfile import Model
        need = set(bone_names)
        for n in names:
            if n.lower().endswith('.smb'):
                try:
                    have = {o.name for o in Model(os.path.join(folder, n)).objects}
                except Exception:
                    continue
                if need <= have:
                    rig.smb, rig.how = os.path.join(folder, n), 'contains all bones'
                    break
    return rig


def find_rig_for_smb(smb_path):
    """Motion table for a skeleton file itself (Tees.smb, mGknight.smb, m1.smb)."""
    folder = os.path.dirname(os.path.abspath(smb_path))
    base = os.path.splitext(os.path.basename(smb_path))[0].lower()
    rig = Rig()
    rig.smb = smb_path
    rig.how = 'skeleton file'
    try:
        names = sorted(os.listdir(folder), key=lambda n: not n.lower().endswith('.inx'))
    except OSError:
        names = []
    for n in names:
        if n.lower().endswith(('.inx', '.ini', '.in')):
            try:
                mi = read_info(os.path.join(folder, n))
            except Exception:
                continue
            mf = os.path.splitext(os.path.basename(mi.motion_file.replace('\\', '/')))[0].lower()
            if mf == base and mi.raw_motions:
                rig.info = mi
                rig.how = 'motion table of %s' % n
                break
    return rig
