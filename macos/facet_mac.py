"""The macOS app's Python side: paths, environment setup, config writes and checks.

The Swift launcher runs this with the interpreter bundled in Facet.app (stdlib only,
``python3 -I``) and only draws what it prints, so everything that decides something
lives here, where the rest of Facet is reviewed and tested.

    facet_mac.py serve PORT    become the viewer on 127.0.0.1:PORT, in a process group of its own
    facet_mac.py env           JSON: what the viewer runs with (python, args, cwd, env)
    facet_mac.py ready         exit 0 and print setup's GPU check when the environment matches
                               this app build, else exit 1
    facet_mac.py setup         build or repair the environment, printing @FACET_PROGRESS lines
    facet_mac.py add-folder P  add P to viewer.scan_directories
    facet_mac.py folders       JSON: the configured scan folders
    facet_mac.py doctor        JSON: torch, MPS and free disk, from the environment's interpreter

The app bundle is read-only (it is signed, and macOS may run it from a translocated
copy), so nothing here writes inside it: the environment, config, library, models and
caches all live under the user's Library folder.
"""

import sys

# This runs from inside the signed bundle: bytecode written next to its imports would break the seal.
sys.dont_write_bytecode = True

import fcntl  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

APP_ROOT = Path(__file__).resolve().parent.parent          # Facet.app/Contents/Resources/app
# Facet's own stdlib-only modules (config_resolve, processing.progress) load from the app.
sys.path.insert(0, str(APP_ROOT))

import config_resolve  # noqa: E402
from processing.progress import emit_progress  # noqa: E402

RESOURCES = APP_ROOT.parent                                # Facet.app/Contents/Resources
BUNDLED_PYTHON = RESOURCES / 'python' / 'bin' / 'python3'
UV = RESOURCES / 'bin' / 'uv'
EXIFTOOL_DIR = RESOURCES / 'exiftool'
LOCK = APP_ROOT / 'macos' / 'requirements.lock.txt'
BUILD_CONSTRAINTS = APP_ROOT / 'macos' / 'build-constraints.txt'
BUILD_LABEL = APP_ROOT / 'macos' / 'build-label.txt'

# FACET_HOME puts everything in one folder instead (tests, CI), as on Windows.
if os.environ.get('FACET_HOME'):
    SUPPORT = Path(os.environ['FACET_HOME'])
    CACHES, LOGS = SUPPORT / 'cache', SUPPORT / 'logs'
else:
    SUPPORT = Path.home() / 'Library' / 'Application Support' / 'Facet'
    CACHES = Path.home() / 'Library' / 'Caches' / 'Facet'
    LOGS = Path.home() / 'Library' / 'Logs' / 'Facet'
VENV = SUPPORT / 'venv'
VENV_PYTHON = VENV / 'bin' / 'python'
MARKER = VENV / '.facet-setup.json'
CONFIG = SUPPORT / 'config' / 'scoring_config.json'
LIBRARY = SUPPORT / 'library'
DB = LIBRARY / 'photo_scores_pro.db'

# Bump when setup builds the environment differently; the lock and interpreter are keyed already.
SETUP_VERSION = 1
# Free space the environment needs (1.5 GB installed, plus the download cache), checked up front.
ENVIRONMENT_FREE_BYTES = 3 * 10 ** 9
# A fresh install may edit and scan from the browser on this Mac only; api/auth.py
# request_is_local refuses forwarded, cross-origin and non-loopback requests.
SEEDED_CONFIG = {'viewer': {'trusted_local_editing': True}}

_DOWNLOADING = re.compile(r'^Downloading (\S+) \(([\d.]+)(KiB|MiB|GiB)\)$')
_DOWNLOADED = re.compile(r'^ Downloaded (\S+)$')
_UNIT = {'KiB': 2 ** 10, 'MiB': 2 ** 20, 'GiB': 2 ** 30}


def _env_vars():
    """Variables every Facet process of this app runs with; scans inherit them from the viewer."""
    env = {
        'FACET_CONFIG': str(CONFIG),
        'DB_PATH': str(DB),
        'FACET_MODELS_DIR': str(SUPPORT / 'models'),
        'FACET_PLUGINS_DIR': str(SUPPORT / 'plugins'),
        'HF_HOME': str(SUPPORT / 'huggingface'),
        'TORCH_HOME': str(SUPPORT / 'torch'),
        # Bytecode would otherwise be written next to the sources, inside the signed bundle.
        'PYTHONPYCACHEPREFIX': str(CACHES / 'pycache'),
        'PYTHONIOENCODING': 'utf-8',
        'PATH': f"{EXIFTOOL_DIR}{os.pathsep}/usr/bin{os.pathsep}/bin{os.pathsep}/usr/sbin{os.pathsep}/sbin",
    }
    if BUILD_LABEL.is_file():
        env['FACET_BUILD'] = BUILD_LABEL.read_text().strip()
    return env


