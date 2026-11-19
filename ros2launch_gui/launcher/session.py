"""Window side of a launch: a runner child process driven through Qt."""

import json
import os
import signal
import sys
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from python_qt_binding.QtCore import QObject
from python_qt_binding.QtCore import QProcess
from python_qt_binding.QtCore import QProcessEnvironment
from python_qt_binding.QtCore import QTimer
from python_qt_binding.QtCore import Signal

import ros2launch_gui

from .protocol import encode
from .protocol import LineAssembler
from .protocol import LineDecoder
from .protocol import to_text

RUNNER_MODULE = 'ros2launch_gui.launcher.runner'
DESCRIBE_TIMEOUT = 15.0
KILL_GRACE = 2.0

# The runner is imported from the same tree as this window, even from a source checkout.
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(ros2launch_gui.__file__)))


def _runner_process(parent, environment: Optional[Dict[str, str]] = None) -> QProcess:
    """Return a QProcess for the runner, in the given environment (default: this one's)."""
    process = QProcess(parent)
    if environment is None:
        env = QProcessEnvironment.systemEnvironment()
    else:
        env = QProcessEnvironment()
        for name, value in environment.items():
            env.insert(name, value)
    python_path = env.value('PYTHONPATH', '')
    env.insert('PYTHONPATH', _PACKAGE_ROOT + (os.pathsep + python_path if python_path else ''))
    process.setProcessEnvironment(env)
    return process


def _signal_group(pgid: Optional[int], sig: int) -> None:
    if not pgid:
        return
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class LaunchSession(QObject):
    """One launch file, run (and re-run) in its own runner process."""

    state_changed = Signal(str)
    process_started = Signal(str, int, str, bool)
    process_output = Signal(str, str)
    process_exited = Signal(str, int, int)
    state_transition = Signal(str, str, str)
    finished = Signal(int)

    def __init__(self, launch_file_path: str, parent=None, stop_timeout: float = 20.0,
                 environment: Optional[Dict[str, str]] = None):
        super().__init__(parent)
        self.launch_file_path = launch_file_path
        self.environment = environment
        self.stop_timeout = stop_timeout
        self._state = 'stopped'
        self._process = None
        self._pgid = None
        self._run = 0
        self._decoder = LineDecoder()
        self._stderr_lines = LineAssembler()
        self._stop_requested = False
        self._stopping_pids = set()
        self._failed = False

    @property
    def state(self) -> str:
        return self._state

    @property
    def pgid(self) -> Optional[int]:
        """Process group of the current or last run (the runner's pid)."""
        return self._pgid

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def start(self, arguments: List[str]) -> None:
        """Start the launch with 'name:=value' arguments; ignored while it runs."""
        if self._state in ('running', 'stopping'):
            return
        self._run += 1
        self._decoder = LineDecoder()
        self._stderr_lines = LineAssembler()
        self._stop_requested = False
        self._stopping_pids = set()
        self._failed = False
        process = _runner_process(self, self.environment)
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        process.start(sys.executable,
                      ['-m', RUNNER_MODULE, 'run', self.launch_file_path, *arguments])
        self._pgid = process.processId() or None
        self._set_state('running')

    def _send(self, message: dict) -> None:
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            self._process.write(encode(message))

    def stop(self) -> None:
        """Shut the launch down; escalate to killing its process group if it hangs."""
        if self._state != 'running':
            return
        self._stop_requested = True
        self._set_state('stopping')
        self._send({'type': 'shutdown'})
        run = self._run
        QTimer.singleShot(int(self.stop_timeout * 1000), lambda: self._escalate(run))

    def _escalate(self, run: int) -> None:
        if run != self._run or self._state != 'stopping':
            return
        self.process_output.emit('', '[launcher] launch did not stop in time; terminating')
        _signal_group(self._pgid, signal.SIGTERM)
        QTimer.singleShot(int(KILL_GRACE * 1000), lambda: self._final_kill(run))

    def _final_kill(self, run: int) -> None:
        if run == self._run and self._state == 'stopping':
            self.kill()

    def kill(self) -> None:
        """Kill the runner's whole process group immediately."""
        _signal_group(self._pgid, signal.SIGKILL)

    def stop_process(self, pid: int) -> None:
        """Interrupt one process of the launch."""
        self._stopping_pids.add(pid)
        self._send({'type': 'stop_process', 'pid': pid})

    def lifecycle(self, node_name: str, transition_id: int) -> None:
        """Request a lifecycle transition of a node in the launch."""
        self._send({'type': 'lifecycle', 'node_name': node_name,
                    'transition_id': transition_id})

    def _on_stdout(self) -> None:
        data = bytes(self._process.readAllStandardOutput())
        for message in self._decoder.feed(data):
            self._dispatch(message)

    def _on_stderr(self) -> None:
        text = self._stderr_lines.feed(bytes(self._process.readAllStandardError()))
        if text:
            self.process_output.emit('', text)

    def _flush_stderr(self) -> None:
        text = self._stderr_lines.flush()
        if text:
            self.process_output.emit('', text)

    def _dispatch(self, message: dict) -> None:
        kind = message.get('type')
        if kind == 'started':
            self._pgid = message['pid']
        elif kind == 'process_started':
            self.process_started.emit(message['name'], message['pid'],
                                      message.get('node_name', ''),
                                      bool(message.get('is_lifecycle')))
        elif kind == 'process_io':
            self.process_output.emit(message['name'], message['text'])
        elif kind == 'process_exited':
            code = message['return_code']
            code = -1 if code is None else code
            expected = self._stop_requested or message['pid'] in self._stopping_pids
            if code != 0 and not expected:
                self._failed = True
            self.process_exited.emit(message['name'], message['pid'], code)
        elif kind == 'state_transition':
            self.state_transition.emit(message['node_name'], message['start'], message['goal'])
        elif kind == 'launch_exited':
            if message.get('return_code') and not self._stop_requested:
                self._failed = True
        elif kind == 'error':
            self.process_output.emit('', '[launcher] ' + message.get('message', ''))

    def _on_error(self, error) -> None:
        if error == QProcess.FailedToStart:
            self.process_output.emit('', '[launcher] failed to start the launch runner')
            self._failed = True
            self._finish(-1)

    def _on_finished(self, exit_code, exit_status) -> None:
        self._on_stdout()
        self._on_stderr()
        self._flush_stderr()
        if exit_status != QProcess.NormalExit and not self._stop_requested:
            self._failed = True
        elif exit_code != 0 and not self._stop_requested:
            self._failed = True
        self._finish(exit_code)

    def _finish(self, exit_code: int) -> None:
        if self._state == 'stopped' or self._state == 'failed':
            return
        # Nothing of this launch may outlive it, whatever the runner managed to clean up.
        self.kill()
        self._run += 1
        self._set_state('failed' if self._failed else 'stopped')
        self.finished.emit(exit_code)


