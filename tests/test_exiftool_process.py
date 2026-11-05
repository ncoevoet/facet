"""The persistent ExifTool session: per-command contract, protocol edges, lifetime."""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

import utils.exiftool_process as exiftool_process
from tests import exiftool_fake
from utils.exiftool_process import ARGFILE_PREFIX, close_sessions, run_exiftool_process

_PREFIX = list(ARGFILE_PREFIX)
_REAL = pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')


def _ok(stdout='', stderr='', status=0):
    return lambda args: subprocess.CompletedProcess(args, status, stdout=stdout, stderr=stderr)


def test_commands_share_one_stay_open_process_and_keep_their_own_results(monkeypatch):
    results = iter([(0, 'café\r\nline\n', ''), (1, '', 'Warning: bad tag\n')])
    def handler(args):
        status, out, err = next(results)
        return subprocess.CompletedProcess(args, status, stdout=out, stderr=err)
    started = exiftool_fake.install(monkeypatch, handler)
    first = run_exiftool_process(['exiftool', '-j', '/tmp/a.jpg'], timeout=3)
    second = run_exiftool_process(['exiftool', '-j', '/tmp/b.jpg'], timeout=3)
    assert len(started) == 1 and started[0].launch == ['exiftool']
    assert (first.returncode, first.stdout, first.stderr) == (0, 'café\nline\n', '')
    assert (second.returncode, second.stdout, second.stderr) == (1, '', 'Warning: bad tag\n')
    assert first.args == ['exiftool', '-j', '/tmp/a.jpg']
    assert started[0].commands == [['exiftool', '-j', '/tmp/a.jpg'], ['exiftool', '-j', '/tmp/b.jpg']]


@pytest.mark.parametrize('operator', ['=', '+=', '-='])
def test_utf8_argfile_preserves_values_operators_and_keeps_config_first(monkeypatch, operator):
    seen = []
    value = '# 日本\r\n-overwrite_original\nline \\n $ @'
    def handler(args):
        prefix = '-XMP-dc:Description' + operator[:-1] + '<='
        assert args[3].startswith(prefix)
        filename = Path(args[3][len(prefix):])
        assert filename.read_bytes() == value.encode('utf-8')
        if os.name != 'nt':
            assert stat.S_IMODE(filename.stat().st_mode) == 0o600
            assert stat.S_IMODE(filename.parent.stat().st_mode) == 0o700
        seen.append(filename)
        return subprocess.CompletedProcess(args, 0, stdout='')
    started = exiftool_fake.install(monkeypatch, handler)
    run_exiftool_process(['exiftool', '-config', 'facet.config', '-XMP-dc:Description' + operator + value,
                          'Renée.jpg'], timeout=3)
    # ExifTool requires -config first, so it is a launch option, never a command line.
    assert started[0].launch == ['exiftool', '-config', 'facet.config']
    assert started[0].lines[0][:4] == _PREFIX
    assert started[0].lines[0][5:] == ['Renée.jpg']
    assert not seen[0].exists()


def test_plain_unicode_values_preserve_leading_space_hash_and_backslashes(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok())
    run_exiftool_process(['exiftool', '-XMP-dc:Description= # 日本 \\n $ @  ', '/tmp/# 日本.jpg'], timeout=1)
    assert started[0].lines == [[*_PREFIX, '-XMP-dc:Description=  # 日本 \\n $ @  ', '/tmp/# 日本.jpg']]
    assert started[0].commands[0][1] == '-XMP-dc:Description= # 日本 \\n $ @  '


def test_newline_filename_is_a_catchable_runtime_failure_before_process_start(monkeypatch):
    started = exiftool_fake.install(monkeypatch, lambda args: pytest.fail('must refuse before process start'))
    with pytest.raises(RuntimeError, match='filename or option contains a newline'):
        run_exiftool_process(['exiftool', '-XMP-dc:Subject=café', '/tmp/a\nb.jpg'], timeout=1)
    assert started == []


def test_newline_file_include_assignment_is_refused_before_process_start(monkeypatch):
    started = exiftool_fake.install(monkeypatch, lambda args: pytest.fail('must refuse before process start'))
    with pytest.raises(RuntimeError, match='filename or option contains a newline'):
        run_exiftool_process(['exiftool', '-XMP-dc:Subject=café', '-Tag<=a\nb', '/tmp/a.jpg'], timeout=1)
    assert started == []


