"""Everything else in a Priston Tale client folder: sounds, text files and model info.

  * .wav   the client's sound effects start with "JODO" instead of "RIFF"; the rest of the
           file is a normal PCM wave.  .bgm (music) files are already normal waves.
  * text   .inf .ini .in .sin .msg .txt ... are Korean text in code page 949 (CP949):
           readable copies are written as UTF-8.
  * .inx   the compiled form of a model's .ini / .inf / .in (smMODELINFO, fileread.cpp
           AddModelDecode): model + motion files, detail levels and the motion table, with the
           start/end frames scrambled with a checksum of the file's path (MotionKeyWordEncode).
           read_inx() undoes that, inx_to_ini() writes the text the game compiles it from, and
           compile_ini() builds the .inx again exactly as the game does.
"""

import os
import re
import struct

CP = 'cp949'
EXT = 10                          # CHRMOTION_EXT: motion slots below this are unused
MOTION_MAX = 512
TALK_MAX = 30
NPC_RATE_MAX = 30

# CHRMOTION_STATE_* -> the word that makes AddModelDecode pick that state (order matters there:
# a later match wins, so each word must contain only its own keyword)
STATE_WORD = {
    0x40: '서있기', 0x50: '걷는', 0x60: '뛰는', 0x80: '떨어지는', 0x100: '공격', 0x110: '타격',
    0x120: '죽기', 0x130: '가끔', 0x140: '먹기', 0x150: '기술', 0x170: '작은착지', 0x180: '큰착지',
    0x200: '다시시작', 0x210: '워프', 0x220: '만세', 1: '기타',
}
AUTO_REPEAT = (0x40, 0x50, 0x60)  # stand / walk / run loop by themselves
TALK_WORD = {
    0x400: '아표정', 0x410: '이표정', 0x420: '오표정', 0x430: '눈깜빡표정', 0: '무표정(작동않함)',
    0x440: '웃는표정', 0x450: '화난표정', 0x460: '슬픈표정', 0x470: '놀란표정', 0x480: '고유표정',
    0x490: '특별표정',
}
# *적용직업 (BitMaskJobNames, plus the classes added after the 2012 source)
JOB_BITS = [('Fighter', 0x01), ('Mechanician', 0x02), ('Archer', 0x04), ('Pikeman', 0x08),
            ('Atalanta', 0x10), ('Knight', 0x20), ('Magician', 0x40), ('Priest', 0x80),
            ('Assassin', 0x100), ('Shaman', 0x200), ('MartialArtist', 0x400)]


# ----------------------------------------------------------------------------- small helpers
def speed_sum(name):
    """GetSpeedSum (character.cpp): the checksum of a game-relative path, case-insensitive."""
    s2 = dw = cnt = 0
    for ch in name.encode(CP, 'replace'):
        if 97 <= ch <= 122:
            ch -= 0x20
        s2 += ch * (cnt + 1)
        dw += ch * cnt * cnt
        cnt += 1
    return ((dw << 24) | (cnt << 16) | s2) & 0xFFFFFFFF


def decode_wav(data):
    """Client sound -> playable .wav (only the first 4 bytes differ)."""
    if data[:4] == b'JODO':
        return b'RIFF' + data[4:]
    return data


def encode_wav(data):
    if data[:4] == b'RIFF':
        return b'JODO' + data[4:]
    return data


def _utf16(data):
    """Text saved as UTF-16 (Notepad's "Unicode"), or None."""
    if data[:2] == b'\xff\xfe':
        return data[2:].decode('utf-16-le', 'replace')
    if data[:2] == b'\xfe\xff':
        return data[2:].decode('utf-16-be', 'replace')
    return None


def is_text(data):
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return True
    return b'\0' not in data[:4096]


def text_to_utf8(data):
    """CP949 text -> UTF-8 (with BOM, so Notepad and editors pick the right code page).  Plain
    ASCII, text that already is UTF-8 and bytes that are not clean CP949 stay as they are."""
    if data[:3] == b'\xef\xbb\xbf' or max(data, default=0) < 0x80:
        return data
    try:
        data.decode('utf-8')
        return data
    except UnicodeDecodeError:
        pass
    try:
        return b'\xef\xbb\xbf' + data.decode(CP).encode('utf-8')
    except UnicodeDecodeError:
        return data


