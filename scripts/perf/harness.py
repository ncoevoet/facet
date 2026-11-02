"""Instrumented runner for facet.py multi-pass scans (scan-pass performance work).

usage: harness.py RUN_DIR [facet args...]
env:   PERF_REPO       (required) checkout to run; its facet.py is executed, its modules are imported
       PERF_PROFILE    16gb (default) | 8gb          -> FACET_VRAM_PROFILE
       PERF_CHUNK      N: pin the chunk size (auto-tuning resize neutralised, RAM-cache eviction stays live)
       PERF_PIL_GUARD  1: crc32 of every photo's PIL image before and after every _run_model_pass

Everything is runtime monkeypatching; no repo file is touched.
Outputs in RUN_DIR: harness.log, events.json (timed calls), accum.json (any-thread timers),
samples.csv (GPU util/mem, CPU, rss/private, sys_mem_pct, swap_used_gib, phase), summary.json
(with the processor `metrics` dict), batch_sizes.json (sub-batch ledger), pil_guard.json (guard mode).

Exit codes: 3 = PERF_REPO is not a checkout / the imported module is not under PERF_REPO.
"""
import os
import sys

REPO = os.environ.get('PERF_REPO', '')
if not REPO or not os.path.isfile(os.path.join(REPO, 'processing', 'multi_pass.py')):
    print('harness: PERF_REPO=%r has no processing/multi_pass.py; refusing to run' % REPO, file=sys.stderr)
    sys.exit(3)
REPO = os.path.realpath(REPO)

import collections  # noqa: E402
import csv  # noqa: E402
import functools  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import runpy  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import zlib  # noqa: E402

args = sys.argv[1:]
if not args:
    print(__doc__, file=sys.stderr)
    sys.exit(2)
run = args.pop(0)
os.makedirs(run, exist_ok=True)
os.environ['FACET_VRAM_PROFILE'] = os.environ.get('PERF_PROFILE', '16gb')
sys.path.insert(0, REPO)
os.chdir(REPO)
import torch  # noqa: E402
import pynvml  # noqa: E402
import psutil  # noqa: E402

T0 = time.time()
_logf = open(os.path.join(run, 'harness.log'), 'a')


def log(*a):
    msg = ' '.join(map(str, a))
    print('[HARNESS %.1f] %s' % (time.time() - T0, msg), file=sys.__stderr__, flush=True)
    print('[%.2f] %s' % (time.time() - T0, msg), file=_logf, flush=True)


pynvml.nvmlInit()
H = pynvml.nvmlDeviceGetHandleByIndex(0)
G = 2 ** 30
BASE = pynvml.nvmlDeviceGetMemoryInfo(H).used / G
log('repo', REPO)
log('profile', os.environ['FACET_VRAM_PROFILE'], 'baseline_gib=%.3f' % BASE)

# ---------------------------------------------------------------- phase state
MAIN = threading.main_thread()
PHASE = ['startup']          # stack of main-thread phase labels
EVENTS = []                  # (label, t0, t1, extra)
ACC = collections.defaultdict(lambda: [0, 0.0])   # name -> [count, seconds] (any thread)
ACC_LOCK = threading.Lock()
STATE = {'stop': False, 'post': None, 'metrics': None, 'chunk': -1, 'model': None}


def cur_phase():
    return PHASE[-1]


def acc(name, dt):
    with ACC_LOCK:
        a = ACC[name]
        a[0] += 1
        a[1] += dt


def sync():
    try:
        if torch.cuda.is_initialized():
            torch.cuda.synchronize()
    except Exception:
        pass


def timed_phase(label_fn, do_sync=False):
    """Phase push/pop on the MAIN thread only (S4 runs _load_images on a worker); an event is
    recorded from every thread, tagged with the thread name when it is not the main one."""
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **k):
            label, extra = label_fn(*a, **k)
            on_main = threading.current_thread() is MAIN
            if on_main:
                PHASE.append(label)
            else:
                extra = dict(extra, thread=threading.current_thread().name)
            t = time.time()
            try:
                return fn(*a, **k)
            finally:
                if do_sync:
                    sync()
                t1 = time.time()
                if on_main:
                    PHASE.pop()
                EVENTS.append((label, t - T0, t1 - T0, extra))
        w.__perf_wrapped__ = True
        return w
    return deco


