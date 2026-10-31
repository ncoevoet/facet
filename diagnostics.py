"""Facet diagnostic tool — checks Python, PyTorch, GPU, dependencies, config, and database."""

import contextlib
import importlib.metadata
import io
import logging
import os
import pathlib
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import warnings

logger = logging.getLogger("facet.diagnostics")


def _section(title):
    logger.info("=" * 50)
    logger.info("  %s", title)
    logger.info("=" * 50)


def _ok(label, value):
    logger.info("  [OK] %s: %s", label, value)


def _warn(label, value):
    logger.warning("  [!!] %s: %s", label, value)


def _info(label, value):
    logger.info("  [--] %s: %s", label, value)


_CUDA_INDEX_URL = "https://download.pytorch.org/whl/"


def _log_pytorch_reinstall_hint(lead):
    """Print the wheel-index advice, from the one place that knows the indexes.

    Three call sites reach the same dead end by different routes -- a CPU-only
    build, a driver torch cannot use, and a build with no kernels for this card
    -- and all three end with the same two pip commands. They were copies until
    a cu124 -> cu126 bump had to touch each of them separately.
    """
    logger.warning(lead)
    logger.warning("    pip install torch torchvision --index-url %scu128", _CUDA_INDEX_URL)
    logger.warning("  For older GPUs (pre-Blackwell), cu126 may also work:")
    logger.warning("    pip install torch torchvision --index-url %scu126", _CUDA_INDEX_URL)


def _cuda_is_usable(torch_module):
    """True when torch reports CUDA *and* a kernel really runs on this GPU."""
    from utils.device import is_device_available
    return is_device_available("cuda", torch_module=torch_module)


def _report_cuda_arch_mismatch(status):
    """Explain a GPU torch can see but ships no kernels for (issue #119).

    ``torch.cuda.is_available()`` is True here, so every other check would
    read green while the first real tensor op dies with "no kernel image is
    available for execution on the device".
    """
    from utils.device import GPU_UNUSABLE_LABEL, sm_name
    capability = (
        f"{status.capability[0]}.{status.capability[1]} ({sm_name(status.capability)})"
        if status.capability else "unknown"
    )
    _warn(GPU_UNUSABLE_LABEL, status.reason)
    _warn("Device compute capability", capability)
    _warn("PyTorch architectures", ", ".join(status.arch_list) or "unknown")
    logger.warning("  This PyTorch build ships no kernels for your GPU architecture.")
    logger.warning("  Docker — switch to the image built for your card:")
    logger.warning("    ghcr.io/ncoevoet/facet:latest-cuda         Turing through Blackwell, incl. RTX 50-series (sm_75-sm_120)")
    logger.warning("    ghcr.io/ncoevoet/facet:latest-cuda-legacy  Maxwell through Hopper (sm_50-sm_90)")
    _log_pytorch_reinstall_hint("  Bare metal — reinstall PyTorch from the matching CUDA index:")


def _registry_id(name):
    """Registry id for a config model name ('clip-mlp', 'qwen3.5-2b', 'topiq_iaa'...)."""
    import licensing
    aliases = {'clip-mlp': 'clip_mlp_head', 'samp-net': 'samp_net'}
    for candidate in (aliases.get(name), name, name.replace('.', '_').replace('-', '_')):
        if candidate in licensing.COMPONENTS:
            return candidate
    return None


def _components_in_use(cfg, profile_name, pol):
    """Registry ids a scan under ``pol`` would load for the profile, in a stable order.

    The set comes from :func:`processing.routing.route_models`, the function the
    scan queue itself calls, so the doctor reports what is routed rather than
    what is merely configured (a commercial install never loads TOPIQ or
    InsightFace, and does load YuNet, SFace and Q-ReAlign). The VRAM fit of a
    VLM tagger is reported by the VRAM section, so every tagger counts as fitting
    here. Only configuration is read; no model is loaded.
    """
    import importlib.util

    import licensing
    from processing.routing import resolve_selected_quality, route_models

    profile_name = profile_name or 'legacy'
    profile = cfg.get('models', {}).get('profiles', {}).get(profile_name, {})
    extended_cfg = cfg.get('iqa_extended', {})
    qrealign = extended_cfg.get('qrealign', 'auto')
    if isinstance(qrealign, str) and qrealign.strip().lower() == 'auto':
        qrealign = profile_name != 'legacy'
    extended = {'qrealign': bool(qrealign),
                'aesthetic_v25': bool(extended_cfg.get('aesthetic_v25', False)),
                'deqa': bool(extended_cfg.get('deqa', False))}

    loaders = route_models(cfg, profile, extended, lambda _gb: True, pol)
    routed = set()
    # The primary quality model is not itself a queue entry when it is the CLIP head.
    routed.add(licensing.component_for_loader(resolve_selected_quality(cfg, profile, pol)))
    blendshapes = cfg.get('face_detection', {}).get('blendshapes', {}).get('enabled', True)
    for loader in loaders:
        if loader == 'clip':
            routed.add('siglip2' if profile.get('clip_config') == 'clip' else 'clip')
        elif loader == 'faces_permissive':
            routed.update(('yunet', 'sface'))
            if importlib.util.find_spec('ofiq') is not None:
                routed.add('ofiq')
            if blendshapes:
                routed.add('mediapipe_face_landmarker')
        else:
            routed.add(licensing.component_for_loader(loader))
            if loader == 'insightface' and blendshapes:
                routed.add('mediapipe_face_landmarker')
            if loader == 'samp_net':
                routed.add('u2netp')

    # Stable display order: the profile's own listing order, then anything routed beyond it.
    order = []
    for candidate in (
            _registry_id(profile.get('aesthetic_model', 'clip-mlp')), 'siglip2', 'clip',
            _registry_id(profile.get('tagging_model', 'clip')),
            *(_registry_id(n) for n in profile.get('supplementary_pyiqa', [])),
            'samp_net', 'u2netp', 'birefnet', 'insightface', 'mediapipe_face_landmarker',
            'qrealign_native', 'aesthetic_v25', 'deqa', 'yunet', 'sface', 'ofiq'):
        if candidate in routed and candidate not in order:
            order.append(candidate)
    order.extend(sorted(routed - set(order)))
    return order