def text_to_cp949(data):
    """UTF-8 (with a BOM, or valid UTF-8 with Korean in it) or UTF-16 -> CP949 text the game reads."""
    u16 = _utf16(data)
    if u16 is not None:
        return u16.encode(CP, 'replace')
    if data[:3] == b'\xef\xbb\xbf':
        return data[3:].decode('utf-8', 'replace').encode(CP, 'replace')
    if max(data, default=0) < 0x80:
        return data
    try:
        return data.decode('utf-8').encode(CP, 'replace')
    except UnicodeDecodeError:
        return data


def read_text(data):
    """Text bytes as a str: UTF-16 or UTF-8 when marked, UTF-8 when valid, CP949 otherwise."""
    u16 = _utf16(data)
    if u16 is not None:
        return u16
    if data[:3] == b'\xef\xbb\xbf':
        return data[3:].decode('utf-8', 'replace')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode(CP, 'replace')


def _cstr(b):
    return b.split(b'\0', 1)[0].decode(CP, 'replace')


def _put_str(buf, off, s, size):
    raw = s.encode(CP, 'replace')[:size - 1]
    buf[off:off + size] = raw + b'\0' * (size - len(raw))


def _strcpy(buf, off, s):
    """lstrcpy: a name longer than its slot runs on into the next one (the next copy then
    overwrites the overflow, as in the game)."""
    raw = s.encode(CP, 'replace') + b'\0'
    buf[off:off + len(raw)] = raw


# ----------------------------------------------------------------------------- layout
class Layout(object):
    """smMOTIONINFO: 120 bytes (2012 clients, 52 one-byte item codes) or 172 bytes (later
    clients, 52 two-byte item codes)."""

    def __init__(self, rec):
        self.rec = rec
        self.wide = rec == 172
        self.item_bytes = 104 if self.wide else 52
        o = 40 + self.item_bytes
        self.job, self.skill, self.mappos, self.repeat, self.key, self.frame = o, o + 4, o + 12, o + 16, o + 20, o + 24
        self.motions = 0x18C
        tail = self.motions + MOTION_MAX * rec
        self.count, self.ftk, self.lfk = tail, tail + 4, tail + 8
        self.link, self.talk_link, self.talk_file = tail + 12, tail + 76, tail + 140
        self.talk = tail + 204
        self.talk_count = self.talk + TALK_MAX * rec
        self.npc_rate = self.talk_count + 4
        self.npc_rate_cnt = self.npc_rate + 4 * NPC_RATE_MAX
        self.talk_rate = self.npc_rate_cnt + 400
        self.talk_rate_cnt = self.talk_rate + 4 * TALK_MAX
        self.size = self.talk_rate_cnt + 800


LAYOUTS = {Layout(r).size: Layout(r) for r in (120, 172)}


class Motion(object):
    def __init__(self):
        self.state = 0
        self.start = self.end = 0
        self.events = [0, 0, 0, 0]       # ticks from the start frame
        self.item_count = 0
        self.items = []
        self.jobs = 0
        self.jobs_set = False            # a *적용직업 line came (it overwrites an item overflow)
        self.skills = [0] * 8
        self.map_pos = 0
        self.repeat = 0
        self.key = 0
        self.piece = 0                   # MotionFrame: which *동작모음 (1-based; talk: 0-based)


class ModelInfo(object):
    def __init__(self, layout):
        self.layout = layout
        self.model_file = self.motion_file = self.sub_file = ''
        self.lod = ([], [], [])
        self.motions = []                # index = slot; slots below EXT are unused
        self.link_file = self.talk_link = self.talk_file = ''
        self.talk = []
        self.npc_rate = [0] * NPC_RATE_MAX
        self.talk_rate = [0] * TALK_MAX
        self.ftk = self.lfk = 0


def _read_motion(b, o, L):
    m = Motion()
    m.state, kw1, sf, kw2, ef = struct.unpack_from('<5I', b, o)
    m.raw = (kw1, sf, kw2, ef)
    m.start, m.end = sf, ef
    m.events = list(struct.unpack_from('<4i', b, o + 20))     # ticks from the start, can be < 0
    m.item_count = struct.unpack_from('<i', b, o + 36)[0]
    n = max(0, min(m.item_count, 52))
    if L.wide:
        m.items = list(struct.unpack_from('<%dH' % n, b, o + 40))
    else:
        m.items = list(b[o + 40:o + 40 + n])
    m.jobs = struct.unpack_from('<I', b, o + L.job)[0]
    m.skills = list(b[o + L.skill:o + L.skill + 8])
    m.map_pos = struct.unpack_from('<i', b, o + L.mappos)[0]
    m.repeat = struct.unpack_from('<I', b, o + L.repeat)[0]
    m.key = b[o + L.key]
    m.piece = struct.unpack_from('<i', b, o + L.frame)[0]
    return m


