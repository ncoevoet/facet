"""Run ExifTool commands through one persistent ``-stay_open`` process per executable.

Every ExifTool launch starts a fresh Perl interpreter, which costs tens of
milliseconds before any work happens; an export of thousands of photos paid
that on every read and every write. Commands now go to a long-lived process,
one per (executable, ``-config``, working directory), and keep their
per-command contract: exit status, stdout, stderr and timeout.

``exiftool.exiftool_batch.ExifToolBatch`` is the scanner's own persistent
reader and is deliberately separate: it reads JSON from the bare ``exiftool``
on PATH, discards stderr and reports no exit status, which a metadata writer
cannot do without.
"""
import atexit
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# Every command starts with these: arguments and filenames travel as UTF-8.
ARGFILE_PREFIX = ('-charset', 'filename=UTF8', '-charset', 'UTF8')
# A session left unused this long is stopped; the next command starts it again.
IDLE_SECONDS = 30
_ASSIGNMENT = re.compile(r'(-[-:\w]+?#?)([-+<]?=)(.*)', re.DOTALL)
# Options that would end or re-frame a command if they reached the session.
_FRAMING_OPTIONS = re.compile(r'-(execute\d*|stay_open|@)', re.IGNORECASE)
# Linux: the ExifTool process is killed with the thread that launched it, so a
# killed Python never leaves it polling stdin forever (ExifTool ignores EOF).
_PDEATHSIG = (['setpriv', '--pdeathsig', 'KILL', '--']
              if sys.platform.startswith('linux') and shutil.which('setpriv') else [])


def _argfile_lines(arguments, directory):
    """Arguments in ExifTool's -@ argument-file format, one per line.

    Metadata values with newlines go to private UTF-8 value files: ExifTool's
    CSTR escape parser changes literal $/@ characters. Ordinary argfiles strip
    ONE space after an assignment, so that space is supplied explicitly. An
    argument file also drops a line starting with '#', strips leading
    whitespace and skips an empty line, so such arguments are refused.
    """
    lines = []
    for index, argument in enumerate(arguments):
        assignment = re.fullmatch(_ASSIGNMENT, argument)
        if _FRAMING_OPTIONS.fullmatch(argument):
            raise RuntimeError(f'ExifTool option {argument} cannot be sent to a persistent process')
        if '\n' in argument or '\r' in argument:
            if not assignment or assignment[2] == '<=':
                raise RuntimeError('ExifTool filename or option contains a newline')
            filename = os.path.join(directory(), str(index))
            descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(assignment[3].encode('utf-8'))
            argument = assignment[1] + assignment[2][:-1] + '<=' + filename
        elif assignment:
            argument = assignment[1] + assignment[2] + ' ' + assignment[3]
        elif not argument or argument[0] == '#' or argument[0].isspace():
            raise RuntimeError(f'ExifTool argument {argument!r} would be altered by an argument file; '
                               'pass an absolute path')
        lines.append(argument)
    return lines


def _text(lines):
    """Decode like ``subprocess.run(text=True, encoding='utf-8')``: universal newlines."""
    return b''.join(lines).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')


def _split_marker(lines, marker):
    """``(output, match)`` when the last line ends with ``marker``, else ``None``.

    ``-echo3``/``-echo4`` print right after the command's own output, so output
    without a trailing newline shares its last line with the marker.
    """
    if not lines:
        return None
    match = marker.search(lines[-1])
    if not match:
        return None
    rest = lines[-1][:match.start()]
    return [*lines[:-1], *([rest] if rest else [])], match


def _pump(stream, sink):
    for line in iter(stream.readline, b''):
        sink.put(line)
    sink.put(None)


_spawn_requests: queue.SimpleQueue = queue.SimpleQueue()
_spawner_lock = threading.Lock()
_spawner = None


def _spawn_loop():
    while True:
        launch, cwd, reply = _spawn_requests.get()
        try:
            reply.put(subprocess.Popen(launch, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE))
        except BaseException as ex:  # handed back to the caller's thread
            reply.put(ex)