_pending_describes = set()


def describe_launch_file(
        launch_file_path: str,
        callback: Callable[[Optional[List[dict]], Optional[str]], None],
        timeout: float = DESCRIBE_TIMEOUT,
        environment: Optional[Dict[str, str]] = None) -> None:
    """
    Read a launch file's declared arguments in a child process, without blocking.

    callback(arguments, None) on success, callback(None, error_message) on failure.
    """
    process = _runner_process(None, environment)
    _pending_describes.add(process)
    done = []

    def finish(arguments, error):
        if done:
            return
        done.append(True)
        _pending_describes.discard(process)
        callback(arguments, error)

    def on_finished(exit_code, exit_status):
        out = to_text(bytes(process.readAllStandardOutput()))
        err = to_text(bytes(process.readAllStandardError()))
        try:
            result = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            result = {}
        if 'arguments' in result:
            finish(result['arguments'], None)
        else:
            message = result.get('error') or err.strip() or 'exit code {}'.format(exit_code)
            finish(None, message)

    def on_timeout():
        if not done:
            process.kill()
            finish(None, 'timed out after {:.0f} s reading the launch file'.format(timeout))

    process.finished.connect(on_finished)
    process.errorOccurred.connect(
        lambda e: finish(None, 'failed to start the launch runner')
        if e == QProcess.FailedToStart else None)
    QTimer.singleShot(int(timeout * 1000), on_timeout)
    process.start(sys.executable, ['-m', RUNNER_MODULE, 'describe', launch_file_path])
