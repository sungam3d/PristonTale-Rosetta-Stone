"""Run score_stage_parts.py for several PART_LOOKBACK / PART_MERGE_DISTANCE values (totals only).

  python scripts/sweep_stage_parts.py <orig Field dir> <smd Field dir>
"""
import contextlib
import io
import os
import runpy
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from smdanim import convert   # noqa: E402

here = os.path.join(os.path.dirname(__file__), 'score_stage_parts.py')
args = sys.argv[1:3]
for lb in (0, 1, 2, 4):
    for dist in (300.0, 1000.0):
        convert.PART_LOOKBACK = lb
        convert.PART_MERGE_DISTANCE = dist
        buf = io.StringIO()
        sys.argv = [here] + args
        with contextlib.redirect_stdout(buf):
            runpy.run_path(here, run_name='__main__')
        print('lookback %d distance %5.0f  %s' % (lb, dist, buf.getvalue().strip().splitlines()[-1]), flush=True)