def _popen(launch, cwd):
    """Start the process; with a death signal, from a thread that lives as long as Python.

    PR_SET_PDEATHSIG fires when the launching THREAD exits, and the viewer runs
    exports on pool threads that come and go, so those must not launch it.
    """
    global _spawner
    if launch[0] != 'setpriv':
        return subprocess.Popen(launch, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    with _spawner_lock:
        if _spawner is None:
            _spawner = threading.Thread(target=_spawn_loop, name='exiftool-spawner', daemon=True)
            _spawner.start()
    reply: queue.SimpleQueue = queue.SimpleQueue()
    _spawn_requests.put((launch, cwd, reply))
    result = reply.get()
    if isinstance(result, BaseException):
        raise result
    return result


class _Session:
    """One ``exiftool -stay_open`` process, used by one command at a time."""

    def __init__(self, executable, config, cwd):
        self._executable, self._config, self._cwd = executable, config, cwd
        self._lock = threading.Lock()
        self._process = None
        self._out = self._err = None
        self._last_used = time.monotonic()

    def _start(self):
        launch = [self._executable, *self._config, '-stay_open', 'True', '-@', '-']
        resolved = shutil.which(self._executable)
        if _PDEATHSIG and resolved:
            # Resolved first: a missing ExifTool must still fail as OSError, not as setpriv's exit 127.
            launch = [*_PDEATHSIG, resolved, *launch[1:]]
        process = _popen(launch, self._cwd)
        self._out, self._err = queue.Queue(), queue.Queue()
        for stream, sink in ((process.stdout, self._out), (process.stderr, self._err)):
            threading.Thread(target=_pump, args=(stream, sink), daemon=True).start()
        self._process = process

    def _kill(self):
        process, self._process = self._process, None
        if process is None:
            return
        if os.name == 'nt' and process.pid:
            # exiftool.exe is a launcher for its own perl.exe: end the whole tree.
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _stop(self):
        try:
            self._process.stdin.write(b'-stay_open\nFalse\n')
            self._process.stdin.flush()
            self._process.wait(timeout=5)
            self._process = None
        except (OSError, subprocess.TimeoutExpired):
            self._kill()

    def close(self):
        with self._lock:
            if self._process is not None:
                self._stop()

    def close_if_idle(self, now):
        """Stop the process when unused for ``IDLE_SECONDS``; never waits for a running command."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._process is not None and now - self._last_used >= IDLE_SECONDS:
                self._stop()
        finally:
            self._lock.release()

    @staticmethod
    def _collect(sink, done, deadline):
        """Lines up to the one ``done`` matches; ``None`` when the process exited first."""
        lines = []
        while True:
            line = sink.get(timeout=max(0.0, deadline - time.monotonic()))
            if line is None:
                return lines, None
            lines.append(line)
            split = done(lines)
            if split:
                return split

    def _exited(self, command, out, deadline):
        """The process died mid-command: report its own status and stderr, like a one-shot run."""
        err = []
        end = min(deadline, time.monotonic() + 2)
        try:
            while (line := self._err.get(timeout=max(0.0, end - time.monotonic()))) is not None:
                err.append(line)
        except queue.Empty:
            pass
        process, self._process = self._process, None
        try:
            status = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process = process
            self._kill()
            status = None
        if not status:
            raise OSError('exiftool exited during a command')
        return subprocess.CompletedProcess(command, status, _text(out), _text(err))

    def run(self, command, lines, timeout, deadline):
        if not self._lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise subprocess.TimeoutExpired(command, timeout)
        try:
            if self._process is None or self._process.poll() is not None:
                self._start()
            # Unguessable markers: a tag value echoed by -X can never fake the end of a command.
            token = secrets.token_hex(16)
            number = secrets.randbelow(10 ** 15)
            ready = b'{ready%d}' % number
            status_marker = re.compile(rb'\{facet-status ' + token.encode() + rb' (-?\d+)\}\r?\n\Z')
            err_marker = re.compile(rb'\{facet-done ' + token.encode() + rb'\}\r?\n\Z')
            script = ''.join(value + '\n' for value in lines)
            script += (f'-echo3\n{{facet-status {token} ${{status}}}}\n'
                       f'-echo4\n{{facet-done {token}}}\n-execute{number}\n')
            try:
                self._process.stdin.write(script.encode('utf-8'))
                self._process.stdin.flush()
                out, ended = self._collect(
                    self._out, lambda got: (got[:-1], True) if got[-1].rstrip(b'\r\n') == ready else None,
                    deadline)
                if ended is None:
                    return self._exited(command, out, deadline)
                status = _split_marker(out, status_marker)
                if status is None:
                    raise OSError('exiftool did not report a command status')
                out, match = status
                err, ended = self._collect(self._err, lambda got: _split_marker(got, err_marker), deadline)
                if ended is None:
                    raise OSError('exiftool exited during a command')
            except queue.Empty:
                self._kill()
                raise subprocess.TimeoutExpired(command, timeout) from None
            except (OSError, ValueError):  # a broken pipe, a lost status: the process is unusable
                self._kill()
                raise
            return subprocess.CompletedProcess(command, int(match[1]), _text(out), _text(err))
        finally:
            self._last_used = time.monotonic()
            self._lock.release()


_sessions: dict = {}
_sessions_lock = threading.Lock()
_shutting_down = False
_reaper = None


def _reap_idle(now):
    with _sessions_lock:
        sessions = list(_sessions.values())
    for session in sessions:
        session.close_if_idle(now)


def _reap_loop():
    while True:
        time.sleep(IDLE_SECONDS / 3)
        _reap_idle(time.monotonic())


def _session(executable, config):
    global _reaper
    key = (executable, *config, os.getcwd())
    with _sessions_lock:
        if _shutting_down:
            raise OSError('exiftool sessions are closed: the interpreter is exiting')
        session = _sessions.get(key)
        if session is None:
            # ExifTool requires -config to be the first actual command-line option.
            session = _sessions[key] = _Session(executable, config, key[-1])
        if _reaper is None:
            _reaper = threading.Thread(target=_reap_loop, name='exiftool-reaper', daemon=True)
            _reaper.start()
        return session


def close_sessions():
    """Stop every persistent ExifTool process; the next command starts a new one."""
    with _sessions_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.close()


def _shutdown():
    global _shutting_down
    with _sessions_lock:
        _shutting_down = True
    close_sessions()


atexit.register(_shutdown)


def run_exiftool_process(args, *, timeout):
    """Run one ExifTool command; returns a ``CompletedProcess`` (text stdout/stderr).

    Arguments travel as UTF-8 through the -@ argument file, so Unicode values and
    filenames survive Windows' ANSI command line. Raises ``subprocess.TimeoutExpired``
    after ``timeout`` seconds, waiting for a busy session included (the process is
    killed and restarted on next use), ``OSError`` when ExifTool cannot start or
    dies without an exit status, and ``RuntimeError`` before anything runs for an
    argument an argument file cannot carry (a newline in a filename or option, a
    leading '#' or whitespace, an empty argument, or a framing option).
    """
    deadline = time.monotonic() + timeout
    command = list(args)
    executable, *arguments = command
    config = arguments[:2] if arguments[:1] == ['-config'] else []
    arguments = arguments[len(config):]
    value_files = []

    def directory():
        # Only a newline value needs one, so most commands create no directory at all.
        if not value_files:
            value_files.append(tempfile.TemporaryDirectory(prefix='facet-exiftool-'))
        return value_files[0].name
    try:
        lines = [*ARGFILE_PREFIX, *_argfile_lines(arguments, directory)]
        return _session(executable, config).run(command, lines, timeout, deadline)
    finally:
        for value_file in value_files:
            value_file.cleanup()