def timed_acc(name_fn, do_sync=False):
    def deco(fn):
        if getattr(fn, '__perf_wrapped__', False):
            return fn

        @functools.wraps(fn)
        def w(*a, **k):
            t = time.time()
            try:
                return fn(*a, **k)
            finally:
                if do_sync:
                    sync()
                dt = time.time() - t
                nm = name_fn(*a, **k) if callable(name_fn) else name_fn
                if threading.current_thread() is not MAIN:
                    nm = nm + '@thread'
                acc(nm, dt)
        w.__perf_wrapped__ = True
        return w
    return deco


# ---------------------------------------------------------------- sampler
SAMPLES = []
PROC = psutil.Process()


def sampler():
    PROC.cpu_percent(None)
    psutil.cpu_percent(None)
    last_cpu = sys_cpu = tc = 0.0
    rss = priv = sysm = swap = 0.0
    while not STATE['stop']:
        now = time.time()
        if now - tc > 0.5:
            last_cpu = PROC.cpu_percent(None) / psutil.cpu_count()
            sys_cpu = psutil.cpu_percent(None)
            tc = now
            try:
                mi = PROC.memory_info()
                rss = mi.rss / G
                priv = getattr(mi, 'private', 0) / G
                sysm = psutil.virtual_memory().percent
                swap = psutil.swap_memory().used / G
            except Exception:
                rss = priv = sysm = swap = -1
        try:
            u = pynvml.nvmlDeviceGetUtilizationRates(H).gpu
            m = pynvml.nvmlDeviceGetMemoryInfo(H).used / G
        except Exception:
            u, m = -1, -1
        SAMPLES.append((now - T0, u, m, last_cpu, sys_cpu, round(rss, 3), round(priv, 3), sysm,
                        round(swap, 3), cur_phase()))
        time.sleep(0.05)


threading.Thread(target=sampler, daemon=True).start()

# ---------------------------------------------------------------- instrumentation
import processing.multi_pass as mp  # noqa: E402
import models.model_manager as mm  # noqa: E402
import processing.progress as prog  # noqa: E402

MOD_FILE = os.path.realpath(mp.__file__)
log('module processing.multi_pass', MOD_FILE)
if os.path.commonpath([MOD_FILE, REPO]) != REPO:
    log('FATAL processing.multi_pass is not under PERF_REPO', REPO)
    print('harness: processing.multi_pass imported from %s, not from PERF_REPO %s' % (MOD_FILE, REPO),
          file=sys.stderr)
    sys.exit(3)

MPP = mp.ChunkedMultiPassProcessor


def _chunk_label(self, paths, ci, tc, *a, **k):
    STATE['chunk'] = ci
    return 'chunk', {'n': len(paths), 'idx': ci}


MPP._process_chunk = timed_phase(_chunk_label)(MPP._process_chunk)
MPP._load_images = timed_phase(lambda self, paths, *a, **k: ('io', {'n': len(paths)}))(MPP._load_images)
MPP._compute_aggregates = timed_phase(lambda self, r, i, *a, **k: ('agg', {'n': len(r)}))(MPP._compute_aggregates)
MPP._save_results = timed_phase(lambda self, r, i, *a, **k: ('save', {'n': len(r)}))(MPP._save_results)
MPP._reclaim_freed_memory = timed_phase(lambda self, *a, **k: ('reclaim', {}))(MPP._reclaim_freed_memory)

# batch-size ledger (G4, D19): per chunk, ordered (model, sub_batch_size, halved_to)
LEDGER = collections.defaultdict(list)
LEDGER_LOCK = threading.Lock()


def ledger_add(model, size):
    with LEDGER_LOCK:
        LEDGER[STATE['chunk']].append([model, size, None])


def ledger_halved(model_hint, to):
    with LEDGER_LOCK:
        for entry in reversed(LEDGER[STATE['chunk']]):
            if model_hint is None or entry[0] == model_hint:
                entry[2] = to if entry[2] is None else min(entry[2], to)
                return
        LEDGER[STATE['chunk']].append([model_hint or '?', None, to])


_PIL_GUARD = os.environ.get('PERF_PIL_GUARD') == '1'
GUARD = {'checked_passes': 0, 'mismatches': []}


def _pil_crcs(images):
    out = {}
    for path, d in images.items():
        pil = d.get('pil') if isinstance(d, dict) else None
        if pil is not None:
            out[path] = zlib.crc32(pil.tobytes())
    return out


