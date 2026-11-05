"""Stand-ins for ExifTool that speak its ``-stay_open True -@ -`` protocol.

``utils.exiftool_process`` keeps one ExifTool process open and feeds it commands
through stdin, so a test can no longer fake ExifTool by replacing
``subprocess.run``: that hook never sees those commands. Both fakes here answer
the real protocol instead, so the session code under test (status echo, stderr
marker, ``{readyN}``, timeout, a dying process) runs unchanged.

* ``install(monkeypatch, handler)`` -- an in-process fake process. ``handler(args)``
  receives one command's arguments as ExifTool parses them (``[exe, *config,
  *arguments]``) and returns an object with ``returncode`` and ``stdout`` (and
  optionally ``stderr``). Raising ``OSError`` makes the process die mid-command;
  raising ``subprocess.TimeoutExpired`` makes it hang until the caller's timeout.
  Each process records ``commands`` (parsed) and ``lines`` (the raw argument-file
  lines of each command).
* ``script(tmp_path, handle_source)`` -- a real executable, for tests that need an
  actual process. ``handle_source`` defines ``handle(args) -> (status, stdout,
  stderr)``; every command it receives is appended to ``<script>.log`` as JSON.
"""
import json
import queue
import re
import subprocess
import sys
import textwrap
import types

import utils.exiftool_process as exiftool_process

_ASSIGNMENT = re.compile(r'(-[-:\w]+?#?)([-+<]?=) (.*)', re.DOTALL)
_CHARSET = ['-charset', 'filename=UTF8', '-charset', 'UTF8']


def _parsed(lines):
    """One command's argument-file lines as ExifTool reads them."""
    if lines[:4] == _CHARSET:
        lines = lines[4:]
    parsed = []
    for line in lines:
        match = _ASSIGNMENT.fullmatch(line)
        # An argument file strips ONE space after an assignment.
        parsed.append(match[1] + match[2] + match[3] if match and match[2] != '<=' else line)
    return parsed


def _split_command(lines):
    """``(arguments, echo3 text, echo4 text)`` of one command block."""
    arguments, echo3, echo4 = [], [], []
    iterator = iter(lines)
    for line in iterator:
        if line == '-echo3':
            echo3.append(next(iterator))
        elif line == '-echo4':
            echo4.append(next(iterator))
        else:
            arguments.append(line)
    return arguments, echo3, echo4


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

    def __init__(self, launch, handler):
        assert launch[-4:] == ['-stay_open', 'True', '-@', '-'], launch
        self.launch = launch[:-4]
        self.handler = handler
        self.stdin, self.stdout, self.stderr = _Stdin(self), _Pipe(), _Pipe()
        self.returncode = None
        self.commands = []
        self.lines = []
        self._block = []
        self._stopping = False

    def line(self, line):
        if self._stopping:
            if line == 'False':
                self._exit(0)
            self._stopping = False
            return
        if line == '-stay_open':
            self._stopping = True
            return
        match = re.fullmatch(r'-execute(\d*)', line)
        if not match:
            self._block.append(line)
            return
        block, self._block = self._block, []
        arguments, echo3, echo4 = _split_command(block)
        args = [*self.launch, *_parsed(arguments)]
        self.lines.append(arguments)
        self.commands.append(args)
        try:
            result = self.handler(args)
        except subprocess.TimeoutExpired:
            return  # hangs: the caller's deadline has to fire
        except OSError:
            self._exit(1)
            return
        status = result.returncode
        self.stdout.put((result.stdout or '').encode('utf-8'))
        for text in echo3:
            self.stdout.put((text.replace('${status}', str(status)) + '\n').encode('utf-8'))
        self.stdout.put(f'{{ready{match[1]}}}\n'.encode('utf-8'))
        self.stderr.put((getattr(result, 'stderr', '') or '').encode('utf-8'))
        for text in echo4:
            self.stderr.put((text.replace('${status}', str(status)) + '\n').encode('utf-8'))

    def _exit(self, code):
        if self.returncode is None:
            self.returncode = code
            self.stdout.close()
            self.stderr.close()

    def poll(self):
        return self.returncode

    def kill(self):
        self._exit(-9)

    def wait(self, timeout=None):
        return self.returncode


def install(monkeypatch, handler):
    """Route every ExifTool command to ``handler`` through a fake stay-open process.

    Returns the list of processes started, so a test can count launches and read
    each one's ``commands``.
    """
    started = []

    def popen(launch, **kwargs):
        process = FakeStayOpenProcess(list(launch), handler)
        started.append(process)
        return process

    fake = types.SimpleNamespace(**{name: getattr(subprocess, name) for name in
                                    ('PIPE', 'TimeoutExpired', 'CompletedProcess')}, Popen=popen)
    exiftool_process.close_sessions()
    monkeypatch.setattr(exiftool_process, 'subprocess', fake)
    monkeypatch.setattr(exiftool_process, '_sessions', {})
    return started


_SCRIPT = '''\
import json, re, sys
LOG = {log!r}

{handle}

def log(args):
    with open(LOG, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(args) + '\\n')

def answer(args):
    log(args)
    return handle(args)

argv = sys.argv[1:]
if argv[-4:] != ['-stay_open', 'True', '-@', '-']:
    status, out, err = answer(argv)
    sys.stdout.write(out); sys.stderr.write(err)
    sys.exit(status)
config = argv[:-4]
block = []
lines = iter(sys.stdin.buffer)
for raw in lines:
    line = raw.decode('utf-8').rstrip('\\r\\n')
    if line == '-stay_open':
        if next(lines).decode('utf-8').strip() == 'False':
            sys.exit(0)
        continue
    match = re.fullmatch(r'-execute(\\d*)', line)
    if not match:
        block.append(line)
        continue
    arguments, echo3, echo4 = SPLIT(block)
    block = []
    status, out, err = answer(config + PARSED(arguments))
    sys.stdout.write(out)
    for text in echo3:
        sys.stdout.write(text.replace('${{status}}', str(status)) + '\\n')
    sys.stdout.write('{{ready' + match[1] + '}}\\n'); sys.stdout.flush()
    sys.stderr.write(err)
    for text in echo4:
        sys.stderr.write(text.replace('${{status}}', str(status)) + '\\n')
    sys.stderr.flush()
'''


def script(tmp_path, handle_source, name='fake_exiftool'):
    """Write an executable fake ExifTool; returns ``(launcher path, log path)``."""
    import inspect
    body = tmp_path / f'{name}.py'
    log = tmp_path / f'{name}.log'
    helpers = '\n'.join(inspect.getsource(fn) for fn in (_parsed, _split_command))
    source = ('_ASSIGNMENT = re.compile(r\'(-[-:\\w]+?#?)([-+<]?=) (.*)\', re.DOTALL)\n'
              f'_CHARSET = {_CHARSET!r}\n' + helpers + '\nPARSED, SPLIT = _parsed, _split_command\n')
    body.write_text(_SCRIPT.format(log=str(log), handle=textwrap.dedent(handle_source) + '\n' + source),
                    encoding='utf-8')
    if sys.platform == 'win32':
        launcher = tmp_path / f'{name}.cmd'
        launcher.write_text(f'@"{sys.executable}" "{body}" %*\r\n')
    else:
        launcher = tmp_path / name
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n')
        launcher.chmod(0o755)
    return str(launcher), log


def logged(log):
    """Every command the script fake received, in order."""
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
