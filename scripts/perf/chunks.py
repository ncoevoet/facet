"""Per-chunk cost table for one or two harness run directories.

usage: chunks.py RUN_DIR [RUN_DIR_B] [--json OUT.json]

One run: header (wall, startup, scan, post), then per chunk: n, wall, load (disk/ram/resident hit-miss
by model), unload+reclaim, io, agg, save, infer per model, max sys_mem_pct, max swap, plus the
evicted model names, the sub-batch ledger, the GPU-idle share, the peak private/RSS and the sibling
memory (system used minus the scan's RSS).
Two runs: the same totals side by side with the B/A ratio, and the median `agg` per chunk (chunks >= 1).

Windows: a chunk owns the events between the previous chunk's end and its own end, so work started
just before the timed chunk body (an overlapped decode) is still charged to a chunk. Events recorded
from a worker thread carry `thread` in their extra and are summed under `<label>@thread`.
A decode-ahead (`ahead` event: the next chunk's first photos, decoded during the chunk that
submitted it) is NOT charged to that chunk: its span, and the `io@thread` events inside it, are
booked to the chunk that consumes it as `io_ahead`.
"""
import collections
import csv
import json
import os
import statistics
import sys


def load(run):
    ev = json.load(open(os.path.join(run, 'events.json')))
    summ = json.load(open(os.path.join(run, 'summary.json')))
    accum = json.load(open(os.path.join(run, 'accum.json')))
    rows = list(csv.DictReader(open(os.path.join(run, 'samples.csv'))))
    ledger_path = os.path.join(run, 'batch_sizes.json')
    ledger = json.load(open(ledger_path)) if os.path.exists(ledger_path) else {}
    return ev, summ, accum, rows, ledger


def dur(e):
    return e[2] - e[1]


def analyse(run):
    ev, summ, accum, rows, ledger = load(run)
    scan = [e for e in ev if e[0] == 'scan']
    chunks = sorted((e for e in ev if e[0] == 'chunk'), key=lambda e: e[1])
    post = [e for e in ev if e[0].startswith('post:')]
    S = [(float(r['t']), float(r['sys_mem_pct']), float(r.get('swap_used_gib') or 0),
          float(r['rss_gib']), float(r['private_gib']), int(r['gpu_util']), r['phase']) for r in rows]
    out = {'run': os.path.basename(os.path.normpath(run)), 'wall_s': summ['wall_s'], 'exit': summ['exit'],
           'profile': summ.get('profile'), 'fixed_chunk': summ.get('fixed_chunk'),
           'module_file': summ.get('module_file'),
           'startup_s': scan[0][1] if scan else None, 'scan_s': dur(scan[0]) if scan else None,
           'post_s': {e[0][5:]: round(dur(e), 2) for e in post},
           'post_total_s': round(sum(dur(e) for e in post), 2), 'n_chunks': len(chunks),
           'metrics': summ.get('metrics'), 'peak_swap_gib': summ.get('peak_swap_gib'),
           'peak_sys_mem_pct': summ.get('peak_sys_mem_pct')}
    ahead = [e for e in ev if e[0] == 'ahead']

    def inside_ahead(e):
        # The scan thread's own events (infer/load/unload) run beside the ahead by design.
        return bool(e[3].get('thread')) and any(a[1] - 1e-6 <= e[1] and e[2] <= a[2] + 1e-6 for a in ahead)

    per_chunk = []
    prev_end = scan[0][1] if scan else 0.0
    for c in chunks:
        lo, hi = prev_end, c[2]
        d = collections.OrderedDict()
        d['n'] = c[3]['n']
        d['wall'] = round(hi - lo, 2)
        loads = collections.OrderedDict()
        evicted = []
        for e in ev:
            if e is c or e[0] in ('chunk', 'scan', 'ahead') or e[0].startswith('post:'):
                continue
            if inside_ahead(e):
                continue
            if not (e[1] >= lo - 1e-6 and e[2] <= hi + 1e-6):
                continue
            k = e[0]
            if e[3].get('thread'):
                k += '@thread'
            if k.startswith('load:'):
                state = 'resident' if e[3].get('resident') else ('ram' if e[3].get('hit') else 'disk')
                loads[k[5:]] = [state, round(dur(e), 2)]
                continue
            if e[0] == 'evict_cpu_cache':
                evicted.extend(e[3].get('cached') or [])
            d[k] = round(d.get(k, 0) + dur(e), 2)
        consumed = [a for a in ahead if a[1] < c[1] and not any(
            p[1] > a[1] and p[1] < c[1] for p in chunks)]
        if consumed:
            d['io_ahead'] = round(sum(dur(a) for a in consumed), 2)
        d['loads'] = loads
        d['evicted'] = evicted
        win = [s for s in S if lo <= s[0] <= hi]
        d['max_sys_mem_pct'] = max((s[1] for s in win), default=None)
        d['max_swap_gib'] = max((s[2] for s in win), default=None)
        per_chunk.append(d)
        prev_end = hi
    out['per_chunk'] = per_chunk
    tot = collections.defaultdict(float)
    for c in per_chunk:
        for k, v in c.items():
            if k in ('n', 'wall', 'loads', 'evicted', 'max_sys_mem_pct', 'max_swap_gib'):
                continue
            tot['unload+reclaim' if k.startswith('unload:') or k in ('reclaim', 'evict_cpu_cache') else k] += v
        tot['load'] += sum(x[1] for x in c['loads'].values())
        tot['load_disk'] += sum(x[1] for x in c['loads'].values() if x[0] == 'disk')
        tot['load_ram'] += sum(x[1] for x in c['loads'].values() if x[0] == 'ram')
        tot['loads_disk_n'] += sum(1 for x in c['loads'].values() if x[0] == 'disk')
        tot['loads_ram_n'] += sum(1 for x in c['loads'].values() if x[0] == 'ram')
        tot['loads_resident_n'] += sum(1 for x in c['loads'].values() if x[0] == 'resident')
        tot['infer'] += sum(v for k, v in c.items() if k.startswith('infer:'))
    out['totals'] = {k: round(v, 2) for k, v in sorted(tot.items())}
    aggs = [c.get('agg', 0.0) for c in per_chunk[1:]]
    out['agg_median_chunks_ge1'] = round(statistics.median(aggs), 3) if aggs else None
    out['evicted_models'] = [m for c in per_chunk for m in c['evicted']]
    out['ledger'] = ledger
    out['accum'] = {k: {'n': v[0], 's': round(v[1], 2), 'ms_each': round(1000 * v[1] / v[0], 1) if v[0] else 0}
                    for k, v in sorted(accum.items())}
    if scan and S:
        s0, s1 = scan[0][1], scan[0][2]
        tt = idle = us = 0.0
        for i in range(1, len(S)):
            if s0 <= S[i - 1][0] < s1:
                dt = S[i][0] - S[i - 1][0]
                tt += dt
                us += S[i - 1][5] * dt
                idle += dt if S[i - 1][5] <= 5 else 0
        out['scan_gpu'] = {'s': round(tt, 1), 'util_mean': round(us / tt, 1) if tt else 0, 'idle_s': round(idle, 1)}
        # system used minus the scan process = what the siblings hold
        try:
            import psutil
            total_gib = psutil.virtual_memory().total / 2 ** 30
            oth = [s[1] / 100 * total_gib - s[3] for s in S if s0 <= s[0] <= s1]
            out['sibling_mem_gib'] = {'min': round(min(oth), 1), 'median': round(statistics.median(oth), 1),
                                      'max': round(max(oth), 1)}
        except Exception:
            pass
    if S:
        out['scan_rss_peak_gib'] = max(s[3] for s in S)
        out['scan_private_peak_gib'] = max(s[4] for s in S)
    return out