def _report_model_licences(config_path, db_path, profile_name):
    """Licensing mode, the commercial status of each component in use, and face-model drift."""
    import licensing
    from db.embedding_space import embedding_model_for_policy
    try:
        from config_resolve import load_resolved
        cfg = load_resolved(config_path)
        pol = licensing.resolve_policy(cfg)
    except Exception as e:
        _warn("Licensing", f"could not resolve the configuration: {e}")
        return
    mode = pol.mode + (" (allow_unclear)" if pol.allow_unclear else "")
    _ok("Licensing mode", mode)
    _info("Scoring drift",
          f"scores are weighted for the '{pol.mode}' licensing mode; after changing the mode, "
          "photos scored under the other one keep their old aggregate until --recompute-average is run")
    if profile_name is None:
        _info("Profile", "unknown — showing the legacy profile's components")
    for component_id in _components_in_use(cfg, profile_name, pol):
        comp = licensing.COMPONENTS[component_id]
        label = f"{comp.name} ({component_id})"
        if not licensing.allowed(component_id, pol):
            hint = f" — use {comp.replacement}" if comp.replacement else ""
            _warn(label, f"not permitted in commercial mode (commercial use: {comp.commercial}){hint}")
        elif comp.commercial == 'yes':
            _ok(label, "commercial use: yes")
        elif comp.commercial == 'unclear':
            _info(label, f"commercial use: unclear ({comp.weights_licence})")
        else:
            _info(label, f"commercial use: no ({comp.weights_licence})")
    _warn_face_model_mismatch(db_path, embedding_model_for_policy(pol))


def _warn_face_model_mismatch(db_path, active_model):
    """Warn when stored face embeddings come from a model other than the active one."""
    from db.embedding_space import face_model_mismatch_message, mismatched_face_models
    if not os.path.exists(db_path):
        return
    try:
        uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = mismatched_face_models(conn, active_model)
        finally:
            conn.close()
    except sqlite3.Error:
        return  # no faces table / unreadable DB: reported by the database section
    for model, count in rows:
        _warn("Face embedding model", face_model_mismatch_message(model, count, active_model))


_CUDA_PROVIDER = "CUDAExecutionProvider"
_CPU_PROVIDER = "CPUExecutionProvider"
_PROBE_REASON_LIMIT = 300
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
# What ONNX Runtime writes when the provider cannot load, when a library it needs is missing,
# and when the provider loads but the session fails at runtime, most specific cause first.
_PROBE_CAUSES = (
    re.compile(r"Failed to load library .*? with error:\s*(.+)"),
    re.compile(r"(\S+: cannot open shared object file.*)"),
    re.compile(r"(CUDA failure \d+:[^;]*)"),
    re.compile(r"(Error loading .*)"),
)


def _torch_cuda_version(torch_module):
    """``torch.version.cuda``, or None for a CPU build, a ROCm build and a missing torch."""
    return getattr(getattr(torch_module, "version", None), "cuda", None)


def _log_fix(text):
    logger.warning("    %s", text)


def _log_distribution_fix(torch_cuda):
    """Fix line for a broken or doubled install: the GPU build when one applies, else the CPU build.

    ``repair_hint`` explains why no GPU wheel applies, which is not a way out of
    a state that has to be repaired, so the CPU command stands in for it.
    """
    from utils.onnx_runtime import CPU_REPAIR_COMMAND, repair_command
    _log_fix(f"Fix: {repair_command(torch_cuda) or CPU_REPAIR_COMMAND}")


@contextlib.contextmanager
def _captured_stderr_fd():
    """Collect what native code writes to file descriptor 2 inside the block, as one string in a list.

    ONNX Runtime reports a provider that fails to load from its C++ logger, so the
    reason never reaches Python's ``sys.stderr`` or the ``warnings`` machinery. If
    the descriptor cannot be redirected the block simply runs uncaptured.
    """
    captured = []
    try:
        sink = tempfile.TemporaryFile()
    except OSError:
        yield captured
        return
    try:
        saved = os.dup(2)
    except OSError:
        sink.close()
        yield captured
        return
    try:
        os.dup2(sink.fileno(), 2)
    except OSError:
        os.close(saved)
        sink.close()
        yield captured
        return
    try:
        yield captured
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        sink.seek(0)
        captured.append(sink.read().decode("utf-8", "replace"))
        sink.close()


