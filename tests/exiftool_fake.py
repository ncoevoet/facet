"""Stand-ins for ExifTool that speak its ``-stay_open True -@ -`` protocol.

``utils.exiftool_process`` keeps one ExifTool process open and feeds it commands
through stdin, so a test can no longer fake ExifTool by replacing
``subprocess.run``: that hook never sees those commands. Both fakes here answer
the real protocol through ``tests/exiftool_protocol.py``, so the session code under
test (status echo, stderr marker, ``{readyN}``, timeout, a dying process) runs
unchanged.

* ``install(monkeypatch, handler)`` -- an in-process fake process. ``handler(args)``
  receives one command's arguments as ExifTool parses them (``[exe, *config,
  *arguments]``) and returns an object with ``returncode`` and ``stdout`` (and
  optionally ``stderr``). Raising ``Exit(status, stderr)`` makes the process write
  ``stderr`` and exit mid-command (``OSError`` is ``Exit(1)``); raising
  ``subprocess.TimeoutExpired`` makes it hang until the caller's timeout. Each
  process records ``commands`` (parsed) and ``lines`` (the raw argument-file lines
  of each command).
* ``script(tmp_path, handle_source)`` -- a real executable, for tests that need an
  actual process. ``handle_source`` defines ``handle(args) -> (status, stdout,
  stderr)``; it returns the launcher path, and ``logged(launcher)`` lists every
  command the process received.
"""
import json
import queue
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import utils.exiftool_process as exiftool_process
from tests.exiftool_protocol import Exit, Protocol

__all__ = ['Exit', 'FakeStayOpenProcess', 'install', 'logged', 'script']


class _Pipe:
    def __init__(self):
        self._lines = queue.Queue()

    def put(self, data):
        for line in data.splitlines(keepends=True):
            self._lines.put(line)

    def close(self):
        self._lines.put(b'')

    def readline(self):
        line = self._lines.get()
        if line == b'':
            self._lines.put(b'')
        return line


class _Stdin:
    def __init__(self, process):
        self._process = process
        self._buffer = b''

    def write(self, data):
        if self._process.returncode is not None:
            raise BrokenPipeError('fake exiftool has exited')
        self._buffer += data
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            self._process.line(line.decode('utf-8'))

    def flush(self):
        pass


class FakeStayOpenProcess:
    """In-process ``exiftool -stay_open True -@ -`` driven by a handler."""

    pid = None

    def __init__(self, launch, handler, *, report_status=True, ignore_stop=False):
        assert launch[-4:] == ['-stay_open', 'True', '-@', '-'], launch
        self.launch = launch[:-4]
        self.handler = handler
        self.ignore_stop = ignore_stop
        self.stdin, self.stdout, self.stderr = _Stdin(self), _Pipe(), _Pipe()
        self.returncode = None
        self.commands = []
        self.lines = []
        self.killed = False
        self._protocol = Protocol(self._answer, exiftool_process.ARGFILE_PREFIX, report_status)

    def _answer(self, lines, args):
        args = [*self.launch, *args]
        self.lines.append(lines)
        self.commands.append(args)
        result = self.handler(args)
        return result.returncode, result.stdout or '', getattr(result, 'stderr', '') or ''

    def line(self, line):
        result = self._protocol.feed(line)
        if result == 'stop' and not self.ignore_stop:
            self._exit(0)
        elif isinstance(result, Exit):
            self.stderr.put(result.stderr.encode('utf-8'))
            self._exit(result.status)
        elif isinstance(result, tuple):
            self.stdout.put(result[0])
            self.stderr.put(result[1])

    def _exit(self, code):
        if self.returncode is None:
            self.returncode = code
            self.stdout.close()
            self.stderr.close()

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self._exit(-9)

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired('fake exiftool', timeout)
        return self.returncode


def install(monkeypatch, handler, **options):
    """Route every ExifTool command to ``handler`` through a fake stay-open process.

    ``options`` go to ``FakeStayOpenProcess`` (``report_status``, ``ignore_stop``).
    Returns the list of processes started, so a test can count launches and read
    each one's ``commands``.
    """
    started = []

    def popen(launch, **kwargs):
        process = FakeStayOpenProcess(list(launch), handler, **options)
        started.append(process)
        return process

    fake = types.SimpleNamespace(**{name: getattr(subprocess, name) for name in
                                    ('PIPE', 'TimeoutExpired', 'CompletedProcess', 'run')}, Popen=popen)
    exiftool_process.close_sessions()
    monkeypatch.setattr(exiftool_process, 'subprocess', fake)
    monkeypatch.setattr(exiftool_process, '_sessions', {})
    monkeypatch.setattr(exiftool_process, '_PDEATHSIG', [])
    return started


_SCRIPT = '''\
import json, sys
sys.path.insert(0, {tests!r})
from exiftool_protocol import Exit, Protocol

LOG = {log!r}

{handle}

def answer(lines, args):
    with open(LOG, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(args) + '\\n')
    return handle(args)

argv = sys.argv[1:]
if argv[-4:] != ['-stay_open', 'True', '-@', '-']:
    status, out, err = answer(argv, argv)
    sys.stdout.write(out); sys.stderr.write(err)
    sys.exit(status)
config = argv[:-4]
protocol = Protocol(lambda lines, args: answer(lines, config + args), {prefix!r})
for raw in sys.stdin.buffer:
    result = protocol.feed(raw.decode('utf-8').rstrip('\\r\\n'))
    if result == 'stop':
        sys.exit(0)
    if isinstance(result, Exit):
        sys.stderr.write(result.stderr); sys.stderr.flush()
        sys.exit(result.status)
    if isinstance(result, tuple):
        sys.stdout.buffer.write(result[0]); sys.stdout.flush()
        sys.stderr.buffer.write(result[1]); sys.stderr.flush()
'''


def _log(launcher):
    return Path(launcher).with_suffix('.log')


def script(tmp_path, handle_source, name='fake_exiftool'):
    """Write an executable fake ExifTool; returns its launcher path."""
    body = tmp_path / f'{name}.py'
    log = tmp_path / f'{name}.log'
    body.write_text(_SCRIPT.format(tests=str(Path(__file__).resolve().parent), log=str(log),
                                   prefix=exiftool_process.ARGFILE_PREFIX,
                                   handle=textwrap.dedent(handle_source)),
                    encoding='utf-8')
    if sys.platform == 'win32':
        launcher = tmp_path / f'{name}.cmd'
        launcher.write_text(f'@"{sys.executable}" "{body}" %*\r\n')
    else:
        launcher = tmp_path / name
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n')
        launcher.chmod(0o755)
    assert _log(launcher) == log
    return str(launcher)


def logged(launcher):
    """Every command the script fake at ``launcher`` received, in order."""
    log = _log(launcher)
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