def _unscramble(m):
    """MotionKeyWordDecode: (start, end) frames and the path checksum they were mixed with."""
    kw1, sf, kw2, ef = m.raw
    code = None
    if kw1 or sf:
        code = ((kw1 & 0xff000000) | ((kw1 & 0x0000ff00) << 8) | (sf & 0x0000ff00) | ((sf & 0xff000000) >> 24)) & 0xFFFFFFFF
        m.start = (((sf & 0xff) << 24) | (sf & 0x00ff0000) | ((kw1 & 0x00ff0000) >> 8) | (kw1 & 0xff)) & 0xFFFFFFFF
    if kw2 or ef:
        c2 = (((ef & 0x0000ff00) << 16) | ((ef & 0xff000000) >> 8) | (kw2 & 0x0000ff00) | ((kw2 & 0xff000000) >> 24)) & 0xFFFFFFFF
        code = code if code is not None else c2
        m.end = (((kw2 & 0x00ff0000) << 8) | ((kw2 & 0xff) << 16) | ((ef & 0x00ff0000) >> 8) | (ef & 0xff)) & 0xFFFFFFFF
    return code


def read_inx(path_or_bytes):
    b = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, 'rb').read()
    L = LAYOUTS.get(len(b))
    if L is None:
        raise ValueError('not an .inx (%d bytes)' % len(b))
    mi = ModelInfo(L)
    mi.model_file, mi.motion_file, mi.sub_file = _cstr(b[0:64]), _cstr(b[64:128]), _cstr(b[128:192])
    for k in range(3):
        o = 192 + 68 * k
        n = struct.unpack_from('<i', b, o)[0]
        # a name of 16 or more characters runs on into the next slot; the next name (if any)
        # overwrote the overflow, the last one keeps it
        n = max(0, min(n, 4))
        for j in range(n):
            end = o + 20 + 16 * j if j < n - 1 else o + 68
            mi.lod[k].append(_cstr(b[o + 4 + 16 * j:end] + b'\0'))
    mi.folder = ''
    for f in (mi.model_file, mi.motion_file):
        if '\\' in f:
            mi.folder = f[:f.rfind('\\') + 1]
            break
    count = struct.unpack_from('<I', b, L.count)[0]
    mi.ftk, mi.lfk = struct.unpack_from('<2I', b, L.ftk)
    mi.link_file, mi.talk_link, mi.talk_file = _cstr(b[L.link:L.link + 64]), _cstr(b[L.talk_link:L.talk_link + 64]), _cstr(b[L.talk_file:L.talk_file + 64])
    talk_count = struct.unpack_from('<I', b, L.talk_count)[0]
    mi.motions = [_read_motion(b, L.motions + L.rec * k, L) for k in range(min(count, MOTION_MAX))]
    mi.talk = [_read_motion(b, L.talk + L.rec * k, L) for k in range(min(talk_count, TALK_MAX))]
    scrambled = count > EXT and talk_count <= EXT
    mi.code = None
    for m in mi.motions[EXT:]:
        if scrambled:
            c = _unscramble(m)
            mi.code = mi.code if mi.code is not None else c
    mi.npc_rate = list(struct.unpack_from('<%di' % NPC_RATE_MAX, b, L.npc_rate))
    mi.talk_rate = list(struct.unpack_from('<%di' % TALK_MAX, b, L.talk_rate))
    return mi


# ----------------------------------------------------------------------------- tables
_ITEMS = None
_SKILLS = None


def _source_tables():
    """Item and skill names in the order the game indexes them (from the server source, when
    it is around: X:\\...\\sinItem.cpp and fileread.cpp).  Missing -> numbers are written."""
    global _ITEMS, _SKILLS
    if _ITEMS is not None:
        return _ITEMS, _SKILLS
    _ITEMS, _SKILLS = [], []
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, 'data', 'items.txt'),):
        if os.path.isfile(p):
            _ITEMS = [l.strip() for l in open(p, encoding='utf-8') if l.strip()]
    for p in (os.path.join(here, 'data', 'skills.txt'),):
        if os.path.isfile(p):
            _SKILLS = [l.strip() for l in open(p, encoding='utf-8') if l.strip()]
    return _ITEMS, _SKILLS


