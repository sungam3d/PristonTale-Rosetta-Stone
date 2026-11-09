"""Hand-made 'edited' files through smd2ase --to-game; check what the game would read.

    python check_to_game.py        (needs Pillow; writes work\\enc_tests)

Pictures: the game's loaders (smTexture.cpp) are imitated here: BMP = header-decode, pixels at
14 + biSize + palette (bfOffBits ignored), bfSize bytes; TGA = header-decode, raw pixels right after
the 18-byte header.  Sounds: Dxwav.cpp's fixed layouts.  Text: CP949 bytes."""
import io
import os
import shutil
import struct
import subprocess
import sys

from PIL import Image

EXE = r'X:\Projects\SMD-ANIM\src\smd2ase\bin\Release\net48\smd2ase.exe'
W = r'X:\Projects\SMD-ANIM\work\enc_tests'
SRC = os.path.join(W, 'edited')
OUT = os.path.join(W, 'out')
shutil.rmtree(W, ignore_errors=True)
D = os.path.join(SRC, 'char', 'monster', 'Test')
os.makedirs(D)
os.makedirs(os.path.join(SRC, 'wav', 'BGM'))
os.makedirs(os.path.join(SRC, 'wav', 'Effects'))

# a 7x5 picture with distinct pixels (odd width: BMP row padding matters)
img = Image.new('RGB', (7, 5))
for y in range(5):
    for x in range(7):
        img.putpixel((x, y), (x * 30, y * 50, (x * 7 + y * 13) % 256))
imga = img.convert('RGBA')
for y in range(5):
    for x in range(7):
        r, g, b, _ = imga.getpixel((x, y))
        imga.putpixel((x, y), (r, g, b, (x * 40 + y) % 256))


def save(name, data):
    p = os.path.join(D, name)
    with open(p, 'wb') as f:
        f.write(data)


def pil_bytes(im, fmt, **kw):
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


# TGA cases
save('t_plain24.tga', pil_bytes(img, 'TGA'))
save('t_rle24.tga', pil_bytes(img, 'TGA', compression='tga_rle'))
save('t_rle32.tga', pil_bytes(imga, 'TGA', compression='tga_rle'))
raw = bytearray(pil_bytes(img, 'TGA'))
idfield = b'made by an editor'
withid = bytearray(raw[:18]) + idfield + raw[18:]
withid[0] = len(idfield)
save('t_id24.tga', bytes(withid))
save('t_gray8.tga', pil_bytes(img.convert('L'), 'TGA'))

# BMP cases
bmp24 = pil_bytes(img, 'BMP')
save('b_plain24.bmp', bmp24)
# top-down: negative height, rows reversed
off = struct.unpack_from('<I', bmp24, 10)[0]
stride = (7 * 3 + 3) // 4 * 4
rows = [bmp24[off + r * stride: off + (r + 1) * stride] for r in range(5)]
td = bytearray(bmp24[:off]) + b''.join(reversed(rows))
struct.pack_into('<i', td, 22, -5)
save('b_topdown24.bmp', bytes(td))
# gap between header and pixels (bfOffBits further on), bfSize 0
gap = bytearray(bmp24[:off]) + b'\x00' * 16 + bmp24[off:]
struct.pack_into('<I', gap, 10, off + 16)
struct.pack_into('<I', gap, 2, 0)
save('b_gap24.bmp', bytes(gap))
# 32-bit BI_BITFIELDS with a 40-byte header and masks after it
px32 = b''.join(bytes((b, g, r, a)) for y in range(4, -1, -1) for x in range(7)
                for (r, g, b, a) in [imga.getpixel((x, y))])
hdr = struct.pack('<IiiHHIIiiII', 40, 7, 5, 1, 32, 3, len(px32), 2835, 2835, 0, 0)
masks = struct.pack('<III', 0x00FF0000, 0x0000FF00, 0x000000FF)
bf = b'BM' + struct.pack('<IHHI', 14 + 40 + 12 + len(px32), 0, 0, 14 + 40 + 12) + hdr + masks + px32
save('b_bitfields32.bmp', bf)
save('b_16bit.bmp', b'BM' + struct.pack('<IHHI', 14 + 40 + 7 * 2 * 5 + 10, 0, 0, 54) +
     struct.pack('<IiiHHIIiiII', 40, 7, 5, 1, 16, 0, 0, 0, 0, 0, 0) + b'\x00' * 80)


