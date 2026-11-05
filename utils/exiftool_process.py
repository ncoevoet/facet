"""Run ExifTool commands through one persistent ``-stay_open`` process per executable.

Every ExifTool launch starts a fresh Perl interpreter, which costs tens of
milliseconds before any work happens; an export of thousands of photos paid
that on every read and every write. Commands now go to a long-lived process,
one per (executable, ``-config``) pair, and keep their per-command contract:
exit status, stdout, stderr and timeout.
"""
import atexit
import os
import queue
import re
import subprocess
import tempfile
import threading

_READY = re.compile(rb'^\{ready(\d+)\}\r?\n?$')
_STATUS = re.compile(rb'^\{facet-status (\d+) (-?\d+)\}\r?\n?$')
_ERR_DONE = re.compile(rb'^\{facet-err-done (\d+)\}\r?\n?$')


def _argfile_lines(arguments, directory):
    """Arguments in ExifTool's -@ argument-file format, one per line.

    Metadata values with newlines go to private UTF-8 value files: ExifTool's
    CSTR escape parser changes literal $/@ characters. Ordinary argfiles strip
    ONE space after an assignment, so that space is supplied explicitly.
    """
    lines = []
    for index, argument in enumerate(arguments):
        assignment = re.fullmatch(r'(-[-:\w]+?#?)([-+<]?=)(.*)', argument, re.DOTALL)
        if '\n' in argument or '\r' in argument:
            if not assignment or assignment[2] == '<=':
                raise RuntimeError('ExifTool filename or option contains a newline')
            filename = os.path.join(directory, str(index))
            descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(assignment[3].encode('utf-8'))
            argument = assignment[1] + assignment[2][:-1] + '<=' + filename
        elif assignment:
            argument = assignment[1] + assignment[2] + ' ' + assignment[3]
        lines.append(argument)
    return lines


def _text(lines):
    """Decode like ``subprocess.run(text=True, encoding='utf-8')``: universal newlines."""
    return b''.join(lines).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')


def _pump(stream, sink):
    for line in iter(stream.readline, b''):
        sink.put(line)
    sink.put(None)


class _Session:
    """One ``exiftool -stay_open`` process, used by one command at a time."""

    def __init__(self, launch):
        self._launch = launch
        self._lock = threading.Lock()
        self._process = None
        self._sequence = 0

    def _start(self):
        process = subprocess.Popen(self._launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        self._out, self._err = queue.Queue(), queue.Queue()
        for stream, sink in ((process.stdout, self._out), (process.stderr, self._err)):
            threading.Thread(target=_pump, args=(stream, sink), daemon=True).start()
        self._process = process

    def _kill(self):
        if self._process is not None:
            try:
                self._process.kill()
                self._process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._process = None

    def close(self):
        with self._lock:
            if self._process is not None:
                try:
                    self._process.stdin.write(b'-stay_open\nFalse\n')
                    self._process.stdin.flush()
                    self._process.wait(timeout=5)
                    self._process = None
                except (OSError, subprocess.TimeoutExpired):
                    self._kill()

    @staticmethod
    def _collect(sink, done, deadline_left):
        lines = []
        while True:
            line = sink.get(timeout=deadline_left())
            if line is None:
                raise OSError('exiftool exited during a command')
            match = done(line)
            if match:
                return lines, match
            lines.append(line)

    def run(self, command, lines, timeout):
        import time
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            self._sequence += 1
            n = self._sequence
            script = ''.join(value + '\n' for value in lines)
            script += (f'-echo3\n{{facet-status {n} ${{status}}}}\n'
                       f'-echo4\n{{facet-err-done {n}}}\n-execute{n}\n')
            end = time.monotonic() + timeout

            def left():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                return remaining
            try:
                self._process.stdin.write(script.encode('utf-8'))
                self._process.stdin.flush()
                out, _ = self._collect(self._out, lambda line: _READY.match(line), left)
                err, _ = self._collect(self._err, lambda line: _ERR_DONE.match(line), left)
            except queue.Empty:
                self._kill()
                raise subprocess.TimeoutExpired(command, timeout) from None
            except (OSError, ValueError):
                self._kill()
                raise
            status = None
            if out:
                match = _STATUS.match(out[-1])
                if match and int(match[1]) == n:
                    status = int(match[2])
                    out = out[:-1]
            if status is None:
                self._kill()
                raise OSError('exiftool did not report a command status')
            return subprocess.CompletedProcess(command, status, _text(out), _text(err))


_sessions: dict = {}
_sessions_lock = threading.Lock()


def _session(executable, config):
    key = (executable, *config)
    with _sessions_lock:
        session = _sessions.get(key)
        if session is None:
            # ExifTool requires -config to be the first actual command-line option.
            session = _sessions[key] = _Session([executable, *config, '-stay_open', 'True', '-@', '-'])
        return session


def close_sessions():
    """Stop every persistent ExifTool process (also run at interpreter exit)."""
    with _sessions_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.close()


atexit.register(close_sessions)


def run_exiftool_process(args, *, timeout):
    """Run one ExifTool command; returns a ``CompletedProcess`` (text stdout/stderr).

    Arguments travel as UTF-8 through the -@ argument file, so Unicode values and
    filenames survive Windows' ANSI command line. Raises ``subprocess.TimeoutExpired``
    after ``timeout`` seconds (the process is killed and restarted on next use),
    ``OSError`` when ExifTool cannot start or dies, and ``RuntimeError`` before
    anything runs for a filename or option containing a newline.
    """
    command = list(args)
    executable, *arguments = command
    config = arguments[:2] if arguments[:1] == ['-config'] else []
    arguments = arguments[len(config):]
    with tempfile.TemporaryDirectory(prefix='facet-exiftool-') as directory:
        lines = ['-charset', 'filename=UTF8', '-charset', 'UTF8', *_argfile_lines(arguments, directory)]
        return _session(executable, config).run(command, lines, timeout)