def _probe_reason(lines):
    """Short reason the CUDA provider did not load, from the captured output lines; "" when there is none.

    ONNX Runtime colours its log lines with ANSI escapes, and those lines run to
    about 500 characters with the library name near the end, so the escapes go
    first and the cause is cut out of the line rather than the line truncated:
    ``... Failed to load library <path> with error: libcublasLt.so.13: cannot open
    shared object file ...`` yields ``libcublasLt.so.13: cannot ...``. A provider
    that loads but fails at runtime is reported by ONNX Runtime's Python layer on
    stdout as ``EP Error ... CUDA failure 35: CUDA driver version is insufficient
    ...``. Anything else falls back to the first line, truncated.
    """
    lines = [_ANSI_ESCAPE.sub("", line).strip() for line in lines]
    lines = [line for line in lines if line and not line.startswith("****")]
    for cause in _PROBE_CAUSES:
        for line in lines:
            match = cause.search(line)
            if match:
                return match.group(1).strip()[:_PROBE_REASON_LIMIT]
    return lines[0][:_PROBE_REASON_LIMIT] if lines else ""


def _probe_model_bytes():
    """A one-node Identity model, serialised; the lowest common denominator any ONNX Runtime loads.

    ``make_model`` stamps the newest IR version the installed ``onnx`` knows, which
    an older ONNX Runtime rejects, so the IR version is pinned.
    """
    from onnx import TensorProto, helper
    graph = helper.make_graph(
        [helper.make_node("Identity", ["x"], ["y"])], "facet_ort_probe",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    return model.SerializeToString()


def _probe_cuda_session(ort):
    """Build a tiny session asking for CUDA; ``(providers it really uses, reason)``, or None without ``onnx``.

    ``get_available_providers()`` lists what the wheel was compiled with, so it
    reads green for a CUDA 13 build beside a CUDA 12 PyTorch; only a session shows
    whether the provider loads. Called only on the CUDA runtime path, i.e. after the
    PyTorch section imported torch: torch maps the CUDA libraries that the provider
    then reuses, exactly as at scan time. The verdict is the first provider alone;
    the reason text is best effort and comes from three channels: the C++ logger
    (file descriptor 2), Python warnings, and the ``EP Error`` banner that the
    Python layer prints on stdout before retrying on the CPU. All three are
    captured so none reaches the doctor's own output.
    """
    try:
        model_bytes = _probe_model_bytes()
    except ImportError:
        return None
    options = ort.SessionOptions()
    options.log_severity_level = 3
    with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()) as stdout, \
            _captured_stderr_fd() as stderr_text:
        warnings.simplefilter("always")
        session = ort.InferenceSession(model_bytes, sess_options=options,
                                       providers=[_CUDA_PROVIDER, _CPU_PROVIDER])
    lines = [line for text in stderr_text for line in text.splitlines()]
    lines.extend(line for warning in caught for line in str(warning.message).splitlines())
    lines.extend(stdout.getvalue().splitlines())
    return list(session.get_providers()), _probe_reason(lines)


def _runs_on_cuda(providers):
    """True when a session's providers put CUDA first: it is the one that runs the graph.

    A session that lists CUDA behind the CPU provider (or only somewhere in the list) runs
    its nodes on the CPU, so presence alone is not a verdict.
    """
    return bool(providers) and providers[0] == _CUDA_PROVIDER


def _report_cuda_session(ort, torch_cuda):
    """The doctor's verdict on whether ONNX Runtime really runs on CUDA."""
    from utils.onnx_runtime import repair_hint
    try:
        probe = _probe_cuda_session(ort)
    except Exception as ex:
        _warn("CUDA session", f"could not be created: {ex}")
        _log_fix(repair_hint(torch_cuda))
        return
    if probe is None:
        _info("CUDA session", "not probed: the 'onnx' package is not installed")
        return
    providers, reason = probe
    if _runs_on_cuda(providers):
        _ok("CUDA session", f"a test InferenceSession runs on {_CUDA_PROVIDER}")
        return
    _warn("CUDA session", f"fell back to {providers}" + (f": {reason}" if reason else ""))
    _log_fix(repair_hint(torch_cuda))


def _report_onnx_runtime_cuda(ort, torch_cuda):
    """CUDA checks, for a runtime device of ``cuda`` only."""
    from utils.onnx_runtime import cuda_mismatch, repair_hint
    if not torch_cuda:
        _info("ONNX Runtime CUDA", "not applicable: this PyTorch build reports no CUDA version")
        return
    # No attribute or an empty string is the CPU wheel (or an old build): nothing to compare.
    mismatch = cuda_mismatch(getattr(ort, "cuda_version", None), torch_cuda)
    if mismatch:
        _warn("ONNX Runtime CUDA build", mismatch)
        _log_fix(repair_hint(torch_cuda))
    if _CUDA_PROVIDER not in ort.get_available_providers():
        _warn(_CUDA_PROVIDER, "missing - InsightFace runs on the CPU although Facet uses CUDA")
        _log_fix(repair_hint(torch_cuda))
        return
    _report_cuda_session(ort, torch_cuda)