# The only variables of the user's session a Facet process inherits; the rest is set here.
_SESSION_ENV = ('HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL')
# A proxy is how some networks reach PyPI at all.
_PROXY_ENV = ('HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy')


def _session_env(names=_SESSION_ENV):
    return {k: os.environ[k] for k in names if k in os.environ}


def _uv_env():
    # Ambient UV_* variables and uv config (an index, exclude-newer, a cache) must not reach
    # this install, and uv's interpreter probe must not write bytecode into the bundled Python.
    return {**_session_env(_SESSION_ENV + _PROXY_ENV), 'PATH': '/usr/bin:/bin',
            'UV_NO_CONFIG': '1', 'UV_CACHE_DIR': str(CACHES / 'uv'),
            'UV_PYTHON_DOWNLOADS': 'never', 'NO_COLOR': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            # The Mac's own trust store, so a network that inspects TLS still works; hashes pin the files.
            'UV_SYSTEM_CERTS': '1'}


def _child_env():
    """What setup's own runs of the environment's Python get: the session basics and Facet's paths."""
    return {**_session_env(), **_env_vars()}


def setup_key():
    """What the environment was built from. A change in any part means build it again.

    The interpreter's real path is part of it: a venv points at its base interpreter by
    absolute path, so moving or renaming the app breaks the old one.
    """
    digest = hashlib.sha256()
    for part in (LOCK.read_bytes(), BUILD_CONSTRAINTS.read_bytes(), str(SETUP_VERSION).encode(),
                 str(BUNDLED_PYTHON.resolve()).encode(), sys.version.encode()):
        digest.update(hashlib.sha256(part).digest())
    return digest.hexdigest()


def ready_report():
    """The GPU check setup saved, or None when the environment must be built again."""
    try:
        marker = json.loads(MARKER.read_text())
    except (OSError, ValueError):
        return None
    return marker.get('doctor') if marker.get('key') == setup_key() and VENV_PYTHON.exists() else None


def emit(phase, current=None, total=None, **extra):
    emit_progress(phase, current, total, extra=extra, force=True)


class SetupError(RuntimeError):
    """A failure the app names in the user's language: macos_app.setup.error_<code>, filled
    with ``params``. The English message goes to setup.log."""

    def __init__(self, code, message, **params):
        super().__init__(message)
        self.code, self.params = code, params


