"""Are stage TexLinks (per-face UV records) shared between faces, and in face order?

  python scripts/probe_stage_texlinks.py <stage.smd>
"""
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim import smdfile   # noqa: E402

st = smdfile.Stage(sys.argv[1])
b = open(sys.argv[1], 'rb').read()
off = st.data_end - st.n_light * 28 - st.n_texlink * 32 - st.n_face * 28
raw = list(struct.iter_unpack('<IIHHHHIhhhh', b[off:off + st.n_face * 28]))
base = struct.unpack_from('<I', b, smdfile.ST_TEXLINK_PTR)[0]
ptrs = [(r[6] - base) // 32 if r[6] else -1 for r in raw]
use = Counter(p for p in ptrs if p >= 0)
print('faces', st.n_face, 'texlinks', st.n_texlink, 'faces with uv', sum(use.values()),
      'distinct', len(use), 'shared by >1 face', sum(1 for v in use.values() if v > 1))
back = sum(1 for i in range(1, len(ptrs)) if 0 <= ptrs[i] < max(ptrs[:i] or [-1]))
print('first 20 ptrs', ptrs[:20])
mono = sum(1 for i in range(1, len(ptrs)) if ptrs[i] >= 0 and ptrs[i - 1] >= 0 and ptrs[i] < ptrs[i - 1])
print('decreasing steps', mono)
print('sum/calcsum first faces', [(hex(r[0]), hex(r[1])) for r in raw[:6]])
