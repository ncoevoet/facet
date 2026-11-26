"""macos/facet_mac.py, the Python side of Facet.app: setup progress, the environment
check, and the config writes the menu-bar app makes."""

import ast
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from processing.progress import PROGRESS_PREFIX

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / 'macos' / 'facet_mac.py'

# The app is macOS-only, and these tests run fake tools as shell scripts.
pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='macOS app helper')


@pytest.fixture
def mac(tmp_path, monkeypatch):
    # The module reads FACET_HOME at import, so each test gets a fresh copy.
    monkeypatch.setenv('FACET_HOME', str(tmp_path / 'home'))
    # The helper sets sys.dont_write_bytecode and prepends to sys.path at import.
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    spec = importlib.util.spec_from_file_location('facet_mac_under_test', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _events(output, prefix):
    return [json.loads(line[len(prefix):]) for line in output.splitlines() if line.startswith(prefix)]


def test_uv_download_lines_become_byte_progress(mac, tmp_path, capsys):
    fake_uv = tmp_path / 'uv'
    fake_uv.write_text('#!/bin/sh\n'
                       'echo "Resolved 3 packages"\n'
                       'echo "Downloading torch (2.0MiB)"\n'
                       'echo "Downloading numpy (512KiB)"\n'
                       'echo " Downloaded numpy"\n'
                       'echo " Downloaded torch"\n'
                       'echo "Installed 3 packages"\n')
    fake_uv.chmod(0o755)
    mac.UV = fake_uv
    log = tmp_path / 'setup.log'
    with open(log, 'w') as handle:
        mac._run_uv(['pip', 'sync'], handle)

    total = 2 * 2 ** 20 + 512 * 2 ** 10
    events = _events(capsys.readouterr().out, PROGRESS_PREFIX)
    assert [(e['current'], e['total']) for e in events] == [
        (0, 2 * 2 ** 20), (0, total), (512 * 2 ** 10, total), (total, total)]
    assert 'Installed 3 packages' in log.read_text()


def test_uv_failure_raises_with_the_log(mac, tmp_path):
    fake_uv = tmp_path / 'uv'
    fake_uv.write_text('#!/bin/sh\necho "error: no wheel"\nexit 2\n')
    fake_uv.chmod(0o755)
    mac.UV = fake_uv
    with open(tmp_path / 'setup.log', 'w') as handle, pytest.raises(RuntimeError, match='exit 2'):
        mac._run_uv(['pip', 'sync'], handle)


def test_setup_key_follows_the_lock(mac, tmp_path):
    mac.LOCK = tmp_path / 'requirements.lock.txt'
    mac.LOCK.write_text('torch==2.11.0\n')
    before = mac.setup_key()
    assert mac.setup_key() == before
    mac.LOCK.write_text('torch==2.12.0\n')
    assert mac.setup_key() != before


def test_uv_runs_without_the_users_uv_settings(mac, monkeypatch):
    monkeypatch.setenv('UV_INDEX_URL', 'https://mirror.example/simple')
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.example:3128')
    env = mac._uv_env()
    assert 'UV_INDEX_URL' not in env and env['UV_NO_CONFIG'] == '1'
    assert env['HTTPS_PROXY'] == 'http://proxy.example:3128'


def test_setup_key_follows_the_setup_version_not_the_helper_text(mac, monkeypatch):
    before = mac.setup_key()
    monkeypatch.setattr(mac, 'SETUP_VERSION', mac.SETUP_VERSION + 1)
    assert mac.setup_key() != before


def test_ready_only_for_an_environment_built_from_this_app(mac, tmp_path):
    mac.LOCK = tmp_path / 'requirements.lock.txt'
    mac.LOCK.write_text('torch==2.11.0\n')
    assert mac.ready_report() is None

    mac.VENV_PYTHON.parent.mkdir(parents=True)
    mac.VENV_PYTHON.touch()
    report = {'torch': '2.11.0', 'mps': True, 'mps_works': True}
    mac.MARKER.write_text(json.dumps({'key': mac.setup_key(), 'doctor': report}))
    assert mac.ready_report() == report

    mac.LOCK.write_text('torch==2.12.0\n')
    assert mac.ready_report() is None


def test_add_folder_writes_only_the_override(mac, tmp_path):
    photos = tmp_path / 'Photos'
    photos.mkdir()
    assert mac.folders() == []
    assert mac.add_folder(str(photos)) == [str(photos.resolve())]
    assert mac.add_folder(str(photos)) == [str(photos.resolve())]

    written = json.loads(mac.CONFIG.read_text())
    assert written == {'viewer': {'trusted_local_editing': True,
                                  'scan_directories': [str(photos.resolve())]}}
    # The config can hold a password and API keys in plaintext.
    assert stat.S_IMODE(mac.CONFIG.stat().st_mode) == 0o600
    assert mac.folders() == [str(photos.resolve())]


def test_add_folder_refuses_a_missing_folder(mac, tmp_path):
    with pytest.raises(SystemExit, match='Not a folder'):
        mac.add_folder(str(tmp_path / 'missing'))


def test_everything_writable_lives_outside_the_bundle(mac, tmp_path):
    spec = mac.launch_spec()
    home = tmp_path / 'home'
    for key in ('FACET_CONFIG', 'DB_PATH', 'FACET_MODELS_DIR', 'FACET_PLUGINS_DIR',
                'HF_HOME', 'TORCH_HOME', 'PYTHONPYCACHEPREFIX'):
        assert Path(spec['env'][key]).is_relative_to(home), key
    assert Path(spec['cwd']).is_relative_to(home)
    assert spec['args'][-2:] == ['--host', '127.0.0.1']


def test_setup_failure_is_reported_as_an_event(mac, monkeypatch, capsys):
    monkeypatch.setattr(mac, 'ENVIRONMENT_FREE_BYTES', 10 ** 18)
    assert mac.main([str(HELPER), 'setup']) == 1
    events = _events(capsys.readouterr().out, PROGRESS_PREFIX)
    assert events[-1]['phase'] == 'error' and events[-1]['code'] == 'no_space'
    assert 'Not enough free space' in events[-1]['message']
    assert set(events[-1]['params']) == {'free', 'needed'}
    assert 'Not enough free space' in (mac.LOGS / 'setup.log').read_text()


@pytest.mark.parametrize('group_leader', [True, False], ids=['started-by-the-app', 'started-from-a-shell'])
def test_serve_runs_the_viewer_in_a_process_group_of_its_own(tmp_path, group_leader):
    # The app's Foundation Process starts the helper as a group leader; a shell does not.
    home = tmp_path / 'home'
    fake_python = home / 'venv' / 'bin' / 'python'
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text('#!/bin/sh\n/bin/ps -o pid=,pgid= -p $$\n')
    fake_python.chmod(0o755)
    (home / 'library').mkdir()
    result = subprocess.run([sys.executable, '-I', str(HELPER), 'serve', '5999'],
                            env={'FACET_HOME': str(home), 'PATH': '/usr/bin:/bin'},
                            capture_output=True, text=True, timeout=30,
                            process_group=0 if group_leader else None)
    assert result.returncode == 0, result.stderr
    pid, pgid = result.stdout.split()
    assert pid == pgid


def test_every_setup_error_has_its_text_in_every_language():
    # The app shows macos_app.setup.error_<code>; a code without text would show its key.
    import re
    codes = set(re.findall(r"SetupError\('(\w+)'", HELPER.read_text()))
    assert codes
    for translation in sorted((REPO / 'i18n' / 'translations').glob('*.json')):
        setup_text = json.loads(translation.read_text())['macos_app']['setup']
        assert {f'error_{code}' for code in codes} <= setup_text.keys(), translation.name


def test_unknown_command_prints_usage(mac, capsys):
    assert mac.main([str(HELPER), 'nope']) == 2
    assert 'facet_mac.py serve PORT' in capsys.readouterr().err


def _imports(path):
    tree = ast.parse(path.read_text())
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    return names | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


@pytest.mark.parametrize('source', ['macos/facet_mac.py', 'processing/progress.py', 'config_resolve.py',
                                    'processing/__init__.py'])
def test_helper_imports_only_the_stdlib(source):
    # It runs on the bare bundled interpreter, before any environment exists, so its
    # imports and those of the Facet modules it borrows must be the stdlib alone.
    facet_own = {'config_resolve', 'processing.progress'}
    roots = {name.split('.')[0] for name in _imports(REPO / source) - facet_own}
    assert roots <= set(sys.stdlib_module_names)


# The doctor check (-c) and database.py are steered by files beside the script, so a test
# can make either fail: doctor-mode is the shell fragment the check runs, library-fails
# makes database.py exit 1.
_FAKE_VENV_PYTHON = """#!/bin/sh
here=$(dirname "$0")
if [ "$1" = "-c" ]; then
  if [ -f "$here/doctor-mode" ]; then . "$here/doctor-mode"; else
    echo '{"torch": "2.0", "mps": true, "mps_works": true}'; fi
elif [ -f "$here/library-fails" ]; then echo "database boom" >&2; exit 1; fi
exit 0
"""

# Stands in for uv: `venv` makes a venv whose python answers the GPU check; `pip sync`
# fails while the fail-sync file exists. Paths are baked in: uv gets no ambient variables.
_FAKE_UV = """#!/bin/sh
case "$1" in
  venv) echo "$@" >> '{calls}'; for last; do :; done
        mkdir -p "$last/bin" && cp '{python}' "$last/bin/python" && chmod +x "$last/bin/python" ;;
  pip) echo "$@" >> '{calls}'; [ -f '{fail_sync}' ] && exit 3 ;;
esac
exit 0
"""


@pytest.fixture
def fake_tools(mac, tmp_path, monkeypatch):
    python = tmp_path / 'venv-python'
    python.write_text(_FAKE_VENV_PYTHON)
    python.chmod(0o755)
    uv = tmp_path / 'uv'
    uv.write_text(_FAKE_UV.format(python=python, fail_sync=tmp_path / 'fail-sync', calls=tmp_path / 'uv-calls'))
    uv.chmod(0o755)
    monkeypatch.setattr(mac, 'UV', uv)
    monkeypatch.setattr(mac, '_check_free_space', lambda: None)
    return tmp_path / 'fail-sync'


def test_setup_swaps_in_a_ready_environment(mac, fake_tools, capsys):
    mac.setup()

    report = mac.ready_report()
    assert report is not None and report['mps_works'] is True and report['torch'] == '2.0'
    assert not (mac.SUPPORT / 'venv.partial').exists()
    events = _events(capsys.readouterr().out, PROGRESS_PREFIX)
    assert [e['phase'] for e in events][-3:] == ['library', 'check', 'done']
    assert events[-1]['doctor'] == report


def test_setup_leaves_an_existing_config_alone(mac, fake_tools):
    mac.CONFIG.parent.mkdir(parents=True)
    mac.CONFIG.write_text('{"viewer": {"password": "kept", "scan_directories": ["/photos"]}}')
    before = mac.CONFIG.read_text()
    mac.setup()
    assert mac.CONFIG.read_text() == before


def test_a_second_setup_is_refused_while_one_runs(mac, fake_tools, capsys):
    import fcntl
    mac.SUPPORT.mkdir(parents=True)
    with open(mac.SUPPORT / 'setup.lock', 'w') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert mac.main([str(HELPER), 'setup']) == 1
    events = _events(capsys.readouterr().out, PROGRESS_PREFIX)
    assert events[-1]['phase'] == 'error' and events[-1]['code'] == 'busy'
    assert not mac.VENV.exists()


def test_setup_does_not_rebuild_a_ready_environment(mac, fake_tools, capsys):
    mac.setup()
    marker = mac.MARKER.stat().st_mtime_ns
    fake_tools.touch()    # a rebuild would now fail
    mac.setup()
    assert mac.MARKER.stat().st_mtime_ns == marker
    assert _events(capsys.readouterr().out, PROGRESS_PREFIX)[-1]['phase'] == 'done'


def test_setup_runs_python_without_the_users_python_variables(mac, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', '/somewhere/else')
    monkeypatch.setenv('DYLD_INSERT_LIBRARIES', '/tmp/x.dylib')
    env = mac._child_env()
    assert 'PYTHONPATH' not in env and 'DYLD_INSERT_LIBRARIES' not in env
    assert env['DB_PATH'] == str(mac.DB)


def test_a_failed_rebuild_keeps_the_working_environment(mac, fake_tools, monkeypatch):
    mac.setup()
    built = mac.SETUP_VERSION
    monkeypatch.setattr(mac, 'SETUP_VERSION', built + 1)    # an update that needs a rebuild
    fake_tools.touch()

    with pytest.raises(mac.SetupError, match='exit 3') as failure:
        mac.setup()
    assert failure.value.code == 'download'
    monkeypatch.setattr(mac, 'SETUP_VERSION', built)
    assert mac.ready_report()['mps_works'] is True


def test_setup_gives_uv_the_hash_and_relocatable_flags(mac, fake_tools, tmp_path):
    mac.setup()
    calls = [line.split() for line in (tmp_path / 'uv-calls').read_text().splitlines()]
    venv_call = next(call for call in calls if call[:1] == ['venv'])
    sync_call = next(call for call in calls if call[:2] == ['pip', 'sync'])
    assert '--relocatable' in venv_call
    assert {'--require-hashes', '--require-build-hashes'} <= set(sync_call)
    assert sync_call[sync_call.index('--build-constraints') + 1] == str(mac.BUILD_CONSTRAINTS)
    assert sync_call[-1] == str(mac.LOCK)


@pytest.mark.parametrize('doctor', ['exit 1', 'true', 'echo "not json"'],
                         ids=['exits-1', 'prints-nothing', 'prints-non-json'])
def test_a_failed_gpu_check_fails_setup_without_a_marker(mac, fake_tools, tmp_path, monkeypatch, doctor):
    real_run = subprocess.run

    def run_with_doctor_mode(cmd, *args, **kwargs):
        # The fake python sits in the venv only once uv has built it.
        if len(cmd) > 1 and cmd[1] == '-c':
            (Path(cmd[0]).parent / 'doctor-mode').write_text(doctor + '\n')
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(mac.subprocess, 'run', run_with_doctor_mode)
    with pytest.raises(mac.SetupError) as failure:
        mac.setup()
    assert failure.value.code == 'check'
    assert not mac.MARKER.exists() and mac.ready_report() is None


def test_a_failed_check_logs_the_childs_stderr(mac, fake_tools, monkeypatch):
    real_run = subprocess.run

    def run_with_doctor_mode(cmd, *args, **kwargs):
        if len(cmd) > 1 and cmd[1] == '-c':
            (Path(cmd[0]).parent / 'doctor-mode').write_text('echo "torch exploded" >&2; exit 1\n')
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(mac.subprocess, 'run', run_with_doctor_mode)
    with pytest.raises(mac.SetupError):
        mac.setup()
    assert 'torch exploded' in (mac.LOGS / 'setup.log').read_text()


def test_a_failing_database_init_fails_setup_as_library(mac, fake_tools, monkeypatch):
    real_run = subprocess.run

    def run_failing(cmd, *args, **kwargs):
        if len(cmd) > 1 and cmd[1].endswith('database.py'):
            (Path(cmd[0]).parent / 'library-fails').touch()
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(mac.subprocess, 'run', run_failing)
    with pytest.raises(mac.SetupError) as failure:
        mac.setup()
    assert failure.value.code == 'library'
    assert not mac.MARKER.exists()
    assert 'database boom' in (mac.LOGS / 'setup.log').read_text()