def _run_uv(args, log):
    """Run uv, turning its download lines into byte progress."""
    announced, done = {}, set()
    proc = subprocess.Popen([str(UV), *args], env=_uv_env(), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        log.write(line)
        line = line.rstrip('\n')
        if match := _DOWNLOADING.match(line):
            announced[match[1]] = int(float(match[2]) * _UNIT[match[3]])
        elif match := _DOWNLOADED.match(line):
            done.add(match[1])
        else:
            continue
        total = sum(announced.values())
        emit('environment', sum(size for name, size in announced.items() if name in done), total)
    if proc.wait():
        raise SetupError('download', f'uv {args[0]} failed (exit {proc.returncode}); see {log.name}')


def _check_free_space():
    SUPPORT.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(SUPPORT).free
    if free < ENVIRONMENT_FREE_BYTES:
        free_gb, needed_gb = f'{free / 1e9:.1f}', f'{ENVIRONMENT_FREE_BYTES / 1e9:.0f}'
        raise SetupError('no_space', f'Not enough free space: {free_gb} GB free, {needed_gb} GB needed',
                         free=free_gb, needed=needed_gb)


def _seed_config():
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        config_resolve.write_user_config(str(CONFIG), SEEDED_CONFIG)


def setup():
    """Build the environment in a sibling folder and swap it in, so a failed run never
    leaves a half-built environment behind that blocks the next attempt."""
    SUPPORT.mkdir(parents=True, exist_ok=True)
    # Two setups would share venv.partial; the OS drops the lock with a killed one.
    with open(SUPPORT / 'setup.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError('busy', 'Facet is already being set up by another copy of the app') from None
        # Another copy may have finished while this one waited to be retried.
        if ready_report() is None:
            _build_environment()
        else:
            emit('done', doctor=ready_report())


def _build_environment():
    for directory in (LOGS, CACHES, LIBRARY, SUPPORT / 'models', SUPPORT / 'plugins'):
        directory.mkdir(parents=True, exist_ok=True)
    staging = SUPPORT / 'venv.partial'
    with open(LOGS / 'setup.log', 'w') as log:    # opened first, so a failure lands in this run's log
        _check_free_space()
        emit('environment', 0, 0)
        shutil.rmtree(staging, ignore_errors=True)
        _run_uv(['venv', '--quiet', '--relocatable', '--python', str(BUNDLED_PYTHON), str(staging)], log)
        # Hashes cover the build dependencies too, for the packages PyPI has only as source.
        _run_uv(['pip', 'sync', '--require-hashes', '--require-build-hashes',
                 '--preview-features', 'build-dependency-hashes', '--build-constraints', str(BUILD_CONSTRAINTS),
                 '--python', str(staging / 'bin' / 'python'), str(LOCK)], log)
        shutil.rmtree(VENV, ignore_errors=True)
        staging.rename(VENV)

        emit('library')
        _seed_config()
        env = _child_env()
        if subprocess.run([str(VENV_PYTHON), str(APP_ROOT / 'database.py')], cwd=LIBRARY, env=env,
                          stdout=log, stderr=subprocess.STDOUT).returncode:
            raise SetupError('library', f'database.py failed; see {log.name}')

        emit('check')
        try:
            report = doctor()
        except (subprocess.CalledProcessError, ValueError, IndexError) as ex:
            log.write(getattr(ex, 'stderr', None) or f'{ex}\n')
            raise SetupError('check', f'the GPU check failed ({ex}); see {log.name}') from ex
        log.write(json.dumps(report) + '\n')
        MARKER.write_text(json.dumps({'key': setup_key(), 'doctor': report}))
    emit('done', doctor=report)


_DOCTOR = """
import json, torch
mps = torch.backends.mps.is_available()
ok = False
if mps:
    ok = (torch.ones(4, device='mps') * 2).sum().item() == 8.0
print(json.dumps({'torch': torch.__version__, 'mps': mps, 'mps_works': ok}))
"""


def doctor():
    out = subprocess.run([str(VENV_PYTHON), '-c', _DOCTOR], env=_child_env(),
                         capture_output=True, text=True, check=True).stdout
    report = json.loads(out.strip().splitlines()[-1])
    report['free_gb'] = round(shutil.disk_usage(SUPPORT).free / 1e9, 1)
    return report


def _resolved_config():
    _seed_config()
    return config_resolve.load_resolved(str(CONFIG), named=True)


def folders():
    config = _resolved_config()
    return config.get('viewer', {}).get('scan_directories', [])


def add_folder(path):
    folder = str(Path(path).expanduser().resolve())
    if not Path(folder).is_dir():
        raise SystemExit(f'Not a folder: {folder}')
    config = _resolved_config()
    viewer = config.setdefault('viewer', {})
    current = viewer.get('scan_directories', [])
    if folder not in current:
        viewer['scan_directories'] = [*current, folder]
        config_resolve.write_user_config(str(CONFIG), config)
    return viewer['scan_directories']


def launch_spec():
    return {
        'python': str(VENV_PYTHON),
        'args': [str(APP_ROOT / 'viewer.py'), '--production', '--host', '127.0.0.1'],
        'cwd': str(LIBRARY),
        'env': _env_vars(),
        'logs': str(LOGS),
    }


def serve(port):
    """Replace this process with the viewer. Its own session makes it a process group the
    app can stop in one signal, scans it spawned included."""
    spec = launch_spec()
    # The app's Process already starts this as a group leader, and setsid() refuses one (EPERM).
    if os.getpgrp() != os.getpid():
        os.setsid()
    os.chdir(spec['cwd'])
    os.execve(spec['python'], [spec['python'], *spec['args'], '--port', str(port)], {**_session_env(), **spec['env']})


def main(argv):
    command = argv[1] if len(argv) > 1 else ''
    if command == 'serve' and len(argv) == 3 and argv[2].isdigit():
        serve(int(argv[2]))
    elif command == 'env':
        print(json.dumps(launch_spec()))
    elif command == 'ready':
        report = ready_report()
        if report is None:
            return 1
        print(json.dumps(report))
    elif command == 'setup':
        try:
            setup()
        except Exception as ex:
            # A refused second setup leaves the log to the one that holds the lock.
            if getattr(ex, 'code', None) != 'busy':
                LOGS.mkdir(parents=True, exist_ok=True)
                with open(LOGS / 'setup.log', 'a') as log:
                    log.write(f'Setup failed: {ex}\n')
            if isinstance(ex, SetupError):
                emit('error', message=str(ex), code=ex.code, params=ex.params)
            else:
                emit('error', message=str(ex))
            return 1
    elif command == 'add-folder' and len(argv) == 3:
        print(json.dumps(add_folder(argv[2])))
    elif command == 'folders':
        print(json.dumps(folders()))
    elif command == 'doctor':
        print(json.dumps(doctor()))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