def _job_names(bits):
    out = [n for n, b in JOB_BITS if bits & b]
    rest = bits & ~sum(b for _n, b in JOB_BITS)
    k = 0x100
    while rest:
        if rest & k:
            out.append('0x%X' % k)
            rest &= ~k
        k <<= 1
    return out


# ----------------------------------------------------------------------------- .inx -> .ini
def _rel_name(path, folder):
    """A path stored with the .ini's folder in front -> as written in the .ini."""
    p = path.replace('/', '\\')
    if folder and p.lower().startswith(folder.lower()):
        return p[len(folder):]
    return p


def inx_to_ini(mi, rel_path=''):
    """The text an .inx is compiled from (CP949 words; return a str).  rel_path: the .inx's
    path from the game folder (char\\monster\\Tees\\Tees.inx), to write file names the way
    the .ini writes them (without its folder)."""
    items, skills = _source_tables()
    folder = getattr(mi, 'folder', '') or os.path.dirname(rel_path.replace('/', '\\'))
    if folder and not folder.endswith('\\'):
        folder += '\\'
    out = ['// %s - rebuilt from the compiled .inx by PristonTale - Rosetta Stone' % (os.path.basename(rel_path) or 'model'), '']
    if mi.model_file:
        out.append('*모양파일\t%s' % _rel_name(mi.model_file, folder))
    for word, names in zip(('*정밀모양', '*보통모양', '*저질모양'), mi.lod):
        if names:
            out.append(word + '\t' + '\t'.join('"%s"' % n for n in names))
    if mi.sub_file:
        out.append('*보조동작파일\t"%s"' % _rel_name(mi.sub_file, folder))
    if mi.link_file:
        out.append('*파일연결\t%s' % _rel_name(mi.link_file, folder))
    if mi.talk_link:
        out.append('*표정파일연결\t"%s"' % _rel_name(mi.talk_link, folder))
    if mi.talk_file:
        out.append('*표정파일\t"%s"' % _rel_name(mi.talk_file, folder))
    if mi.motion_file:
        out += ['', '*동작파일\t%s' % _rel_name(mi.motion_file, folder)]
    # Body motions belong to the n-th *동작모음 before them (MotionFrame = n), face motions to the
    # (n+1)-th (MotionFrame = n - 1): both lists are walked together, file by file.
    body = list(enumerate(mi.motions[EXT:], EXT))
    face = list(enumerate(mi.talk[EXT:], EXT))
    last = max([m.piece for _i, m in body] + [m.piece + 1 for _i, m in face] + [0])
    single = last == 1 and not face
    motion_base = os.path.splitext(os.path.basename(mi.motion_file.replace('\\', '/')))[0] or 'motion'
    count = {}
    for piece in range(0, last + 1):
        if piece:
            name = os.path.basename(mi.motion_file.replace('\\', '/')) if single else '%s_%02d.ASE' % (motion_base, piece)
            out += ['', '*동작모음\t"%s"' % name + ('' if single else '\t// (the original name is not kept in the .inx)')]
        for i, m in body:
            if m.piece == piece:
                out += _body_lines(mi, i, m, count, items, skills)
        for i, m in face:
            if m.piece + 1 == piece:
                out.append(_face_line(mi, i, m))
    out += ['', '*끝', '']
    return '\r\n'.join(out)


def _flag(m, rate, auto_repeat=()):
    """The token after the frames: a key letter, or 반복 (repeat); a word in front of a rate."""
    flag = None
    if m.key and 32 <= m.key < 127 and chr(m.key) != '(':
        flag = chr(m.key)
    elif m.repeat and m.state not in auto_repeat:
        flag = '반복'
    if rate and flag is None:
        flag = '비율'                                       # any word: the next token is the rate
    out = [flag] if flag else []
    if rate:
        out.append('(%d)' % rate)
    return out


def _item_name(items, c):
    """An item code as its name, or #code when the name would not lead back to this code (not in
    the table, or listed twice: the client's table is not quite the 2012 source's)."""
    if c < len(items) and items.index(items[c]) == c and items[c]:
        return items[c]
    return '#%d' % c