@pytest.mark.parametrize('argument', ['-execute', '-execute7', '-EXECUTE', '-stay_open', '-@',
                                      '', '#photo.jpg', ' photo.jpg', '\tphoto.jpg'])
def test_arguments_an_argument_file_would_alter_are_refused_before_process_start(monkeypatch, argument):
    # An argfile drops '#' lines and empty lines and strips leading whitespace;
    # a framing option would end the command early or end the session.
    started = exiftool_fake.install(monkeypatch, lambda args: pytest.fail('must refuse before process start'))
    with pytest.raises(RuntimeError):
        run_exiftool_process(['exiftool', '-j', argument], timeout=1)
    assert started == []


def test_each_executable_config_and_working_directory_gets_its_own_process(monkeypatch, tmp_path):
    started = exiftool_fake.install(monkeypatch, _ok())
    for args in (['exiftool', 'a.jpg'], ['exiftool', '-config', 'x.config', 'a.jpg'],
                 ['/other/exiftool', 'a.jpg'], ['exiftool', 'b.jpg']):
        run_exiftool_process(args, timeout=1)
    assert [process.launch for process in started] == [
        ['exiftool'], ['exiftool', '-config', 'x.config'], ['/other/exiftool']]
    # A relative path must resolve against the caller's directory, not the first one.
    monkeypatch.chdir(tmp_path)
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    assert len(started) == 4


def test_a_timed_out_command_kills_the_process_and_the_next_command_restarts_it(monkeypatch):
    calls = []
    def handler(args):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, 0)
        return subprocess.CompletedProcess(args, 0, stdout='ok\n')
    started = exiftool_fake.install(monkeypatch, handler)
    with pytest.raises(subprocess.TimeoutExpired):
        run_exiftool_process(['exiftool', 'slow.jpg'], timeout=0.2)
    assert started[0].returncode == -9
    assert run_exiftool_process(['exiftool', 'fast.jpg'], timeout=3).stdout == 'ok\n'
    assert len(started) == 2


def test_waiting_for_a_busy_session_counts_against_the_timeout(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok())
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    session = next(iter(exiftool_process._sessions.values()))
    with session._lock:  # another thread's command holds the process
        begun = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            run_exiftool_process(['exiftool', 'b.jpg'], timeout=0.1)
        assert time.monotonic() - begun < 1
    assert len(started[0].commands) == 1


def test_a_process_dying_mid_command_reports_its_status_and_stderr_and_is_restarted(monkeypatch):
    calls = []
    def handler(args):
        calls.append(args)
        if len(calls) == 1:
            raise exiftool_fake.Exit(2, 'Out of memory!\n')
        return subprocess.CompletedProcess(args, 0, stdout='ok\n')
    started = exiftool_fake.install(monkeypatch, handler)
    crashed = run_exiftool_process(['exiftool', 'a.jpg'], timeout=3)
    assert (crashed.returncode, crashed.stderr) == (2, 'Out of memory!\n')
    assert run_exiftool_process(['exiftool', 'a.jpg'], timeout=3).stdout == 'ok\n'
    assert len(started) == 2


def test_a_process_exiting_zero_mid_command_raises_oserror(monkeypatch):
    # Status 0 with no answer would read as success: refuse it.
    exiftool_fake.install(monkeypatch, lambda args: (_ for _ in ()).throw(exiftool_fake.Exit(0)))
    with pytest.raises(OSError, match='exited during a command'):
        run_exiftool_process(['exiftool', 'a.jpg'], timeout=3)


def test_a_command_without_a_status_line_raises_and_restarts_the_process(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok(stdout='partial\n'), report_status=False)
    with pytest.raises(OSError, match='did not report a command status'):
        run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    assert started[0].killed
    with pytest.raises(OSError):
        run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    assert len(started) == 2


def test_output_without_a_trailing_newline_is_kept_whole(monkeypatch):
    # -b prints a raw value: the status and stderr markers land on the same line.
    exiftool_fake.install(monkeypatch, _ok(stdout='raw value', stderr='Warning: x'))
    result = run_exiftool_process(['exiftool', '-b', 'a.jpg'], timeout=1)
    assert (result.returncode, result.stdout, result.stderr) == (0, 'raw value', 'Warning: x')


