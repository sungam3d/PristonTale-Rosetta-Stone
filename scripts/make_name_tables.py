"""Item and skill name tables for .inx <-> .ini (*착용무기 / *적용기술 hold indexes into these),
taken from the server source in the order the game builds them.

    python make_name_tables.py <OG Source\\J_Server> [out dir]      (default out: smdanim\\data)
"""
import os
import re
import sys

src = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'smdanim', 'data')
os.makedirs(out, exist_ok=True)


def read(p):
    return open(p, 'rb').read().decode('cp949', 'replace')


# sItem[MAX_ITEM] = { {code, "name", "category", w, h, "dir", class, "LastCategory", ...}, ... }
text = read(os.path.join(src, 'sinbaram', 'sinItem.cpp'))
body = text[text.index('sItem[MAX_ITEM]'):]
body = body[:body.index('};')]
body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
items = []
for line in body.splitlines():
    line = line.split('//')[0]
    if re.match(r'\s*\{\s*sin', line):
        q = re.findall(r'"([^"]*)"', line)
        items.append(q[3] if len(q) > 3 else '')
open(os.path.join(out, 'items.txt'), 'w', encoding='utf-8', newline='\n').write('\n'.join(items) + '\n')

# SkillDataCode[] = { { "name", code }, ... }   (the language #ifdef blocks before it are skipped)
text = read(os.path.join(src, 'fileread.cpp'))
body = text[text.index('SKILL_DATA_CODE\tSkillDataCode[]') if 'SKILL_DATA_CODE\tSkillDataCode[]' in text else text.index('SkillDataCode[] = {'):]
body = body[body.index('{') + 1:]
body = body[:body.index('};')]
skills = []
for line in body.splitlines():
    line = line.split('//')[0]
    m = re.match(r'\s*\{\s*"([^"]*)"', line)
    if m:
        skills.append(m.group(1))
open(os.path.join(out, 'skills.txt'), 'w', encoding='utf-8', newline='\n').write('\n'.join(skills) + '\n')
print('%d items, %d skills -> %s' % (len(items), len(skills), out))