def _body_lines(mi, i, m, count, items, skills):
    word = STATE_WORD.get(m.state, '기타')
    count[word] = count.get(word, 0) + 1
    label = '*%s동작%s' % (word, '' if count[word] == 1 else count[word] - 1)
    end = m.end + 8 if m.state == 0x120 else m.end          # AddModelDecode takes 8 off a death
    parts = [label, str(m.start), str(end)] + [str(int(e / 160) + m.start) for e in m.events if e]
    parts += _flag(m, mi.npc_rate[i] if i < NPC_RATE_MAX else 0, AUTO_REPEAT)
    out = ['\t'.join(parts)]
    if m.item_count or m.jobs or m.map_pos:
        if m.item_count == 0:
            out.append('*착용무기\t모두')
        else:
            none = 0xFFFF if mi.layout.wide else 0xFF
            names = ['없음' if c == none else _item_name(items, c) for c in m.items]
            names += names[-1:] * max(0, m.item_count - len(names))   # (overwritten in the file)
            out.append('*착용무기\t' + '\t'.join(names))
        if m.jobs:
            out.append('*적용직업\t' + '\t'.join(_job_names(m.jobs)))
        if m.map_pos:
            out.append('*해당위치\t' + {1: '마을', 2: '필드'}.get(m.map_pos, '마을\t필드'))
    if m.state == 0x150 and any(m.skills):
        low = [n.lower() for n in skills]                   # (the game compares skill names case-blind)
        out.append('*적용기술\t' + '\t'.join('#%d' % s if _item_name(low, s).startswith('#') else skills[s]
                                             for s in m.skills if s))
    return out


def _face_line(mi, i, m):
    parts = ['*' + TALK_WORD.get(m.state, '고유표정'), str(m.start), str(m.end)]
    parts += [str(int(e / 160) + m.start) for e in m.events if e]
    return '\t'.join(parts + _flag(m, mi.talk_rate[i] if i < TALK_MAX else 0))


# ----------------------------------------------------------------------------- .ini -> .inx
INI_COMMANDS = ['*동작파일', '*동작모음', '*모양파일', '*모양이름', '*파일연결', '*보조동작파일',
                '*정밀모양', '*보통모양', '*저질모양', '*XX걷는동작', '*XX서있기동작',
                '*착용무기', '*적용직업', '*해당위치', '*적용기술', '*표정파일연결', '*표정파일', '*표정모음']
# AddModelDecode's checks in its order (a later one wins)
_STATE_CHECKS = [(('뛰는',), 0x60, True), (('공격',), 0x100, False), (('죽기',), 0x120, False),
                 (('죽는',), 0x120, False), (('타격',), 0x110, False), (('데미지',), 0x110, False),
                 (('막기',), 0x110, False), (('가끔',), 0x130, False), (('떨어',), 0x80, False),
                 (('작은착지',), 0x170, False), (('큰착지',), 0x180, False),
                 (('*서있기', '*정지'), 0x40, True), (('*걷는',), 0x50, True), (('다시시작',), 0x200, False),
                 (('먹기',), 0x140, False), (('기술',), 0x150, False), (('울기', '워프'), 0x210, False),
                 (('만세',), 0x220, False)]
_TALK_CHECKS = [('아표정', 0x400), ('이표정', 0x410), ('오표정', 0x420), ('눈깜빡표정', 0x430),
                ('무표정(작동않함)', 0), ('웃는표정', 0x440), ('화난표정', 0x450), ('슬픈표정', 0x460),
                ('놀란표정', 0x470), ('고유표정', 0x480), ('특별표정', 0x490)]


def _words(line):
    """GetWord: whitespace-separated (space / tab), stopping at the line end."""
    return line.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ').split(' ')


def _tokens(line):
    return [w for w in _words(line) if w]


def _string_arg(rest):
    """The engine's GetString after a quote: everything up to the closing quote."""
    rest = rest.lstrip(' \t')
    if rest.startswith('"'):
        end = rest.find('"', 1)
        return rest[1:end] if end > 0 else rest[1:].rstrip('\r\n')
    t = _tokens(rest)
    return t[0] if t else ''