def _import_onnxruntime():
    """``(module, None)``, or ``(None, why it is unusable)``; never raises.

    ``pip uninstall onnxruntime`` with ``onnxruntime-gpu`` still recorded removes
    the shared files but leaves the directory, and the import then succeeds as an
    empty namespace package: no version, no ``InferenceSession``, which is what
    InsightFace fails on. A plain ``pip install onnxruntime-gpu`` is a no-op in
    that state, so it has to read as a broken install, not a working one.
    """
    try:
        import onnxruntime as ort
    except Exception as ex:
        return None, ex
    missing = [name for name in ("__version__", "InferenceSession") if not hasattr(ort, name)]
    if missing:
        return None, f"module 'onnxruntime' has no attribute '{missing[-1]}' (an empty namespace package)"
    return ort, None


def _report_onnx_runtime(config_path, torch, selected_device):
    """InsightFace's inference engine: what is installed, and whether it really runs on CUDA (issue #229).

    ``onnxruntime`` and ``onnxruntime-gpu`` share files, ``insightface`` requires
    the CPU one, and nothing else tells the user when face detection silently ran
    on the CPU. ``torch`` is the module the PyTorch section imported, or None.
    """
    import licensing
    from utils.onnx_runtime import installed_distributions
    try:
        from config_resolve import load_resolved
        insightface_allowed = licensing.allowed('insightface', licensing.resolve_policy(load_resolved(config_path)))
    except Exception:
        insightface_allowed = True  # a configuration that cannot be resolved is reported by the licences section
    if not insightface_allowed:
        _info("ONNX Runtime", "not used in commercial mode (face detection runs on YuNet/SFace)")
        return
    torch_cuda = _torch_cuda_version(torch)
    distributions = installed_distributions()
    ort, import_error = _import_onnxruntime()
    if ort is None:
        if distributions:
            _warn("onnxruntime", f"installed ({', '.join(distributions)}) but cannot be imported: {import_error}")
            _log_distribution_fix(torch_cuda)
        else:
            _warn("onnxruntime", "NOT INSTALLED - InsightFace face detection is unavailable")
        return
    # Not [OK]: whether this install is healthy is only known once the lines below ran, and a
    # green version line above a "both packages installed" warning contradicts it.
    _info("onnxruntime", f"{ort.__version__} ({', '.join(distributions) or 'distribution unknown'})")
    _info("ONNX Runtime device", ort.get_device())
    _info("Execution providers", ", ".join(ort.get_available_providers()))
    if len(distributions) > 1:
        _warn("ONNX Runtime packages",
              "onnxruntime and onnxruntime-gpu are both installed; the CPU wheel overwrites the GPU wheel's "
              "shared libraries (issue #229)")
        _log_distribution_fix(torch_cuda)
    if selected_device == 'cuda':
        _report_onnx_runtime_cuda(ort, torch_cuda)


_OPENCV_HEADLESS = "opencv-python-headless"
_OPENCV_DISTRIBUTIONS = ("opencv-python", _OPENCV_HEADLESS)


def _installed_versions(names):
    """``{name: version}`` for those of ``names`` that pip has installed, in the order given."""
    found = {}
    for name in names:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def _opencv_fix(versions):
    """The command that leaves only the headless OpenCV build, at the version already installed.

    The headless distribution's version wins, as in ``install.sh``, so the repair does not move
    ``cv2`` to another release. With no distribution recorded there is nothing to uninstall.
    """
    version = versions.get(_OPENCV_HEADLESS) or versions.get("opencv-python")
    if version is None:
        return f"pip install {_OPENCV_HEADLESS}"
    return f'pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "{_OPENCV_HEADLESS}=={version}"'


def _import_opencv():
    """``(module, None)``, or ``(None, why it is unusable)``; never raises.

    ``opencv-python`` links ``libGL.so.1``, which Debian/WSL and slim hosts lack, so its ``cv2``
    fails to import there. Uninstalling one build of two can also leave a ``cv2/`` that imports
    as an empty namespace package: installing ``opencv-python`` over the headless build and then
    uninstalling the headless one leaves only the GUI build's ``cv2/qt/`` behind (observed with
    pip on a GPU host), and ``import cv2`` then succeeds with no ``__version__``. That must read
    as a broken install, not a working one.
    """
    try:
        cv2 = importlib.import_module("cv2")
    except Exception as ex:
        return None, f"{type(ex).__name__}: {ex}"
    if not hasattr(cv2, "__version__"):
        return None, "module 'cv2' has no attribute '__version__' (an empty namespace package)"
    return cv2, None


def _report_opencv():
    """Whether ``cv2`` imports, and which OpenCV distributions provide it.

    ``opencv-python`` and ``opencv-python-headless`` share one ``cv2/`` directory and the one
    installed last wins; ``insightface`` and ``facexlib`` pull the GUI build back in over the
    headless one ``pyiqa`` wants. Facet uses no OpenCV GUI, so only the headless build is needed.
    """
    versions = _installed_versions(_OPENCV_DISTRIBUTIONS)
    cv2, import_error = _import_opencv()
    if cv2 is None:
        _warn("cv2", f"cannot be imported: {import_error}")
        _log_fix(f"Fix: {_opencv_fix(versions)}")
        return
    described = f"{cv2.__version__} ({', '.join(versions) or 'distribution unknown'})"
    if len(versions) < len(_OPENCV_DISTRIBUTIONS):
        _ok("cv2", described)
        return
    # Not a warning: the Docker images ship both on purpose, with libgl1 installed.
    _info("cv2", described)
    _info("OpenCV packages", "both are installed and share cv2/; the one installed last provides it "
                             "(fine where libGL is present, as in the Docker images)")


