"""ExifTool's ``-stay_open True -@ -`` command loop, shared by both test fakes.

Standard library only: the script fake in ``tests/exiftool_fake.py`` imports this
module by path from a fresh interpreter, which must not pay for ``utils``.
"""
import re
import subprocess

# An argument file line: the writer supplies ONE space after an assignment.
_ASSIGNMENT = re.compile(r'(-[-:\w]+?#?)([-+<]?=) (.*)', re.DOTALL)
_EXECUTE = re.compile(r'-execute(\d*)')


class Exit(Exception):
    """Raised by a handler: the process writes ``stderr`` and exits with ``status``."""

    def __init__(self, status, stderr=''):
        super().__init__(status)
        self.status, self.stderr = status, stderr


def parsed(lines, prefix):
    """One command's argument-file lines as ExifTool reads them."""
    if tuple(lines[:len(prefix)]) == tuple(prefix):
        lines = lines[len(prefix):]
    result = []
    for line in lines:
        match = _ASSIGNMENT.fullmatch(line)
        result.append(match[1] + match[2] + match[3] if match and match[2] != '<=' else line)
    return result


class Protocol:
    """The command loop over one process's stdin lines.

    ``answer(lines, args)`` answers one command with ``(status, stdout, stderr)``;
    ``lines`` are the raw argument-file lines, ``args`` the parsed arguments.
    ``feed(line)`` returns ``None`` (more lines needed), ``'stop'``, ``'hang'``,
    an ``Exit``, or ``(stdout bytes, stderr bytes)`` for a finished command.
    ``report_status=False`` drops the ``-echo3`` text, as if ExifTool never
    printed the command status.
    """

    def __init__(self, answer, prefix, report_status=True):
        self.answer = answer
        self.prefix = prefix
        self.report_status = report_status
        self._block = []
        self._stopping = False

    def feed(self, line):
        if self._stopping:
            self._stopping = False
            return 'stop' if line == 'False' else None
        if line == '-stay_open':
            self._stopping = True
            return None
        match = _EXECUTE.fullmatch(line)
        if not match:
            self._block.append(line)
            return None
        block, self._block = self._block, []
        arguments, echo3, echo4 = [], [], []
        lines = iter(block)
        for value in lines:
            if value == '-echo3':
                echo3.append(next(lines))
            elif value == '-echo4':
                echo4.append(next(lines))
            else:
                arguments.append(value)
        try:
            status, out, err = self.answer(arguments, parsed(arguments, self.prefix))
        except subprocess.TimeoutExpired:
            return 'hang'
        except Exit as ex:
            return ex
        except OSError:
            return Exit(1)
        if self.report_status:
            out += ''.join(text.replace('${status}', str(status)) + '\n' for text in echo3)
        err += ''.join(text.replace('${status}', str(status)) + '\n' for text in echo4)
        return (out + f'{{ready{match[1]}}}\n').encode('utf-8'), err.encode('utf-8')