def _run_pass_label(self, name, model, images, results, *a, **k):
    STATE['model'] = name
    return 'infer:' + name, {'n': len(images)}


_rmp = MPP._run_model_pass
_rmp_timed = timed_phase(_run_pass_label, do_sync=True)(_rmp)


@functools.wraps(_rmp)
def _run_model_pass(self, name, model, images, results, *a, **k):
    if not _PIL_GUARD:
        return _rmp_timed(self, name, model, images, results, *a, **k)
    before = _pil_crcs(images)
    try:
        return _rmp_timed(self, name, model, images, results, *a, **k)
    finally:
        after = _pil_crcs(images)
        GUARD['checked_passes'] += 1
        for p, c in before.items():
            if after.get(p) != c:
                GUARD['mismatches'].append({'chunk': STATE['chunk'], 'model': name, 'path': p})
                log('PIL GUARD MISMATCH', STATE['chunk'], name, p)


MPP._run_model_pass = _run_model_pass

# PERF_CHUNK=N: fixed chunk size (auto-tune resize disabled; RAM-cache eviction unchanged) so two
# runs batch identically and their results can be compared bit-for-bit.
FIXED_CHUNK = int(os.environ.get('PERF_CHUNK', '0') or 0)
if FIXED_CHUNK:
    _pd0 = MPP.process_directory

    def _pd_fixed(self, paths, *a, **k):
        self.chunk_size = FIXED_CHUNK
        return _pd0(self, paths, *a, **k)
    MPP.process_directory = _pd_fixed
    MPP.reduce_chunk_size = lambda self, *a, **k: False
    MPP.increase_chunk_size = lambda self, *a, **k: False
    log('fixed chunk size', FIXED_CHUNK)

_pd1 = MPP.process_directory


@functools.wraps(_pd1)
def _process_directory(self, *a, **k):
    t = time.time()
    PHASE.append('scan')
    try:
        return _pd1(self, *a, **k)
    finally:
        PHASE.pop()
        EVENTS.append(('scan', t - T0, time.time() - T0, {'n': len(a[0]) if a else 0}))
        try:
            STATE['metrics'] = {kk: (vv if isinstance(vv, (int, float, str, bool, type(None))) else str(vv))
                                for kk, vv in dict(self.metrics).items()}
        except Exception as e:  # metrics are best effort: phase tables also come from events
            log('metrics capture failed', e)


MPP.process_directory = _process_directory

MM = mm.ModelManager


def _load_label(self, name, *a, **k):
    return 'load:' + name, {'hit': name in self._cpu_cache, 'resident': name in self.models}


def _unload_label(self, name, *a, **k):
    try:
        cache_to_ram = self._can_cache_to_ram(name)
    except Exception:
        cache_to_ram = None
    return 'unload:' + name, {'cache_to_ram': cache_to_ram}


MM.load_model_only = timed_phase(_load_label, do_sync=True)(MM.load_model_only)
MM.unload_model = timed_phase(_unload_label, do_sync=True)(MM.unload_model)
MM.evict_cpu_cache = timed_phase(lambda self, *a, **k: ('evict_cpu_cache', {'cached': list(self._cpu_cache)}))(MM.evict_cpu_cache)

# post-scan steps are delimited by emit_progress phase markers
_orig_emit = prog.emit_progress


def emit(phase, *a, **k):
    if threading.current_thread() is MAIN and phase != 'scoring':
        if STATE['post'] is not None:
            PHASE.pop()
            EVENTS.append(('post:' + STATE['post'][0], STATE['post'][1], time.time() - T0, {}))
        if phase != 'done':
            STATE['post'] = (phase, time.time() - T0)
            PHASE.append('post:' + phase)
        else:
            STATE['post'] = None
    return _orig_emit(phase, *a, **k)


prog.emit_progress = emit

# --- image-load components (thread pool) ---
import utils  # noqa: E402
import utils.image_loading as il  # noqa: E402,F401
import analyzers  # noqa: E402
import analyzers.form_facet as ff  # noqa: E402
import analyzers.image_cache as icm  # noqa: E402,F401
import imagehash  # noqa: E402
import exiftool  # noqa: E402