# Exit codes of verify_onnx_runtime, read by install.sh's final check; the numbers in its `case`
# are kept in step with these by tests/test_onnx_runtime_install_consistency.py.
VERIFY_ON_CUDA = 0
VERIFY_NOT_ON_CUDA = 1
VERIFY_COULD_NOT_RUN = 2
VERIFY_LISTED_ONLY = 3


def verify_onnx_runtime():
    """install.sh's last check after a GPU install: print a short report, return a ``VERIFY_*`` code.

    Four outcomes, because "the check failed" and "ONNX Runtime is not on CUDA" call for
    different messages and the first must never be reported as the second:
    ``VERIFY_ON_CUDA`` a test session really runs on CUDA (the doctor's probe);
    ``VERIFY_LISTED_ONLY`` the CUDA provider is listed and ``onnxruntime-gpu`` is alone, but no
    session could be created (PyTorch sees no GPU on this machine, or the ``onnx`` package is
    missing), which is the strongest check possible there;
    ``VERIFY_NOT_ON_CUDA`` ONNX Runtime is broken, doubled, CPU-only or falls back to the CPU,
    with the repair text; ``VERIFY_COULD_NOT_RUN`` anything unexpected (torch fails to import,
    the session cannot be built). ``get_available_providers()`` alone is not enough: a CUDA 13
    wheel beside a CUDA 12 PyTorch lists the provider and then falls back.
    """
    try:
        # torch first: it maps the CUDA libraries the provider then reuses, as at scan time.
        import torch

        from utils.onnx_runtime import installed_distributions, repair_hint
        hint = repair_hint(_torch_cuda_version(torch))
        distributions = installed_distributions()
        ort, import_error = _import_onnxruntime()
        if ort is None:
            print(f"onnxruntime cannot be imported: {import_error} (distributions: {distributions})")
            print(hint)
            return VERIFY_NOT_ON_CUDA
        if distributions != ["onnxruntime-gpu"]:
            print(f"onnxruntime {ort.__version__}, distributions {distributions}: expected onnxruntime-gpu alone")
            print(hint)
            return VERIFY_NOT_ON_CUDA
        if _CUDA_PROVIDER not in ort.get_available_providers():
            print(f"onnxruntime-gpu {ort.__version__} does not offer {_CUDA_PROVIDER} "
                  f"(providers: {ort.get_available_providers()})")
            print(hint)
            return VERIFY_NOT_ON_CUDA
        listed = f"onnxruntime-gpu {ort.__version__}, {_CUDA_PROVIDER} listed"
        if not torch.cuda.is_available():
            print(listed)
            print("no CUDA session was created: PyTorch sees no GPU on this machine, so only the provider "
                  "listing was checked. Run 'python facet.py --doctor' on the GPU machine to prove it loads")
            return VERIFY_LISTED_ONLY
        probe = _probe_cuda_session(ort)
        if probe is None:
            print(listed)
            print("no CUDA session was created: the 'onnx' package is not installed, so only the provider "
                  "listing was checked")
            return VERIFY_LISTED_ONLY
        providers, reason = probe
        if _runs_on_cuda(providers):
            print(f"onnxruntime-gpu {ort.__version__}: a CUDA test session runs on {_CUDA_PROVIDER}")
            return VERIFY_ON_CUDA
        print(f"onnxruntime-gpu {ort.__version__}: the CUDA test session fell back to {providers}"
              + (f": {reason}" if reason else ""))
        print(hint)
        return VERIFY_NOT_ON_CUDA
    except Exception as ex:
        print(f"{type(ex).__name__}: {ex}")
        return VERIFY_COULD_NOT_RUN