def _set_motion(m, args):
    """SetIniMotionInfo: start end [events...] [flag] [(rate)] -> rate or None."""
    def num(s):
        mm = re.match(r'-?\d+', s)
        return int(mm.group(0)) if mm else 0
    it = iter(args + [''] * 8)
    m.start = num(next(it))
    m.end = num(next(it))
    m.events = [0, 0, 0, 0]
    n = 0
    tok = next(it)
    while tok[:1].isdigit() and n < 4:
        m.events[n] = (num(tok) - m.start) * 160
        n += 1
        tok = next(it)
    if tok == '반복':
        m.repeat = 1
    if tok and tok[0] != '(' and ' ' <= tok[0] <= '\x7f':
        m.key = ord(tok[0])
    rate = None
    tok = next(it)
    if 2 < len(tok) < 6 and tok[0] == '(' and tok[-1] == ')':
        rate = min(int(tok[1:-1]) if tok[1:-1].isdigit() else 0, 100)
    return rate


def compile_ini(text, rel_inx, layout=172, folder=None, code=None):
    """AddModelDecode + the keyword encoding: .ini / .inf / .in text -> .inx bytes.  rel_inx:
    the .inx path from the game folder (its checksum is mixed into the file); folder: how the
    game spelled the folder it puts in front of file names (default: rel_inx's; only the case
    can differ, which the game ignores); code: the path checksum to use instead of rel_inx's
    (an .inx compiled somewhere else and copied keeps the old one)."""
    items, skills = _source_tables()
    item_index = {}
    for i, n in enumerate(items):
        item_index.setdefault(n, i)
    skill_index = {}
    for i, n in enumerate(skills):
        skill_index.setdefault(n.lower(), i)
    L = Layout(layout)
    rel_inx = rel_inx.replace('/', '\\')
    if folder is None:
        folder = os.path.dirname(rel_inx)
        folder = folder + '\\' if folder else ''
    mi = ModelInfo(L)
    mi.motions = [Motion() for _ in range(EXT)]
    mi.talk = [Motion() for _ in range(EXT)]
    pieces = 0
    last = 0
    for line in text.replace('\r\n', '\n').split('\n'):
        line = line[:511]
        ws = _words(line)
        head = next((w for w in ws if w), '')
        rest = line[line.find(head) + len(head):] if head else ''
        args = _tokens(rest)
        try:
            cmd = INI_COMMANDS.index(head)
        except ValueError:
            cmd = -1
        if cmd < 0:
            if head.startswith('*') and '동작' in head:
                if len(mi.motions) < MOTION_MAX:
                    m = Motion()
                    rate = _set_motion(m, args)
                    if rate is not None and len(mi.motions) < NPC_RATE_MAX:
                        mi.npc_rate[len(mi.motions)] = rate
                    m.piece = pieces
                    m.state = 1
                    for words, st, rep in _STATE_CHECKS:
                        if any(w in head for w in words):
                            m.state = st
                            if rep:
                                m.repeat = 1
                    if m.state == 0x150:
                        m.skills[0] = 0
                    if m.state == 0x120:
                        m.end = (m.end - 8) & 0xFFFFFFFF
                    last = len(mi.motions)
                    mi.motions.append(m)
            elif head.startswith('*') and '표정' in head and pieces:
                if len(mi.talk) < TALK_MAX:
                    m = Motion()
                    rate = _set_motion(m, args)
                    if rate is not None:
                        mi.talk_rate[len(mi.talk)] = rate
                    m.piece = pieces - 1
                    m.state = 1
                    for w, st in _TALK_CHECKS:
                        if w in head:
                            m.state = st
                            break
                    mi.talk.append(m)
            continue
        if cmd == 0:
            mi.motion_file = folder + _string_arg(rest)
        elif cmd in (1, 17):
            pieces += 1
        elif cmd == 2:
            mi.model_file = folder + (args[0] if args else '')
        elif cmd == 4:
            mi.link_file = folder + (args[0] if args else '')
        elif cmd == 5:
            mi.sub_file = folder + _string_arg(rest)
        elif cmd in (6, 7, 8):
            grp = mi.lod[cmd - 6]
            r = rest
            for _ in range(4):
                if not _tokens(r):
                    break
                s = r.lstrip(' \t')
                if s.startswith('"'):
                    end = s.find('"', 1)
                    name, r = s[1:end], s[end + 1:]
                else:
                    name = _tokens(s)[0]
                    r = s[len(name):]
                if len(grp) < 4:
                    grp.append(name)
        elif cmd == 11:
            m = mi.motions[last]
            for tok in args:
                if tok == '모두':
                    m.item_count = 0
                    m.items = []
                    break
                if tok == '없음':
                    m.items.append(0xFFFF if L.wide else 0xFF)
                elif tok in item_index:
                    m.items.append(item_index[tok])
                elif re.match(r'#\d+$', tok):                  # an item code by number (our own form)
                    m.items.append(int(tok[1:]))
                m.item_count = len(m.items)
        elif cmd == 12:
            m = mi.motions[last]
            m.jobs = 0
            m.jobs_set = True
            for tok in args:
                for n, b in JOB_BITS:
                    if tok.lower() == n.lower():
                        m.jobs |= b
                        break
        elif cmd == 13:
            m = mi.motions[last]
            v = 0
            for tok in args[:2]:
                v |= 1 if tok == '마을' else 2 if tok == '필드' else 0
            if v == 0 or m.state == 0x150:
                v = 3
            m.map_pos = v
        elif cmd == 14:
            m = mi.motions[last]
            if m.state == 0x150:
                k = 0
                for tok in args:
                    if k >= 7:
                        break
                    if tok.lower() in skill_index:
                        m.skills[k] = skill_index[tok.lower()]
                        k += 1
                    elif re.match(r'#\d+$', tok):              # a skill by number (our own form)
                        m.skills[k] = int(tok[1:]) & 0xFF
                        k += 1
                m.skills[k] = 0
        elif cmd == 15:
            mi.talk_link = folder + _string_arg(rest)
        elif cmd == 16:
            mi.talk_file = folder + _string_arg(rest)
    _balance_rates(mi)
    return _write_inx(mi, rel_inx, code)