utils.load_image_from_path = timed_acc('io.decode')(utils.load_image_from_path)
# The full scan decodes AND makes the stored thumbnail here (one RAW open); the save no
# longer generates one, so there is no save.thumbnail timer.
utils.load_image_and_thumbnail = timed_acc('io.decode_thumbnail')(utils.load_image_and_thumbnail)
TA = analyzers.TechnicalAnalyzer
for nm in ('get_sharpness_data', 'get_color_harmony_data', 'get_histogram_data', 'detect_monochrome',
           'get_dynamic_range', 'get_noise_estimate', 'get_contrast_score'):
    setattr(TA, nm, staticmethod(timed_acc('io.tech.' + nm)(getattr(TA, nm))))
analyzers.ImageCache.__init__ = timed_acc('io.image_cache')(analyzers.ImageCache.__init__)
ff.compute_form_metrics = timed_acc('io.form')(ff.compute_form_metrics)
imagehash.phash = timed_acc('io.phash')(imagehash.phash)
exiftool.get_exif_batch = timed_acc('io.exif_batch')(exiftool.get_exif_batch)
import processing.scorer as psc  # noqa: E402

psc.Facet.get_exif_data = timed_acc('io.exif_single')(psc.Facet.get_exif_data)
psc.Facet.save_photos_batch = timed_acc('save.save_photos_batch')(psc.Facet.save_photos_batch)

# --- inference sub-components ---
import models.pyiqa_scorer as pq  # noqa: E402

pq.PyIQAScorer._preprocess_image = timed_acc(lambda self, img, *a, **k: 'pre.pyiqa.' + self.model_name, do_sync=True)(pq.PyIQAScorer._preprocess_image)
_pq_score_batch = pq.PyIQAScorer.score_batch


@functools.wraps(_pq_score_batch)
def _pq_score_batch_ledger(self, images, *a, **k):
    ledger_add(self.model_name, getattr(self, 'forward_batch', None))
    return _pq_score_batch(self, images, *a, **k)


pq.PyIQAScorer.score_batch = _pq_score_batch_ledger
import models.qrealign_native as qn  # noqa: E402

qn.QReAlignNativeScorer._prepare = timed_acc('pre.qrealign.resize')(qn.QReAlignNativeScorer._prepare)
qn.QReAlignNativeScorer._score_one = timed_acc('qrealign.score_one', do_sync=True)(qn.QReAlignNativeScorer._score_one)
import models.saliency_scorer as ss  # noqa: E402

ss.SaliencyScorer._run_chunk = timed_acc('saliency.run_chunk', do_sync=True)(ss.SaliencyScorer._run_chunk)
ss.SaliencyScorer._score_from_mask = timed_acc('saliency.score_from_mask')(ss.SaliencyScorer._score_from_mask)
_ss_affordable = ss.SaliencyScorer._affordable_batch_size


@functools.wraps(_ss_affordable)
def _ss_affordable_ledger(self, requested, *a, **k):
    n = _ss_affordable(self, requested, *a, **k)
    ledger_add('saliency', n)
    return n


ss.SaliencyScorer._affordable_batch_size = _ss_affordable_ledger
import models.samp_net as sn  # noqa: E402

sn.SAMPNetScorer.preprocess = timed_acc('samp.preprocess', do_sync=True)(sn.SAMPNetScorer.preprocess)
sn.SAMPNetScorer.score = timed_acc('samp.score', do_sync=True)(sn.SAMPNetScorer.score)
import models.vlm_tagger as vt  # noqa: E402

vt.VLMTagger._batch_qwen3 = timed_acc('vlm.batch_total', do_sync=True)(vt.VLMTagger._batch_qwen3)
vt.VLMTagger.tag_image = timed_acc('vlm.tag_image_single', do_sync=True)(vt.VLMTagger.tag_image)
import analyzers.face as af  # noqa: E402

af.FaceAnalyzer._blendshape_face_scores = timed_acc('face.blendshapes')(af.FaceAnalyzer._blendshape_face_scores)
af.FaceAnalyzer.analyze_faces = timed_acc('face.analyze_total', do_sync=True)(af.FaceAnalyzer.analyze_faces)

# halvings after an out-of-memory error are only visible in the log line each scorer emits;
# hook the logger dispatch once (a call happens on the logger that emitted, so nothing is counted twice)
import logging  # noqa: E402

_HALVE_RE = re.compile(r'(Saliency batch|(\S+) forward batch) reduced to (\d+)')
_call_handlers = logging.Logger.callHandlers