# WAV cases
def wav(chunks, magic=b'RIFF'):
    body = b'WAVE' + b''.join(cid + struct.pack('<I', len(p)) + p + (b'\0' if len(p) & 1 else b'') for cid, p in chunks)
    return magic + struct.pack('<I', len(body)) + body


pcm = struct.pack('<HHIIHH', 1, 1, 22050, 44100, 2, 16)
samples = bytes(range(200))
WD = os.path.join(SRC, 'wav', 'Effects')
open(os.path.join(WD, 'w_plain.wav'), 'wb').write(wav([(b'fmt ', pcm), (b'data', samples)]))
open(os.path.join(WD, 'w_list.wav'), 'wb').write(wav([(b'fmt ', pcm), (b'LIST', b'INFOISFT\x05\x00\x00\x00Lavf\x00\x00'), (b'data', samples)]))
ext = struct.pack('<HHIIHHHHIH14s', 0xFFFE, 1, 22050, 44100, 2, 16, 22, 16, 4, 1,
                  b'\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71')
open(os.path.join(WD, 'w_extensible.wav'), 'wb').write(wav([(b'fmt ', ext), (b'data', samples)]))
open(os.path.join(WD, 'w_fmt18.wav'), 'wb').write(wav([(b'fmt ', pcm + b'\x00\x00'), (b'data', samples)]))
flt = struct.pack('<HHIIHH', 3, 1, 22050, 88200, 4, 32)
open(os.path.join(WD, 'w_float.wav'), 'wb').write(wav([(b'fmt ', flt), (b'data', samples)]))
open(os.path.join(SRC, 'wav', 'BGM', 'Town.bgm.wav'), 'wb').write(wav([(b'fmt ', pcm), (b'LIST', b'INFO'), (b'data', samples)]))
open(os.path.join(SRC, 'wav', 'BGM', 'Ending.wav'), 'wb').write(wav([(b'fmt ', pcm), (b'data', samples)]))

# text cases
ini = ('*모양파일\tTest.smd\r\n*동작파일\tTest.smb\r\n\r\n*동작모음\t"Test.ASE"\r\n'
       '*서있기동작\t10\t50\r\n*공격동작\t60\t90\t75\r\n*착용무기\t없음\tNoSuchSword\r\n'
       '*적용직업\tFighter\tWizard\r\n*공격동작턴\t1\t2\r\n*걷는동작 100 140 // walk\r\n*끝\r\n')
open(os.path.join(D, 'Test.ini'), 'wb').write(b'\xff\xfe' + ini.encode('utf-16-le'))
open(os.path.join(D, 'note.txt'), 'wb').write('\ufeffhello 안녕 😀 ✓\r\n'.encode('utf-8'))

r = subprocess.run([EXE, '--to-game', SRC, '-o', OUT], capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout)
if r.stderr:
    print('STDERR', r.stderr)


