"""Exercise the real Unicode transport under simulated Windows ANSI boundaries."""
import json
import shutil
import subprocess
import os
import stat
from pathlib import Path

import pytest
from PIL import Image

from tests import exiftool_fake
from utils.exiftool_process import close_sessions, run_exiftool_process


_CHARSET = ['-charset', 'filename=UTF8', '-charset', 'UTF8']


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
    assert started[0].lines[0][:4] == _CHARSET
    assert started[0].lines[0][5:] == ['Renée.jpg']
    assert not seen[0].exists()


def test_plain_unicode_values_preserve_leading_space_hash_and_backslashes(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok())
    run_exiftool_process(['exiftool', '-XMP-dc:Description= # 日本 \\n $ @  ', '/tmp/# 日本.jpg'], timeout=1)
    assert started[0].lines == [[*_CHARSET, '-XMP-dc:Description=  # 日本 \\n $ @  ', '/tmp/# 日本.jpg']]
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


def test_each_executable_and_config_gets_its_own_process(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok())
    for args in (['exiftool', 'a.jpg'], ['exiftool', '-config', 'x.config', 'a.jpg'],
                 ['/other/exiftool', 'a.jpg'], ['exiftool', 'b.jpg']):
        run_exiftool_process(args, timeout=1)
    assert [process.launch for process in started] == [
        ['exiftool'], ['exiftool', '-config', 'x.config'], ['/other/exiftool']]


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


def test_a_process_dying_mid_command_raises_oserror_and_is_restarted(monkeypatch):
    calls = []
    def handler(args):
        calls.append(args)
        if len(calls) == 1:
            raise OSError('crash')
        return subprocess.CompletedProcess(args, 0, stdout='ok\n')
    started = exiftool_fake.install(monkeypatch, handler)
    with pytest.raises(OSError):
        run_exiftool_process(['exiftool', 'a.jpg'], timeout=3)
    assert run_exiftool_process(['exiftool', 'a.jpg'], timeout=3).stdout == 'ok\n'
    assert len(started) == 2


def test_a_process_that_died_while_idle_is_restarted_before_the_next_command(monkeypatch):
    started = exiftool_fake.install(monkeypatch, _ok(stdout='ok\n'))
    run_exiftool_process(['exiftool', 'a.jpg'], timeout=1)
    started[0].kill()  # e.g. killed by the OS between two photos
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


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')
@pytest.mark.parametrize('embedded', [False, True])
@pytest.mark.parametrize('caption', ['# Renée 日本\r\n-overwrite_original\nsecond line \\n literal \\path "quote" $ @  ',
                                    '  # Renée 日本 \\n literal \\path "quote" $ @  '])
def test_real_writer_preserves_unicode_under_windows_ansi_transport(tmp_path, monkeypatch, embedded, caption):
    from processing import xmp_export as xe
    original_popen = subprocess.Popen
    def windows_ansi_popen(args, **kwargs):
        # Reproduce Windows narrow argv loss on the only argv left: the session launch.
        # Commands travel as UTF-8 bytes on stdin, so no ANSI code page can touch them.
        args = [value.encode('cp1252', errors='replace').decode('cp1252') for value in args]
        return original_popen(args, **kwargs)
    close_sessions()
    monkeypatch.setattr(subprocess, 'Popen', windows_ansi_popen)
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