def print_one(a):
    print('== %s  exit %s  wall %.1fs  startup %.1f  scan %.1f  post %.1f  chunks %d  profile %s pin %s'
          % (a['run'], a['exit'], a['wall_s'], a['startup_s'] or 0, a['scan_s'] or 0, a['post_total_s'],
             a['n_chunks'], a['profile'], a['fixed_chunk']))
    print('   module:', a['module_file'])
    for i, c in enumerate(a['per_chunk']):
        infer = {k[6:]: v for k, v in c.items() if k.startswith('infer:')}
        unl = sum(v for k, v in c.items() if k.startswith('unload:')) + c.get('reclaim', 0) + c.get('evict_cpu_cache', 0)
        load = sum(x[1] for x in c['loads'].values())
        print(' chunk%d n=%d wall=%.1f load=%.1f unload+reclaim=%.1f io=%.1f io_ahead=%.1f agg=%.1f '
              'save=%.1f infer=%.1f sys%%max=%s swapmax=%s' % (i, c['n'], c['wall'], load, unl,
                                                              c.get('io', 0), c.get('io_ahead', 0), c.get('agg', 0),
                                          c.get('save', 0), sum(infer.values()), c['max_sys_mem_pct'], c['max_swap_gib']))
        print('   infer:', ' '.join('%s=%.1f' % kv for kv in infer.items()))
        print('   loads:', ' '.join('%s=%s/%.1fs' % (m, v[0], v[1]) for m, v in c['loads'].items()))
        if c['evicted']:
            print('   evicted:', ','.join(c['evicted']))
    print(' totals:', json.dumps(a['totals']))
    print(' agg median (chunks>=1): %s   evicted models: %s   peak swap %s GiB   peak sys mem %s%%'
          % (a['agg_median_chunks_ge1'], a['evicted_models'] or 'none', a['peak_swap_gib'], a['peak_sys_mem_pct']))
    if 'scan_gpu' in a:
        print(' scan GPU: util mean %(util_mean)s%% idle %(idle_s)ss of %(s)ss' % a['scan_gpu'])
    if 'sibling_mem_gib' in a:
        print(' sibling memory GiB (system used minus scan RSS):', a['sibling_mem_gib'])
    print(' ledger:', json.dumps(a['ledger']))


def print_pair(a, b):
    print('== side by side: A=%s  B=%s' % (a['run'], b['run']))
    print('%-22s %12s %12s %8s' % ('metric', 'A', 'B', 'B/A'))
    rows = [('wall_s', a['wall_s'], b['wall_s']), ('scan_s', a['scan_s'], b['scan_s']),
            ('post_total_s', a['post_total_s'], b['post_total_s']),
            ('agg_median_chunks_ge1', a['agg_median_chunks_ge1'], b['agg_median_chunks_ge1'])]
    keys = sorted(set(a['totals']) | set(b['totals']))
    rows += [(k, a['totals'].get(k, 0), b['totals'].get(k, 0)) for k in keys]
    for k, x, y in rows:
        r = (y / x) if x else float('nan')
        print('%-22s %12.2f %12.2f %8.3f' % (k, x or 0, y or 0, r))
    print('chunk walls A:', ' '.join('%.0f' % c['wall'] for c in a['per_chunk']))
    print('chunk walls B:', ' '.join('%.0f' % c['wall'] for c in b['per_chunk']))


def main(argv):
    out_json = None
    if '--json' in argv:
        i = argv.index('--json')
        out_json = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv or len(argv) > 2:
        print(__doc__)
        return 2
    res = [analyse(r) for r in argv]
    for a in res:
        print_one(a)
    if len(res) == 2:
        print_pair(*res)
    if out_json:
        json.dump(res if len(res) > 1 else res[0], open(out_json, 'w'), indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
