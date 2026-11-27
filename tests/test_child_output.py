"""What a facet.py child the viewer spawns writes into the job log it shows."""

import subprocess
import sys

from api.config import child_process_env

# A progress bar, and log lines written past it the way facet.py's logging handler does.
_CHILD = """
from tqdm import tqdm
for i in tqdm(range(50), desc='Multi-pass processing', mininterval=0):
    if i % 10 == 0:
        tqdm.write(f'step {i}')
"""


def test_the_job_log_gets_log_lines_not_progress_bar_redraws():
    # Read the way api/routers/scan.py reads a job: text mode, where \\r ends a line too.
    proc = subprocess.run([sys.executable, '-c', _CHILD], env=child_process_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
    lines = proc.stdout.splitlines()
    assert lines == [f'step {i}' for i in range(0, 50, 10)]
