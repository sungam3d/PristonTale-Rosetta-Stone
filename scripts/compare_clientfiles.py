"""C# whole-client output == what smdanim/clientfiles.py makes of the same files?

    smd2ase --client <client> --no-models --no-textures -o <out>
    python compare_clientfiles.py <client> <out>

Rebuilds every sound, text and model info file with the Python code (the same rules as
ClientConvert.Run) and compares it byte for byte with the C# output, including <out>\\_server.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smdanim import clientfiles as cf          # noqa: E402

root, out = sys.argv[1], sys.argv[2]
TEXT = ('.inf', '.ini', '.in', '.sin', '.msg', '.txt', '.lua', '.part', '.cht')
INFO = ('.ini', '.inf', '.in')

files = []
for d, _s, fs in os.walk(root):
    for f in fs:
        files.append(os.path.join(d, f))
by_lower = {f.lower(): f for f in files}


def shipped_source(inx):
    stem = os.path.splitext(inx)[0].lower()
    for e in INFO:
        if stem + e in by_lower:
            return by_lower[stem + e]
    return None


def source_ext(rel):
    r = rel.lower()
    stem = os.path.splitext(os.path.basename(r))[0]
    if '\\tmabcd\\' in r or r.startswith('tmabcd\\'):
        if len(stem) > 4 and stem[0] == 'm' and stem.endswith('bip') and stem[1:-3].isdigit():
            return '.in'
        return '.inf'
    return '.ini'


expect = {}                                    # output-relative path -> bytes
handled = {shipped_source(f) for f in files if f.lower().endswith('.inx')} - {None}
for f in files:
    rel = os.path.relpath(f, root)
    ext = os.path.splitext(f)[1].lower()
    if ext in ('.wav', '.bgm'):
        expect[rel + '.wav' if ext == '.bgm' else rel] = cf.decode_wav(open(f, 'rb').read())     # (music: Name.bgm.wav)
    elif ext == '.inx':
        b = open(f, 'rb').read()
        mi = cf.read_inx(b)
        src = shipped_source(f)
        if src:
            raw = open(src, 'rb').read()
            srel = os.path.relpath(src, root)
            try:
                same = cf.compile_ini(cf.read_text(raw), rel, mi.layout.rec) == b
            except Exception:
                same = False
            if same:
                expect[srel] = cf.text_to_utf8(raw)
                expect[os.path.join('_server', srel)] = cf.text_to_cp949(raw)
                continue
            s0, e0 = os.path.splitext(srel)
            expect[s0 + '.shipped' + e0] = cf.text_to_utf8(raw)
            trel = srel
        else:
            trel = os.path.splitext(rel)[0] + source_ext(rel)
        text = cf.inx_to_ini(mi, rel).encode(cf.CP, 'replace')
        expect[trel] = cf.text_to_utf8(text)
        expect[os.path.join('_server', trel)] = text
    elif ext in TEXT and f not in handled:
        raw = open(f, 'rb').read()
        if not cf.is_text(raw):
            continue
        expect[rel] = cf.text_to_utf8(raw)
        if ext in INFO and rel.lower().startswith('char\\'):
            expect[os.path.join('_server', rel)] = cf.text_to_cp949(raw)

got = set()
for d, _s, fs in os.walk(out):
    for f in fs:
        got.add(os.path.relpath(os.path.join(d, f), out))
same = differ = missing = 0
shown = 0
for rel, data in sorted(expect.items()):
    p = os.path.join(out, rel)
    if rel not in got and not os.path.isfile(p):
        missing += 1
        if shown < 10:
            shown += 1
            print('missing:', rel)
        continue
    got.discard(rel)
    if open(p, 'rb').read() == data:
        same += 1
    else:
        differ += 1
        if shown < 10:
            shown += 1
            print('differs:', rel)
extra = [g for g in got if not g.lower().endswith('missing_textures.txt')]
for g in sorted(extra)[:10]:
    print('extra:', g)
print('%d identical, %d differ, %d missing, %d extra (of %d expected)' % (same, differ, missing, len(extra), len(expect)))