def game_tga(d):
    h = bytearray(d[:18])
    if h[:2] == b'G8':
        for i in range(18):
            h[i] = (h[i] - i * i) & 255
    w, ht, bpp, desc = h[12] | h[13] << 8, h[14] | h[15] << 8, h[16], h[17]
    px = d[18:18 + w * ht * bpp // 8]
    out = []
    for i in range(w * ht):
        p = px[i * bpp // 8:(i + 1) * bpp // 8]
        out.append((p[2], p[1], p[0]) + ((p[3],) if bpp == 32 else ()))
    rows = [out[r * w:(r + 1) * w] for r in range(ht)]
    if not desc & 0x20:
        rows.reverse()                                        # bottom-up -> top row first
    return w, ht, bpp, rows


def game_bmp(d):
    h = bytearray(d[:14])
    if h[:2] == b'A8':
        for i in range(14):
            h[i] = (h[i] - i * i) & 255
    size = struct.unpack_from('<I', h, 2)[0]
    dib = d[14:size]
    bisize, w, ht, _, bpp = struct.unpack_from('<IiiHH', dib, 0)
    used = struct.unpack_from('<I', dib, 32)[0]
    ncol = used if used else (0 if bpp == 24 else (1 << bpp) & 0xFFFFFFFF if bpp < 32 else 1)
    start = bisize + ncol * 4
    stride = (w * bpp + 31) // 32 * 4
    rows = []
    for r in range(ht):
        row = dib[start + r * stride: start + r * stride + w * bpp // 8]
        rows.append([(row[i * bpp // 8 + 2], row[i * bpp // 8 + 1], row[i * bpp // 8])
                     + ((row[i * bpp // 8 + 3],) if bpp == 32 else ()) for i in range(w)])
    rows.reverse()
    return w, ht, bpp, rows


def want(im):
    return [[im.getpixel((x, y)) for x in range(im.width)] for y in range(im.height)]


OD = os.path.join(OUT, 'char', 'monster', 'Test')
ok = True


def check(name, fn, im, expect_bpp):
    global ok
    d = open(os.path.join(OD, name), 'rb').read()
    w, h, bpp, rows = fn(d)
    exp = want(im)
    good = (w, h) == im.size and bpp == expect_bpp and rows == exp and d[:2] in (b'A8', b'G8')
    if fn is game_bmp:
        good = good and struct.unpack_from('<I', bytearray((d[i] - i * i) & 255 for i in range(14)), 2)[0] == len(d)
    print('%-20s %s' % (name, 'game reads the right picture' if good else 'WRONG (%s bpp=%s)' % (d[:2], bpp)))
    ok &= good


check('t_plain24.tga', game_tga, img, 24)
check('t_rle24.tga', game_tga, img, 24)
check('t_rle32.tga', game_tga, imga, 32)
check('t_id24.tga', game_tga, img, 24)
g3 = img.convert('L').convert('RGB')
check('t_gray8.tga', game_tga, g3, 24)
check('b_plain24.bmp', game_bmp, img, 24)
check('b_topdown24.bmp', game_bmp, img, 24)
check('b_gap24.bmp', game_bmp, img, 24)
print('b_bitfields32.bmp    (32-bit: the game reads one pixel late in its own files too; checked by layout)')
d = open(os.path.join(OD, 'b_bitfields32.bmp'), 'rb').read()
h = bytearray((d[i] - i * i) & 255 for i in range(14))
print('   bfOffBits', struct.unpack_from('<I', h, 10)[0], 'compression', struct.unpack_from('<I', d, 30)[0],
      'pixels equal:', d[54:54 + len(px32)] == px32)


def game_wav(d):
    data36 = d[36:40]
    if data36[:2] == b'da':
        size = struct.unpack_from('<I', d, 40)[0]; start = 44
    elif data36[:2] == b'fa':
        size = struct.unpack_from('<I', d, 52)[0]; start = 56
    else:
        size = struct.unpack_from('<I', d, 54)[0]; start = 58
    fmt = struct.unpack_from('<HHIIHH', d, 20)
    return fmt, d[start:start + size]


for n in ('w_plain.wav', 'w_list.wav', 'w_extensible.wav', 'w_fmt18.wav'):
    d = open(os.path.join(OUT, 'wav', 'Effects', n), 'rb').read()
    fmt, s = game_wav(d)
    good = d[:4] == b'JODO' and fmt[0] == 1 and fmt[1:] == (1, 22050, 44100, 2, 16) and s == samples
    print('%-20s %s' % (n, 'game plays the right samples' if good else 'WRONG %s' % (fmt,)))
    ok &= good
bgm = os.path.join(OUT, 'wav', 'BGM', 'Town.bgm')
eff = os.path.join(OUT, 'wav', 'BGM', 'Ending.wav')
good = os.path.isfile(bgm) and open(bgm, 'rb').read(4) == b'RIFF' and os.path.isfile(eff) and open(eff, 'rb').read(4) == b'JODO'
print('%-20s %s' % ('BGM\\Town.bgm.wav', 'Town.bgm (RIFF); Ending.wav stays a sound effect (JODO)' if good else 'WRONG'))
ok &= good
t = open(os.path.join(OD, 'Test.ini'), 'rb').read()
good = t.decode('cp949').startswith('*모양파일')
print('%-20s %s' % ('Test.ini (UTF-16)', 'CP949 text + .inx' if good and os.path.isfile(os.path.join(OD, 'Test.inx')) else 'WRONG'))
ok &= good
print('ALL OK' if ok else 'SOMETHING WRONG')
sys.exit(0 if ok else 1)
