"""Minimal, fast generic ASE (3ds Max ASCII Scene Export) tree parser.

Every node is [key, args, children]; key is e.g. '*MESH_VERTEX' and args is the
raw remainder of the line (string).  Blocks ("{ ... }") become children.
"""

def parse_ase(path_or_text):
    if '\n' in path_or_text:
        text = path_or_text
    else:
        with open(path_or_text, 'r', encoding='latin-1') as f:
            text = f.read()
    root = ['ROOT', '', []]
    stack = [root]
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s[0] == '}':
            if len(stack) > 1:
                stack.pop()
            continue
        if s[0] != '*':
            continue
        sp = s.find(' ')
        tab = s.find('\t')
        if sp < 0 or (0 <= tab < sp):
            sp = tab
        if sp < 0:
            key, args = s, ''
        else:
            key, args = s[:sp], s[sp + 1:].strip()
        if args.endswith('{'):
            node = [key, args[:-1].strip(), []]
            stack[-1][2].append(node)
            stack.append(node)
        else:
            stack[-1][2].append([key, args, None])
    return root


def find(node, key):
    for c in node[2] or ():
        if c[0] == key:
            return c
    return None


def find_all(node, key):
    return [c for c in (node[2] or ()) if c[0] == key]


def val(node, key, default=None):
    c = find(node, key)
    return c[1] if c is not None else default


def unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s