def run_doctor(config_path=None, db_path=None, simulate_gpu=None, simulate_vram=None):
    """Run full diagnostic report.

    Args:
        config_path: Path to scoring config JSON file
        db_path: Path to database file
        simulate_gpu: Simulate a GPU name (e.g., "RTX 5070 Ti") for testing
        simulate_vram: Simulate VRAM in GB (e.g., 16.0) for testing
    """
    from config.scoring_config import resolve_scoring_config_path
    config_path = resolve_scoring_config_path(config_path)
    db_path = db_path or 'photo_scores_pro.db'
    simulating = simulate_gpu is not None
    torch = None
    selected_device = None
    has_mps = False
    arch_mismatch = None
    resolved_profile = None

    if simulating:
        vram_str = f", {simulate_vram:.0f}GB VRAM" if simulate_vram else ""
        logger.info("  [SIM] Simulation mode: %s%s", simulate_gpu, vram_str)

    # --- Python / Platform ---
    _section("Python / Platform")
    _ok("Python", sys.version.split('\n')[0])
    _ok("Platform", platform.platform())

    # --- Facet version ---
    _section("Facet")
    try:
        version = importlib.metadata.version('facet-photo')
        _ok("Version", version)
    except importlib.metadata.PackageNotFoundError:
        _info("Version", "not installed as package (running from source)")

    # --- PyTorch ---
    _section("PyTorch")
    if simulating:
        _info("torch", "skipped (simulation mode)")
        _info("CUDA", "skipped (simulation mode)")
    else:
        try:
            from utils.device import cuda_arch_mismatch, get_device, mps_available
            import torch
            has_mps = mps_available()
            arch_mismatch = cuda_arch_mismatch(torch_module=torch)
            _ok("torch", torch.__version__)
            cuda_version = torch.version.cuda or "None (CPU-only build)"
            if torch.version.cuda:
                _ok("CUDA (compiled)", cuda_version)
            elif has_mps:
                _info("CUDA (compiled)", "not applicable on Apple Metal")
            else:
                _warn("CUDA (compiled)", cuda_version)

            try:
                cudnn = torch.backends.cudnn.version()
                _ok("cuDNN", cudnn)
            except Exception:
                _info("cuDNN", "not available")

            if arch_mismatch is not None:
                _warn("torch.cuda.is_available()",
                      f"True, but no kernel can run on this GPU — {arch_mismatch.reason}")
            elif torch.cuda.is_available():
                _ok("torch.cuda.is_available()", "True")
            elif has_mps:
                _info("torch.cuda.is_available()", "False (using MPS)")
            else:
                _warn("torch.cuda.is_available()", "False")

            if has_mps:
                _ok("Apple Silicon (MPS)", "available")
            else:
                hint = " — Facet will run on CPU on this Mac" if sys.platform == "darwin" else ""
                _info("Apple Silicon (MPS)", f"not available{hint}")
            try:
                selected_device = get_device()
                _ok("Facet runtime device", selected_device)
                if selected_device == 'mps':
                    fallback = os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK', '0')
                    _info("MPS operator fallback", "enabled" if fallback == '1' else "disabled")
            except (RuntimeError, ValueError) as e:
                _warn("Facet runtime device", str(e))
        except ImportError:
            _warn("torch", "NOT INSTALLED")
            logger.warning("  Install PyTorch: pip install torch torchvision")
            torch = None

    # --- GPU ---
    if simulating:
        if simulate_vram is not None:
            _section("GPU (simulated)")
            _ok("Device", f"{simulate_gpu} (simulated)")
            _ok("VRAM", f"{simulate_vram:.1f} GB")
        else:
            # Simulate "driver sees GPU but torch doesn't" scenario
            _section("GPU Troubleshooting")
            _warn("GPU found by driver", f"{simulate_gpu} (simulated)")
            logger.warning("  PyTorch was built without CUDA support for your GPU.")
            logger.warning("  Your PyTorch CUDA version: None (CPU-only)")
            _log_pytorch_reinstall_hint("  Reinstall with the correct CUDA version:")
    elif torch is not None and selected_device == 'mps':
        _section("GPU")
        _ok("Device", "Apple Metal Performance Shaders (MPS)")
        _info("Memory", "unified with system RAM")
        _info("InsightFace", "ONNX Runtime CPU provider")

    elif torch is not None and _cuda_is_usable(torch):
        _section("GPU")
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024 ** 3)
        _ok("Device", name)
        _ok("VRAM", f"{vram_gb:.1f} GB")
        _ok("Compute capability", f"{props.major}.{props.minor}")

        # Driver version via nvidia-smi
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                _ok("Driver", result.stdout.strip())
        except Exception:
            pass

        from utils.device import torch_compile_status
        compile_enabled, compile_reason = torch_compile_status()
        if compile_enabled:
            _ok("torch.compile", "enabled (C compiler available)")
        elif os.environ.get('TORCH_COMPILE_DISABLE'):
            _info("torch.compile", "disabled — TORCH_COMPILE_DISABLE is set; eager CUDA inference")
        else:
            _warn("torch.compile", f"disabled — {compile_reason}; eager CUDA inference")
            logger.warning("    This is expected and fine in minimal Docker images; torch.compile is auto-disabled.")

    elif torch is not None and arch_mismatch is not None:
        _section("GPU Troubleshooting")
        _report_cuda_arch_mismatch(arch_mismatch)

    elif torch is not None and not has_mps:
        _section("GPU Troubleshooting")
        # Check if nvidia-smi sees a GPU even though PyTorch can't use it
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_info = result.stdout.strip()
                _warn("GPU found by driver", gpu_info)
                logger.warning("  PyTorch was built without CUDA support for your GPU.")
                logger.warning("  Your PyTorch CUDA version: %s", torch.version.cuda or "None (CPU-only)")
                _log_pytorch_reinstall_hint("  Reinstall with the correct CUDA version:")
            else:
                _info("nvidia-smi", "no GPU found — is a GPU installed?")
        except FileNotFoundError:
            _warn("nvidia-smi", "not found — NVIDIA driver may not be installed")
            logger.warning("  Install the NVIDIA driver for your GPU, then reinstall PyTorch with CUDA.")
        except Exception as e:
            _warn("nvidia-smi", f"error: {e}")

    # --- OpenCV --- (its own section: core in every mode, unlike ONNX Runtime, which commercial mode drops)
    _section("OpenCV")
    try:
        _report_opencv()
    except Exception as e:
        _warn("OpenCV check", f"failed unexpectedly: {e}")

    # --- ONNX Runtime ---
    _section("ONNX Runtime")
    try:
        _report_onnx_runtime(config_path, torch, selected_device)
    except Exception as e:
        _warn("ONNX Runtime check", f"failed unexpectedly: {e}")

    # --- VRAM Profile ---
    _section("VRAM Profile")
    try:
        from config.scoring_config import ScoringConfig
        profile_vram = simulate_vram if simulating else None
        suggested, vram_gb, msg = ScoringConfig.suggest_vram_profile(vram_gb=profile_vram)
        _ok("Recommended", msg)

        # No os.path.exists guard: an absent override is an install running on
        # the shipped defaults, and ScoringConfig resolves that fine. Guarding
        # on the file dropped the configured profile, the auto note and the
        # mismatch warning on exactly the install whose profile nobody has
        # inspected yet.
        config = ScoringConfig(config_path, validate=False)
        current = config.get_model_config().get('vram_profile', 'legacy')
        _ok("Configured", current)
        resolved_profile = suggested if current == 'auto' else current
        if current == 'auto':
            _info("Note", "auto mode will select the recommended profile at runtime")
        elif current != suggested:
            _warn("Mismatch", f"configured '{current}' but recommended '{suggested}'")
    except Exception as e:
        _warn("Profile detection", str(e))

    # --- Optional Dependencies ---
    _section("Optional Dependencies")
    optional_deps = [
        ('transformers', 'BiRefNet saliency, SigLIP 2 NaFlex, VLM tagging'),
        ('accelerate', 'VLM tagging (16gb/24gb profiles)'),
        ('rawpy', 'RAW file support'),
    ]
    for module, purpose in optional_deps:
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, '__version__', 'installed')
            _ok(module, f"{version} — {purpose}")
        except ImportError:
            _info(module, f"not installed — {purpose}")

    # exiftool
    exiftool_path = shutil.which('exiftool')
    if exiftool_path:
        try:
            result = subprocess.run(
                ['exiftool', '-ver'], capture_output=True, text=True, timeout=5,
            )
            _ok("exiftool", f"{result.stdout.strip()} ({exiftool_path})")
        except Exception:
            _ok("exiftool", exiftool_path)
    else:
        _warn("exiftool", "not found in PATH — EXIF extraction will be limited")

    # darktable-cli (only checked when configured as RAW processor)
    try:
        from config_resolve import load_resolved
        raw_proc = load_resolved(config_path).get('viewer', {}).get('raw_processor', {})
    except Exception:
        raw_proc = {}

    if raw_proc.get('backend') == 'darktable':
        dt_exec = raw_proc.get('darktable', {}).get('executable', 'darktable-cli')
        dt_path = shutil.which(dt_exec) if not os.path.isabs(dt_exec) else dt_exec
        if dt_path and os.path.isfile(dt_path):
            try:
                result = subprocess.run(
                    [dt_path, '--version'], capture_output=True, text=True, timeout=5,
                )
                version = result.stdout.strip().split('\n')[0] if result.stdout else ''
                _ok("darktable-cli", f"{version} ({dt_path})" if version else dt_path)
            except Exception:
                _ok("darktable-cli", dt_path)
        else:
            _warn("darktable-cli", f"not found ({dt_exec}) — RAW downloads will fail")

    # --- Model licences ---
    _section("Model licences")
    _report_model_licences(config_path, db_path, resolved_profile)

    # --- Config & Database ---
    _section("Config / Database")
    from config_resolve import path_is_named
    if os.path.exists(config_path):
        size_kb = os.path.getsize(config_path) / 1024
        _ok("Config", f"{config_path} ({size_kb:.1f} KB)")
    elif path_is_named(config_path):
        # A path a human named cannot be missing by accident, and reading it as
        # "no overrides" is what the rest of the toolchain refuses to do.
        _warn("Config", f"{config_path} was named explicitly but does not exist")
    else:
        _ok("Config", f"no override at {config_path} — running on the shipped defaults")
    notices_config = None
    try:
        from config.scoring_config import ScoringConfig
        notices_config = ScoringConfig(config_path, validate=False)
        schema_errors = notices_config.validate_schema()
        if not schema_errors:
            _ok("Config schema", "valid")
        else:
            for err in schema_errors[:5]:
                _warn("Config schema", err)
    except Exception as e:
        _warn("Config schema", str(e))

    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        _ok("Database", f"{db_path} ({size_mb:.1f} MB)")
        try:
            with sqlite3.connect(db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            _ok("Photos", f"{count:,}")
        except Exception as e:
            _warn("Database query", str(e))

        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute("PRAGMA quick_check").fetchall()
            if len(rows) == 1 and rows[0][0] == "ok":
                _ok("Integrity", "ok")
            else:
                detail = "; ".join(str(r[0]) for r in rows[:3])
                _warn("Integrity", detail or "corruption detected")
        except Exception as e:
            _warn("Integrity", str(e))

        try:
            from db.info import get_user_version
            from db.schema import SCHEMA_VERSION
            db_version = get_user_version(db_path)
            if db_version == SCHEMA_VERSION:
                _ok("Schema version", str(db_version))
            else:
                _warn("Schema version",
                      f"{db_version} (code expects {SCHEMA_VERSION}) — run database.py to upgrade")
        except Exception as e:
            _warn("Schema version", str(e))

        # --- Fast-path Availability ---
        check_fast_paths(db_path)
    else:
        _info("Database", f"{db_path} not found (will be created on first scan)")

    if notices_config is not None:
        _report_config_notices(notices_config)


def _report_config_notices(config):
    """Print the keys an operator file carries that are ignored or have moved.

    Each notice is something that changes nothing on its own but means the
    operator's intent is not being applied (an obsolete key stays inert by
    design: there are no aliases).
    """
    _section("Config notices")
    try:
        # The astro-guard notice is doctor-only: it is the operator's choice to keep it off
        notices = [*config.config_notices(), *config.validate_astro_guard()]
    except Exception as e:
        _warn("Config notices", f"could not evaluate: {e}")
        return
    if not notices:
        _ok("Config notices", "none")
    for message in notices:
        _warn("Config notice", message)


def check_fast_paths(db_path):
    """Probe each perf-critical fast path against the DB on disk.

    Reports the same fast paths /metrics exposes (sqlite-vec, FTS5,
    photo_tags, stats_cache). This is the one-command verification an
    operator can run before deploying — answers "is the production
    deploy going to actually use the intended fast paths?" without
    starting the API.
    """
    _section("Fast-path Availability")

    # sqlite-vec extension installable
    try:
        import sqlite_vec
        vec_version = getattr(sqlite_vec, "__version__", "unknown")
        _ok("sqlite-vec installable", f"v{vec_version}")
        sqlite_vec_module = sqlite_vec
    except ImportError:
        _warn("sqlite-vec installable", "package not installed — /api/search will use NumPy fallback")
        sqlite_vec_module = None

    # Direct DB probes — use a fresh connection so we measure on-disk state,
    # not anything cached by a running API.
    try:
        with sqlite3.connect(db_path) as conn:
            # photos_vec table populated?
            # Extension load can raise NotSupportedError on CPython builds
            # compiled without --enable-loadable-sqlite-extensions (common on
            # Windows/macOS stock binaries). Catch broadly and continue so
            # the photos_fts / photo_tags / stats_cache probes that follow
            # remain independent.
            try:
                if sqlite_vec_module is not None:
                    conn.enable_load_extension(True)
                    sqlite_vec_module.load(conn)
                    conn.enable_load_extension(False)
            except Exception as e:
                _warn("sqlite-vec load", str(e))
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_vec'"
                ).fetchone()
                if row and row[0]:
                    n = conn.execute("SELECT COUNT(*) FROM photos_vec").fetchone()[0]
                    if n > 0:
                        _ok("photos_vec populated", f"{n:,} embeddings")
                    else:
                        _warn("photos_vec populated", "table exists but empty — run database.py --populate-vec")
                else:
                    _warn("photos_vec populated", "table missing — run database.py --populate-vec")
            except sqlite3.OperationalError as e:
                _warn("photos_vec query", str(e))

            # photos_fts table indexed?
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_fts'"
                ).fetchone()
                if row and row[0]:
                    n = conn.execute("SELECT COUNT(*) FROM photos_fts").fetchone()[0]
                    _ok("photos_fts indexed", f"{n:,} rows")
                else:
                    _warn("photos_fts indexed", "table missing — run database.py --rebuild-fts")
            except sqlite3.OperationalError as e:
                _warn("photos_fts query", str(e))

            # photo_tags lookup table?
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photo_tags'"
                ).fetchone()
                if row and row[0]:
                    n = conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()[0]
                    if n > 0:
                        _ok("photo_tags populated", f"{n:,} entries")
                    else:
                        _warn(
                            "photo_tags populated",
                            "table exists but empty — run database.py --migrate-tags",
                        )
                else:
                    _warn("photo_tags populated", "table missing — run database.py --migrate-tags")
            except sqlite3.OperationalError as e:
                _warn("photo_tags query", str(e))

            # stats_cache age — read the table directly instead of the
            # in-memory cache (we're not in the API process).
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MAX(strftime('%s','now') - strftime('%s', updated_at)) "
                    "FROM stats_cache WHERE value IS NOT NULL"
                ).fetchone()
                if row and row[0]:
                    n, max_age = row[0], row[1] or 0
                    hours = max_age / 3600.0
                    if hours > 5:
                        _info("stats_cache",
                              f"{n} entries, oldest {hours:.1f}h (stale — run database.py --refresh-stats)")
                    else:
                        _ok("stats_cache", f"{n} entries, oldest {hours:.1f}h")
                else:
                    _info("stats_cache", "empty — run database.py --refresh-stats")
            except sqlite3.OperationalError:
                _info("stats_cache", "table missing — run database.py --refresh-stats")
    except sqlite3.Error as e:
        _warn("Fast-path probe", str(e))


def main():
    """Entry point for facet-doctor CLI."""
    import argparse

    from utils.cli_logging import configure_cli_logging
    configure_cli_logging()

    parser = argparse.ArgumentParser(description='Facet diagnostic tool')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to scoring config JSON file')
    parser.add_argument('--db', type=str, default='photo_scores_pro.db',
                        help='Path to database file')
    parser.add_argument('--simulate-gpu', type=str, default=None, metavar='NAME',
                        help='Simulate GPU (e.g., "RTX 5070 Ti")')
    parser.add_argument('--simulate-vram', type=float, default=None, metavar='GB',
                        help='Simulate VRAM in GB (e.g., 16)')
    args = parser.parse_args()
    run_doctor(config_path=args.config, db_path=args.db,
               simulate_gpu=args.simulate_gpu, simulate_vram=args.simulate_vram)


if __name__ == '__main__':
    main()