def test_marker_lookalikes_in_output_do_not_end_the_command(monkeypatch):
    fake = '{ready0}\n{ready}\n{facet-status 00 0}\n{facet-done 00}\ntail\n'
    exiftool_fake.install(monkeypatch, _ok(stdout=fake, stderr=fake, status=1))
    result = run_exiftool_process(['exiftool', '-X', 'a.jpg'], timeout=1)
    assert (result.returncode, result.stdout, result.stderr) == (1, fake, fake)


def test_concurrent_commands_never_mix_their_results(tmp_path, monkeypatch):
    exe = exiftool_fake.script(tmp_path, """
        def handle(args):
            return int(args[-1]) % 3, args[-1] + '\\n', 'err ' + args[-1] + '\\n'
        """)
    results = {}
    def worker(start):
        for number in range(start, start + 5):
            results[number] = run_exiftool_process([exe, str(number)], timeout=30)
    threads = [threading.Thread(target=worker, args=(index * 5,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(results) == list(range(40))
    for number, result in results.items():
        assert (result.returncode, result.stdout, result.stderr) == (number % 3, f'{number}\n', f'err {number}\n')
    assert len(exiftool_fake.logged(exe)) == 40


def test_a_process_that_died_while_idle_is_restarted_before_the_next_command(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok(stdout='ok\n'))
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    started[0].kill()  # e.g. killed by the OS between two photos
    assert run_exiftool_process(['exiftool', 'b.jpg'], timeout=1).stdout == 'ok\n'
    assert len(started) == 2


def test_an_idle_session_is_stopped_and_restarted_on_next_use(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok(stdout='ok\n'))
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    exiftool_process._reap_idle(time.monotonic())
    assert started[0].returncode is None  # used just now
    exiftool_process._reap_idle(time.monotonic() + exiftool_process.IDLE_SECONDS)
    assert started[0].returncode == 0 and not started[0].killed
    assert run_exiftool_process(['exiftool', 'b.jpg'], timeout=1).stdout == 'ok\n'
    assert len(started) == 2


def test_close_sessions_stops_every_process_cleanly(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok())
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    run_exiftool_process(['/other/exiftool', 'a.jpg'], timeout=1)
    close_sessions()
    assert [process.returncode for process in started] == [0, 0]
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    assert len(started) == 3


def test_close_kills_a_process_that_ignores_the_stop_request(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok(), ignore_stop=True)
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    close_sessions()
    assert started[0].killed and started[0].returncode == -9


def test_no_session_starts_once_the_interpreter_is_exiting(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok())
    monkeypatch.setattr(exiftool_process, '_shutting_down', True)
    with pytest.raises(OSError, match='interpreter is exiting'):
        run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    assert started == []


def test_a_missing_executable_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        run_exiftool_process([str(tmp_path / 'no-exiftool'), '-ver'], timeout=5)


@pytest.mark.skipif(os.name == 'nt' or shutil.which('exiftool') is None,
                    reason='requires ExifTool and a filesystem allowing newline filenames')
def test_one_newline_filename_does_not_abort_other_photo_exports(tmp_path):
    import sqlite3
    from db.schema import init_database
    from processing import xmp_export as xe
    db = tmp_path / 'test.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for name in ('safe.jpg', 'a\nb.jpg', 'also-safe.jpg'):
            image = tmp_path / name
            Image.new('RGB', (16, 16), 'blue').save(image)
            conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'café'))
        conn.commit()
        result = xe.export_sidecars(conn)
    assert result['written'] == 2 and result['errors'] == 1
    assert (tmp_path / 'safe.jpg.xmp').exists()
    assert (tmp_path / 'also-safe.jpg.xmp').exists()


@_REAL
@pytest.mark.parametrize('embedded', [False, True])
@pytest.mark.parametrize('caption', ['# Renée 日本\r\n-overwrite_original\nsecond line \\n literal \\path "quote" $ @  ',
                                    '  # Renée 日本 \\n literal \\path "quote" $ @  '])
def test_real_writer_round_trips_unicode_values_through_utf8_stdin(tmp_path, embedded, caption):
    from processing import xmp_export as xe
    image = tmp_path / '日本 Renée.jpg'
    Image.new('RGB', (100, 80), 'blue').save(image)
    before = image.read_bytes()
    name = 'Renée, {日}|[name]'
    rating = xe.XmpRating(tags=['café', 'Straße'], caption=caption,
                         regions=[xe.FaceRegion.from_bbox(name, 30, 20, 60, 50, 100, 80)])
    xe.write_metadata(str(image), rating, embed_original=embedded)
    targets = [Path(str(image) + '.xmp')] + ([image] if embedded else [])
    for target in targets:
        result = run_exiftool_process([xe._resolve_exiftool(), '-json', '-struct', '-XMP-dc:Subject',
                                      '-XMP-dc:Description', '-XMP-mwg-rs:RegionInfo', str(target)], timeout=30)
        assert result.returncode == 0, result.stderr
        record = json.loads(result.stdout)[0]
        assert record['Subject'] == ['café', 'Straße']
        assert record['Description'] == caption
        assert record['RegionInfo']['RegionList'][0]['Name'] == name
        # Literal spaces in foreign keywords also survive the ordinary argfile
        # parser; Facet's separate typed-tag normalization is not involved here.
        result = run_exiftool_process([xe._resolve_exiftool(), '-overwrite_original',
                                      '-XMP-dc:Subject= # café  ', str(target)], timeout=30)
        assert result.returncode == 0, result.stderr
        result = run_exiftool_process([xe._resolve_exiftool(), '-json', '-XMP-dc:Subject', str(target)], timeout=30)
        assert json.loads(result.stdout)[0]['Subject'] == ' # café  '
    if not embedded:
        assert image.read_bytes() == before


@_REAL
def test_real_marker_lookalike_value_and_raw_output_without_newline(tmp_path):
    image = tmp_path / '# photo.jpg'  # absolute, so a leading '#' in the name is fine
    Image.new('RGB', (16, 16)).save(image)
    value = '{ready0}\n{facet-status 0 0}\n{facet-done 0}'
    written = run_exiftool_process(['exiftool', '-overwrite_original', f'-XMP-dc:Description={value}',
                                    str(image)], timeout=30)
    assert written.returncode == 0, written.stderr
    for _ in range(2):  # the session must still be in step after reading the value
        read = run_exiftool_process(['exiftool', '-b', '-XMP-dc:Description', str(image)], timeout=30)
        assert (read.returncode, read.stdout) == (0, value)
    missing = run_exiftool_process(['exiftool', '-j', str(tmp_path / 'absent.jpg')], timeout=30)
    assert missing.returncode == 1 and 'not found' in missing.stderr


@_REAL
def test_real_relative_paths_follow_the_callers_working_directory(tmp_path, monkeypatch):
    for width in (16, 32):
        (tmp_path / str(width)).mkdir()
        Image.new('RGB', (width, 8)).save(tmp_path / str(width) / 'a.jpg')
    for width in (16, 32, 16):
        monkeypatch.chdir(tmp_path / str(width))
        result = run_exiftool_process(['exiftool', '-s3', '-ImageWidth', 'a.jpg'], timeout=30)
        assert (result.returncode, result.stdout) == (0, f'{width}\n')


@pytest.mark.skipif(not exiftool_process._PDEATHSIG or shutil.which('exiftool') is None,
                    reason='requires Linux setpriv and ExifTool')
def test_a_killed_python_takes_its_exiftool_process_with_it(tmp_path):
    child = tmp_path / 'child.py'
    child.write_text(textwrap.dedent(f"""
        import sys, threading
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
        import utils.exiftool_process as ep
        # Launched from a short-lived thread, as a viewer pool thread would.
        worker = threading.Thread(target=ep.run_exiftool_process, args=(['exiftool', '-ver'],),
                                  kwargs={{'timeout': 30}})
        worker.start(); worker.join()
        process = next(iter(ep._sessions.values()))._process
        assert process.poll() is None, 'died with its launching thread'
        assert ep.run_exiftool_process(['exiftool', '-ver'], timeout=30).returncode == 0
        assert next(iter(ep._sessions.values()))._process is process
        print(process.pid, flush=True)
        threading.Event().wait()
        """), encoding='utf-8')
    parent = subprocess.Popen([sys.executable, str(child)], stdout=subprocess.PIPE, text=True)
    try:
        line = parent.stdout.readline()
        assert line.strip().isdigit(), f'child failed: {line!r}'
        pid = int(line)
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == 'Z':
                break
            time.sleep(0.05)
        else:
            os.kill(pid, signal.SIGKILL)
            pytest.fail('exiftool outlived its killed parent')
    finally:
        if parent.poll() is None:
            parent.kill()
