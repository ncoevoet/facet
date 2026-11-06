#!/bin/bash
# usage: run.sh LABEL REPO PHOTO_DIR [facet args...]
#   LABEL      run directory name under $PERF_RUNS
#   REPO       checkout to run (BASE or PERF); becomes PERF_REPO for the harness
#   PHOTO_DIR  directory to scan (read-only)
# env passthrough: PERF_PROFILE (16gb|12gb|8gb), PERF_CHUNK, PERF_PIL_GUARD
# env: PERF_RUNS    run root           (default /d/facet-scratch/perf2/runs)
#      PERF_PYTHON  interpreter        (default /d/photo-llm/conda/python.exe)
#      PERF_GATE_MIB nvidia-smi gate   (default 2560)
# exit: 99 = GPU gate refused (nothing was run); otherwise the harness exit code (timeout 1800 -> 124)
#
# The harness always comes from THIS checkout; PERF_REPO selects the tree under test, so the baseline
# and the patched arm are driven by the same instrumentation.
set -u
N="${1:?LABEL}"; REPO="${2:?REPO}"; PH="${3:?PHOTO_DIR}"; shift 3
HERE="$(cd "$(dirname "$0")" && pwd)"
RUNS="${PERF_RUNS:-/d/facet-scratch/perf2/runs}"
PY="${PERF_PYTHON:-/d/photo-llm/conda/python.exe}"
GATE="${PERF_GATE_MIB:-2560}"
D="$RUNS/$N"
mkdir -p "$D"
rm -f "$D"/db.sqlite* "$D"/harness.log "$D"/exit.txt

# temp output never goes to C: (nearly full)
export TMP='D:\facet-scratch\tmp' TEMP='D:\facet-scratch\tmp' TMPDIR='D:\facet-scratch\tmp'
mkdir -p /d/facet-scratch/tmp

B=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d ' ')
echo "baseline_mib=$B gate_mib=$GATE" > "$D/nvsmi_before.txt"
{
    echo "# $(date -Is)"
    nvidia-smi --query-gpu=clocks.sm,clocks.mem,temperature.gpu,power.draw,pstate,memory.used --format=csv
    nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv
} > "$D/gpu_start.txt" 2>&1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/siblings.ps1")" > "$D/other_python.txt" 2>&1
if [ "$B" -gt "$GATE" ]; then
    echo "ABORT: GPU already holds ${B} MiB (> ${GATE})"; echo 99 > "$D/exit.txt"; exit 99
fi

export HF_HUB_OFFLINE=1 PERF_REPO="$(cygpath -w "$REPO")" PYTHONDONTWRITEBYTECODE=1
date +%s > "$D/start.txt"
timeout 1800 "$PY" -I "$(cygpath -w "$HERE/harness.py")" "$(cygpath -w "$D")" "$(cygpath -w "$PH")" \
    --db "$(cygpath -w "$D")\\db.sqlite" "$@" > "$D/run.log" 2>&1
echo $? > "$D/exit.txt"
date +%s > "$D/end.txt"
{
    echo "# $(date -Is) (end)"
    nvidia-smi --query-gpu=clocks.sm,clocks.mem,temperature.gpu,power.draw,pstate,memory.used --format=csv
} > "$D/gpu_end.txt" 2>&1
echo "run $N exit $(cat "$D/exit.txt") wall $(( $(cat "$D/end.txt") - $(cat "$D/start.txt") ))s"
exit "$(cat "$D/exit.txt")"
