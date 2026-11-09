"""Check the interface language tables (src/PTSmd/lang/*.txt) against English.

    python check_lang.py

Every table: the same keys as en.txt, the same {0} {1} ... values, the same number of \\n and (for the
3ds Max texts, max.*) the same number of % - which MAXScript's format fills in.  The English max.* texts
must each be found exactly once as a string in tools\\max\\*.ms: the installer writes the plug-in in the
window's language by replacing them.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANG = os.path.join(HERE, '..', 'src', 'PTSmd', 'lang')
MAX = os.path.join(HERE, '..', 'tools', 'max')


def load(p):
    d = {}
    for line in open(p, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line or line.startswith('#') or ' = ' not in line:
            continue
        k, v = line.split(' = ', 1)
        d[k.strip()] = v
    return d


def ms_literal(v):
    """A table text as MAXScript writes it in the script: "...", with \\n and \\" escapes."""
    v = v.replace('\\n', '\n')
    return '"' + v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


en = load(os.path.join(LANG, 'en.txt'))
bad = 0
for p in sorted(glob.glob(os.path.join(LANG, '*.txt'))):
    if p.endswith('en.txt'):
        continue
    t = load(p)
    problems = []
    problems += ['missing ' + k for k in en if k not in t]
    problems += ['extra ' + k for k in t if k not in en]
    for k in en:
        if k not in t:
            continue
        if sorted(re.findall(r'\{\d+\}', en[k])) != sorted(re.findall(r'\{\d+\}', t[k])):
            problems.append('values differ in ' + k)
        if en[k].count('\\n') != t[k].count('\\n'):
            problems.append('line breaks differ in ' + k)
        if k.startswith('max.') and en[k].count('%') != t[k].count('%'):
            problems.append('% differ in ' + k)
    print('%-10s %3d texts  %s' % (os.path.basename(p), len(t), '; '.join(problems) if problems else 'ok'))
    bad += len(problems)

src = ''.join(open(f, encoding='utf-8-sig').read() for f in glob.glob(os.path.join(MAX, '*.ms')))
for k, v in en.items():
    if k.startswith('max.'):
        n = src.count(ms_literal(v))
        if n != 1:
            print('max text %s is in the scripts %d times: %s' % (k, n, ms_literal(v)[:70]))
            bad += 1 if n == 0 else 0
print('all ok' if bad == 0 else '%d problem(s)' % bad)
sys.exit(1 if bad else 0)