def _call_handlers_hook(self, record):
    try:
        if record.levelno >= logging.WARNING:
            m = _HALVE_RE.search(record.getMessage())
            if m:
                ledger_halved('saliency' if m.group(1) == 'Saliency batch' else m.group(2), int(m.group(3)))
    except Exception:
        pass
    return _call_handlers(self, record)


logging.Logger.callHandlers = _call_handlers_hook


def _post_load_wrap(name, model):
    """Wrap per-instance callables of freshly loaded models (idempotent)."""
    try:
        if name in mp.VLM_TAGGER_KEYS and model is not None:
            g = model.model.generate
            if not getattr(g, '__perf_wrapped__', False):
                model.model.generate = timed_acc('vlm.generate', do_sync=True)(g)
            p = model.processor
            if not getattr(p.apply_chat_template, '__perf_wrapped__', False):
                p.apply_chat_template = timed_acc('vlm.processor')(p.apply_chat_template)
        elif name == 'clip' and isinstance(model, dict):
            pp = model.get('preprocess')
            if pp is not None and not getattr(pp, '__perf_wrapped__', False):
                model['preprocess'] = timed_acc('clip.preprocess')(pp)
            m = model['model']
            if hasattr(m, 'get_image_features') and not getattr(m.get_image_features, '__perf_wrapped__', False):
                m.get_image_features = timed_acc('clip.forward', do_sync=True)(m.get_image_features)
        elif name == 'saliency' and model is not None and getattr(model, 'transform', None) is not None:
            if not getattr(model.transform, '__perf_wrapped__', False):
                model.transform = timed_acc('saliency.transform')(model.transform)
        elif name in ('insightface',) and model is not None and getattr(model, 'face_app', None) is not None:
            if not getattr(model.face_app.get, '__perf_wrapped__', False):
                model.face_app.get = timed_acc('face.app_get', do_sync=True)(model.face_app.get)
    except Exception as e:
        log('post_load_wrap failed', name, e)


_lmo = MM.load_model_only


@functools.wraps(_lmo)
def lmo(self, name, *a, **k):
    m = _lmo(self, name, *a, **k)
    _post_load_wrap(name, m)
    return m


MM.load_model_only = lmo

# ---------------------------------------------------------------- run
sys.argv = ['facet.py'] + args
code = 0
try:
    runpy.run_path(os.path.join(REPO, 'facet.py'), run_name='__main__')
except SystemExit as e:
    code = e.code or 0
except BaseException:
    import traceback
    traceback.print_exc()
    code = 1
if STATE['post'] is not None:
    EVENTS.append(('post:' + STATE['post'][0], STATE['post'][1], time.time() - T0, {}))
T_END = time.time() - T0
STATE['stop'] = True
time.sleep(0.2)
with open(os.path.join(run, 'samples.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['t', 'gpu_util', 'mem_gib', 'proc_cpu_pct', 'sys_cpu_pct', 'rss_gib', 'private_gib',
                'sys_mem_pct', 'swap_used_gib', 'phase'])
    w.writerows(SAMPLES)
json.dump(EVENTS, open(os.path.join(run, 'events.json'), 'w'))
json.dump({k: v for k, v in ACC.items()}, open(os.path.join(run, 'accum.json'), 'w'), indent=1)
json.dump({'chunks': {str(k): v for k, v in sorted(LEDGER.items())}},
          open(os.path.join(run, 'batch_sizes.json'), 'w'), indent=1)
if _PIL_GUARD:
    json.dump(GUARD, open(os.path.join(run, 'pil_guard.json'), 'w'), indent=1)
res = {'exit': code, 'wall_s': T_END, 'baseline_gib': BASE, 'repo': REPO, 'module_file': MOD_FILE,
       'profile': os.environ['FACET_VRAM_PROFILE'], 'fixed_chunk': FIXED_CHUNK,
       'peak_gib': max((s[2] for s in SAMPLES), default=0),
       'peak_swap_gib': max((s[8] for s in SAMPLES), default=0),
       'peak_sys_mem_pct': max((s[7] for s in SAMPLES), default=0),
       'metrics': STATE['metrics'], 'pil_guard': GUARD if _PIL_GUARD else None}
json.dump(res, open(os.path.join(run, 'summary.json'), 'w'), indent=1)
log('SUMMARY', json.dumps(res))
sys.exit(code)
