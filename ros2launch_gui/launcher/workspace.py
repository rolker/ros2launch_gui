"""
Workspaces: source one into a captured environment, list its packages, remember it.

Sourcing runs an interactive bash, so ~/.bashrc applies as in a new terminal.
"""

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
import shutil
import signal
import tempfile
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from python_qt_binding.QtCore import QProcess
from python_qt_binding.QtCore import QProcessEnvironment
from python_qt_binding.QtCore import QSettings
from python_qt_binding.QtCore import QTimer

from .discovery import _is_under
from .protocol import to_text

SOURCE_TIMEOUT = 60.0
MAX_RECENT = 10
ENV_MARKER = b'\0__ROS2LAUNCH_GUI_ENV__\0'
# Set by bash itself for the capturing shell; meaningless for the launches.
_SHELL_VARIABLES = {'SHLVL', 'PWD', 'OLDPWD', '_'}
# Interactive bash without a terminal says so on stderr; not worth showing.
_BASH_NOISE = ('cannot set terminal process group', 'no job control in this shell')
_SOURCE_SCRIPT = 'source "$1"; printf "\\0__ROS2LAUNCH_GUI_ENV__\\0"; env -0'

_pending = set()


class WorkspaceError(Exception):
    """A workspace cannot be opened."""


@dataclass
class Workspace:
    """A sourced workspace."""

    root: str
    prefix: str
    setup_script: str
    env: Dict[str, str]


def _normalise(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path))
    return path.rstrip(os.sep) or os.sep


def find_setup_script(path: str) -> str:
    """Return the setup.bash of a workspace root or of an install directory."""
    path = _normalise(path)
    if not os.path.isdir(path):
        raise WorkspaceError('{} does not exist'.format(path))
    for candidate in (os.path.join(path, 'install', 'setup.bash'),
                      os.path.join(path, 'setup.bash')):
        if os.path.isfile(candidate):
            return candidate
    raise WorkspaceError(
        'No install/setup.bash in {} — build the workspace with colcon first.'.format(path))


def parse_env(output: bytes) -> Dict[str, str]:
    """Parse `env -0` output that follows ENV_MARKER; anything before it is ignored."""
    start = output.find(ENV_MARKER)
    if start < 0:
        raise WorkspaceError('the shell did not print its environment')
    env = {}
    for item in output[start + len(ENV_MARKER):].split(b'\0'):
        name, sep, value = to_text(item).partition('=')
        if sep and name and name not in _SHELL_VARIABLES:
            env[name] = value
    return env


def _source_command(setup_script: str) -> List[str]:
    command = ['bash', '-i', '-c', _SOURCE_SCRIPT, 'ros2launch_gui', setup_script]
    # A session of its own keeps the interactive shell away from the launcher's terminal.
    if shutil.which('setsid'):
        command = ['setsid', '-w'] + command
    return command


def _stderr_tail(stderr: bytes, lines: int = 5) -> str:
    kept = [line for line in to_text(stderr).splitlines()
            if line.strip() and not any(noise in line for noise in _BASH_NOISE)]
    return '\n'.join(kept[-lines:])


def source_workspace(
        path: str,
        callback: Callable[[Optional[Workspace], Optional[str]], None],
        base_env: Optional[Dict[str, str]] = None,
        timeout: float = SOURCE_TIMEOUT) -> None:
    """
    Source a workspace in a child shell without blocking; report from the event loop.

    callback(workspace, None) on success, callback(None, error_message) on failure.
    """
    done = []

    def finish(result, error):
        if not done:
            done.append(True)
            callback(result, error)

    try:
        setup_script = find_setup_script(path)
    except WorkspaceError as e:
        message = str(e)
        QTimer.singleShot(0, lambda: finish(None, message))
        return
    prefix = os.path.dirname(setup_script)
    root = os.path.dirname(prefix) if os.path.basename(prefix) == 'install' else prefix

    process = QProcess()
    _pending.add(process)
    env = QProcessEnvironment()
    for name, value in (os.environ if base_env is None else base_env).items():
        env.insert(name, value)
    process.setProcessEnvironment(env)
    process.setWorkingDirectory(root)

    def on_finished(exit_code, exit_status):
        _pending.discard(process)
        if done:
            return
        out = bytes(process.readAllStandardOutput())
        err = _stderr_tail(bytes(process.readAllStandardError()))
        try:
            captured = parse_env(out)
        except WorkspaceError as e:
            finish(None, '{}: {}{}'.format(setup_script, e, '\n' + err if err else ''))
            return
        paths = captured.get('AMENT_PREFIX_PATH', '').split(os.pathsep)
        if not any(p and _is_under(p, prefix) for p in paths):
            finish(None, 'sourcing {} did not add {} to AMENT_PREFIX_PATH{}'.format(
                setup_script, prefix, '\n' + err if err else ''))
            return
        finish(Workspace(root=root, prefix=prefix, setup_script=setup_script,
                         env=captured), None)

    def on_timeout():
        if done:
            return
        pid = process.processId()
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)  # the shell leads its own session
            except (ProcessLookupError, PermissionError):
                pass
        process.kill()  # stays in _pending until finished
        finish(None, 'timed out after {:.0f} s sourcing {}'.format(timeout, setup_script))

    process.finished.connect(on_finished)
    process.errorOccurred.connect(
        lambda e: finish(None, 'failed to start bash') if e == QProcess.FailedToStart else None)
    QTimer.singleShot(int(timeout * 1000), on_timeout)
    command = _source_command(setup_script)
    process.start(command[0], command[1:])
    process.closeWriteChannel()