def _balance_rates(mi):
    """The NpcMotionRate fix-up of AddModelDecode: the largest share absorbs the difference to
    100, then NpcMotionRateCnt lists each motion index rate times."""
    mi.npc_rate_cnt = [0] * 100
    if mi.npc_rate[EXT]:
        idx = range(EXT, min(len(mi.motions), NPC_RATE_MAX))
        best, pos, tot = 0, 0, 0
        for i in idx:
            if best < mi.npc_rate[i]:
                best, pos = mi.npc_rate[i], i
            tot += mi.npc_rate[i]
        if tot > 100:
            best -= tot - 100
            if best <= 0:
                mi.npc_rate[EXT] = 0
            else:
                mi.npc_rate[pos] = best
        elif tot < 100:
            mi.npc_rate[pos] = best + 100 - tot
        if mi.npc_rate[EXT]:
            k = 0
            for i in idx:
                for _ in range(mi.npc_rate[i]):
                    if k < 100:
                        mi.npc_rate_cnt[k] = i
                    k += 1
    # face motions: the same per face-motion file (MotionFrame 0 / 1), on a copy of the rates
    mi.talk_rate_cnt = [[0] * 100, [0] * 100]
    if mi.talk_rate[EXT]:
        for f in (0, 1):
            idx = [i for i in range(EXT, len(mi.talk)) if mi.talk[i].piece == f]
            rate = {i: (mi.talk_rate[i] if i < TALK_MAX else 0) for i in idx}
            best, pos, tot = 0, None, 0
            for i in idx:
                if best < rate[i]:
                    best, pos = rate[i], i
                tot += rate[i]
            if tot > 100:
                best -= tot - 100
                if best <= 0:
                    mi.talk_rate[EXT] = 0
                elif pos is not None:
                    rate[pos] = best
            elif tot < 100 and pos is not None:
                rate[pos] = best + 100 - tot
            if mi.talk_rate[EXT]:
                k = 0
                for i in idx:
                    for _ in range(rate[i]):
                        if k < 100:
                            mi.talk_rate_cnt[f][k] = i
                        k += 1