def packages_with_prefixes(ament_prefix_path: str) -> Dict[str, str]:
    """
    Return package name to install prefix from the ament index of these prefixes.

    Like ament_index_python.get_packages_with_prefixes(), but for a given
    AMENT_PREFIX_PATH instead of the process environment; the first prefix wins.
    """
    packages = {}
    for prefix in ament_prefix_path.split(os.pathsep):
        index = os.path.join(prefix, 'share', 'ament_index', 'resource_index', 'packages')
        if not prefix or not os.path.isdir(index):
            continue
        for name in sorted(os.listdir(index)):
            if not name.startswith('.'):
                packages.setdefault(name, prefix)
    return packages


class RecentWorkspaces:
    """Recently opened workspaces, shared by every launcher instance."""

    KEY = 'recent_workspaces'

    def __init__(self, settings: Optional[QSettings] = None):
        self._settings = settings or QSettings('ros2launch_gui', 'launcher')

    def paths(self) -> List[str]:
        self._settings.sync()
        try:
            paths = json.loads(self._settings.value(self.KEY, '[]') or '[]')
        except (TypeError, ValueError):
            return []
        return [p for p in paths if isinstance(p, str)][:MAX_RECENT]

    def add(self, path: str) -> None:
        paths = [p for p in self.paths() if p != path]
        self._store([path] + paths)

    def remove(self, path: str) -> None:
        self._store([p for p in self.paths() if p != path])

    def _store(self, paths: List[str]) -> None:
        self._settings.setValue(self.KEY, json.dumps(paths[:MAX_RECENT]))
        self._settings.sync()


def lock_directory() -> str:
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if runtime and os.path.isdir(runtime):
        return os.path.join(runtime, 'ros2launch_gui')
    return os.path.join(tempfile.gettempdir(), 'ros2launch_gui-{}'.format(os.getuid()))


class LaunchLock:
    """Marks a launch file as running in this launcher, across launcher instances."""

    def __init__(self, launch_file_path: str, directory: Optional[str] = None):
        digest = hashlib.sha1(os.path.realpath(launch_file_path).encode()).hexdigest()[:20]
        self._directory = directory or lock_directory()
        self.path = os.path.join(self._directory, digest + '.lock')
        self._fd = None

    def acquire(self) -> bool:
        """Take the lock; False if another holder has it."""
        if self._fd is not None:
            return True
        os.makedirs(self._directory, mode=0o700, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        return True

    def holder(self) -> str:
        """Return the pid written by the holder, or ''."""
        try:
            with open(self.path) as f:
                return f.read().strip()
        except OSError:
            return ''

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


def launcher_setup_script() -> str:
    """Return the setup.bash that makes this launcher importable (for the desktop entry)."""
    from ament_index_python import get_package_prefix

    prefix = get_package_prefix('ros2launch_gui')
    for candidate in (os.path.join(prefix, 'setup.bash'),
                      os.path.join(os.path.dirname(prefix), 'setup.bash')):
        if os.path.isfile(candidate):
            return candidate
    raise WorkspaceError('no setup.bash found for the ros2launch_gui install at ' + prefix)


def _single_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def write_desktop_entry(home: str, setup_script: str) -> Tuple[str, str]:
    """Write ~/.local/bin/ros2-launcher and its desktop entry; return both paths."""
    wrapper = os.path.join(home, '.local', 'bin', 'ros2-launcher')
    desktop = os.path.join(home, '.local', 'share', 'applications', 'ros2-launcher.desktop')
    os.makedirs(os.path.dirname(wrapper), exist_ok=True)
    os.makedirs(os.path.dirname(desktop), exist_ok=True)
    with open(wrapper, 'w') as f:
        f.write('#!/bin/bash\n'
                '# Written by: ros2 run ros2launch_gui launcher --install-desktop-entry\n'
                'source {}\n'
                'exec python3 -m ros2launch_gui.launcher.main "$@"\n'.format(
                    _single_quote(setup_script)))
    os.chmod(wrapper, 0o755)
    exec_path = '"{}"'.format(wrapper) if ' ' in wrapper else wrapper
    with open(desktop, 'w') as f:
        f.write('[Desktop Entry]\n'
                'Type=Application\n'
                'Name=ROS 2 Launcher\n'
                'Comment=Open a ROS 2 workspace, start and stop its launch files, '
                'read their logs\n'
                'Exec={} %f\n'
                'Icon=applications-engineering\n'
                'Terminal=false\n'
                'Categories=Development;\n'.format(exec_path))
    return wrapper, desktop