def _write_motion(buf, o, m, L, code):
    sf, ef, kw1, kw2 = m.start & 0xFFFFFFFF, m.end & 0xFFFFFFFF, 0, 0
    if code is not None:
        if sf:
            kw1 = ((code & 0xff000000) | ((sf & 0x0000ff00) << 8) | ((code & 0x00ff0000) >> 8) | (sf & 0xff)) & 0xFFFFFFFF
            sf = (((code & 0xff) << 24) | (sf & 0x00ff0000) | (code & 0x0000ff00) | ((sf & 0xff000000) >> 24)) & 0xFFFFFFFF
        if ef:
            kw2 = (((code & 0xff) << 24) | ((ef & 0xff000000) >> 8) | (code & 0x0000ff00) | ((ef & 0x00ff0000) >> 16)) & 0xFFFFFFFF
            ef = (((code & 0x00ff0000) << 8) | ((ef & 0x0000ff00) << 8) | ((code & 0xff000000) >> 16) | (ef & 0xff)) & 0xFFFFFFFF
    struct.pack_into('<5I', buf, o, m.state, kw1, sf, kw2, ef)
    struct.pack_into('<4I', buf, o + 20, *[e & 0xFFFFFFFF for e in m.events])
    struct.pack_into('<i', buf, o + 36, m.item_count)
    items = m.items[:60]
    if L.wide:
        struct.pack_into('<%dH' % len(items), buf, o + 40, *[i & 0xFFFF for i in items])
    else:
        buf[o + 40:o + 40 + len(items)] = bytes(i & 0xFF for i in items)
    if len(items) <= 52 or m.jobs_set:
        struct.pack_into('<I', buf, o + L.job, m.jobs)
    buf[o + L.skill:o + L.skill + 8] = bytes(m.skills[:8])
    struct.pack_into('<iI', buf, o + L.mappos, m.map_pos, m.repeat)
    buf[o + L.key] = m.key & 0xFF
    struct.pack_into('<i', buf, o + L.frame, m.piece)


def _write_inx(mi, rel_inx, code=None):
    L = mi.layout
    buf = bytearray(L.size)
    _put_str(buf, 0, mi.model_file, 64)
    _put_str(buf, 64, mi.motion_file, 64)
    _put_str(buf, 128, mi.sub_file, 64)
    for k in range(3):
        o = 192 + 68 * k
        struct.pack_into('<i', buf, o, len(mi.lod[k]))
        for j, n in enumerate(mi.lod[k][:4]):
            _strcpy(buf, o + 4 + 16 * j, n)
    if code is None:
        code = speed_sum(rel_inx)
    scramble = len(mi.motions) > EXT and len(mi.talk) <= EXT
    for k, m in enumerate(mi.motions[:MOTION_MAX]):
        if k >= EXT:
            _write_motion(buf, L.motions + L.rec * k, m, L, code if scramble else None)
    struct.pack_into('<I', buf, L.count, len(mi.motions))
    # ModelKeyWordEncode
    if mi.link_file:
        link = speed_sum(os.path.splitext(mi.link_file)[0] + '.inx')
        ftk = ((code & 0x00ff0000) << 8) | ((link & 0xff) << 16) | ((code & 0xff) << 8) | ((link & 0xff000000) >> 24)
        lfk = (code & 0xff000000) | ((link & 0x0000ff00) << 8) | (code & 0x0000ff00) | ((link & 0x00ff0000) >> 16)
    else:
        ftk = ((code & 0x0000ff00) << 16) | ((code & 0xff000000) >> 8) | ((code & 0xff) << 8) | ((code & 0x00ff0000) >> 16)
        lfk = 0
    struct.pack_into('<2I', buf, L.ftk, ftk & 0xFFFFFFFF, lfk & 0xFFFFFFFF)
    _put_str(buf, L.link, mi.link_file, 64)
    _put_str(buf, L.talk_link, mi.talk_link, 64)
    _put_str(buf, L.talk_file, mi.talk_file, 64)
    for k, m in enumerate(mi.talk[:TALK_MAX]):
        if k >= EXT:
            _write_motion(buf, L.talk + L.rec * k, m, L, None)
    struct.pack_into('<I', buf, L.talk_count, len(mi.talk))
    struct.pack_into('<%di' % NPC_RATE_MAX, buf, L.npc_rate, *mi.npc_rate)
    struct.pack_into('<100i', buf, L.npc_rate_cnt, *getattr(mi, 'npc_rate_cnt', [0] * 100))
    struct.pack_into('<%di' % TALK_MAX, buf, L.talk_rate, *mi.talk_rate)
    trc = getattr(mi, 'talk_rate_cnt', [[0] * 100, [0] * 100])
    struct.pack_into('<200i', buf, L.talk_rate_cnt, *(trc[0] + trc[1]))
    return bytes(buf)
