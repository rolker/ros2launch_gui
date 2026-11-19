"""
Child-process entry point used by the launcher window.

``describe <file>`` prints the launch file's declared arguments as JSON.
``run <file> [name:=value ...]`` runs the launch and streams events (see protocol.py).
"""

import argparse
import json
import os
import queue
import signal
import sys
import threading
import time
from typing import List
from typing import Optional

import logging
from typing import Tuple

from launch import LaunchDescription
from launch import LaunchService
import launch.logging
from launch.actions import EmitEvent
from launch.actions import IncludeLaunchDescription
from launch.actions import Shutdown
from launch.actions import TimerAction
from launch.events.process import SignalProcess
from launch.events.process.process_matchers import matches_pid
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import TextSubstitution
from launch_ros.events import matches_node_name
from launch_ros.events.lifecycle import ChangeState
from ros2launch.api.api import get_launch_description_from_any_launch_file

from ..actions import DisplayUserInterface
from ..api import UserInterface
from ..events import QueryUserInterface
from .protocol import encode
from .protocol import LineAssembler
from .protocol import LineDecoder

# The launch is ended once nothing has been running or pending for this long. launch would
# end an idle launch by itself, but the UI poll timer keeps it busy forever (see README).
IDLE_SHUTDOWN_DELAY = 1.0
# process_io events queued for the window beyond this are dropped (and counted), so a window
# that is not reading can never block the launch's event loop, and with it the nodes.
MAX_QUEUED_IO = 10000


def _describe_default(default_value) -> Optional[str]:
    if default_value is None:
        return None
    return ' + '.join(token.describe() for token in default_value)


def _default_text(default_value) -> Optional[str]:
    if default_value is None:
        return None
    if all(isinstance(token, TextSubstitution) for token in default_value):
        return ''.join(token.text for token in default_value)
    return None


def describe_arguments(launch_file_path: str) -> List[dict]:
    """Return the declared arguments of a launch file without running it."""
    launch_description = get_launch_description_from_any_launch_file(launch_file_path)
    arguments = []
    for argument in launch_description.get_launch_arguments():
        choices = argument.choices
        arguments.append({
            'name': argument.name,
            'default': _describe_default(argument.default_value),
            'default_text': _default_text(argument.default_value),
            'description': argument.description,
            'choices': list(choices) if choices is not None else None,
            'conditional': bool(argument._conditionally_included),
        })
    return arguments


def _describe_main(launch_file_path: str) -> int:
    try:
        result = {'arguments': describe_arguments(launch_file_path)}
        code = 0
    except Exception as e:
        result = {'error': '{}: {}'.format(type(e).__name__, e)}
        code = 1
    sys.stdout.write(json.dumps(result) + '\n')
    sys.stdout.flush()
    return code


class EventWriter:
    """
    Write protocol events to the window from a thread of its own.

    send() never blocks: the launch's event loop calls it, and blocking there would stop
    launch from reading its processes' pipes, which in turn blocks the processes.
    """

    def __init__(self, stream, max_queued_io: int = MAX_QUEUED_IO):
        self._stream = stream
        self._max_queued_io = max_queued_io
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._queued_io = 0
        self._dropped = 0
        self._thread = threading.Thread(target=self._write_loop, daemon=True)
        self._thread.start()

    def send(self, message: dict) -> None:
        with self._lock:
            if message.get('type') == 'process_io':
                if self._queued_io >= self._max_queued_io:
                    self._dropped += 1
                    return
                self._queued_io += 1
        self._queue.put(message)

    def _write(self, message: dict) -> None:
        try:
            self._stream.write(encode(message))
        except (BrokenPipeError, ValueError, OSError):
            pass  # the window is gone; stdin EOF shuts the launch down

    def _write_loop(self) -> None:
        while True:
            message = self._queue.get()
            if message is not None:
                self._write(message)
            with self._lock:
                if message is not None and message.get('type') == 'process_io':
                    self._queued_io -= 1
                dropped, self._dropped = self._dropped, 0
            if dropped:
                self._write({'type': 'error', 'message': '{} output lines dropped: the '
                             'launcher window was not keeping up'.format(dropped)})
            if message is None:
                break

    def close(self, timeout: float = 5.0) -> None:
        """Write everything queued, then stop the writer thread."""
        self._queue.put(None)
        self._thread.join(timeout)


def read_commands(fd: int, commands: queue.Queue) -> None:
    """Feed commands from the window into a queue; a closed stream means shutdown."""
    # Raw os.read, not sys.stdin.buffer: a daemon thread blocked inside a buffered reader
    # makes the interpreter abort at exit ("could not acquire lock for <stdin>").
    decoder = LineDecoder()
    while True:
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b''
        if not data:
            break
        for command in decoder.feed(data):
            commands.put(command)
    commands.put({'type': 'shutdown'})


class ReporterUserInterface(UserInterface):
    """A user interface without a display: reports launch events to the launcher window."""

    def __init__(self, launch_description, writer: EventWriter, commands: queue.Queue,
                 launch_service: LaunchService, debug: bool = False):
        super().__init__(launch_description, debug)
        self._writer = writer
        self._commands = commands
        self._launch_service = launch_service
        self._running = set()
        self._exited = set()
        self._idle_since = None
        self._shutdown_sent = False
        self._assemblers = {}

    def _launch_busy(self) -> bool:
        """Whether launch has work pending, ignoring this UI's own poll timer."""
        if self._running:
            return True
        # The same bookkeeping LaunchService._is_idle() uses (Humble launch 1.0.x).
        for entity, future in self._launch_service._entity_future_pairs:
            if not future.done() and not _is_poll_timer(entity):
                return True
        context = self._launch_service.context
        return any(not future.done() for future in context._completion_futures)

    def _safe_callback(self, fn, event, context):
        # The base class drops events once the UI is closing, because a display backend is
        # torn down by then. The reporter's pipe outlives the shutdown, and the window needs
        # the process exits that shutdown causes, so keep reporting until the launch ends.
        try:
            fn(event, context)
        except Exception as e:
            self._writer.send({'type': 'error', 'message': 'Reporter failed on {}: {}'.format(
                event.name, e)})
        return None

    def _shutdown(self, reason: str) -> None:
        if not self._shutdown_sent:
            self._shutdown_sent = True
            self.add_pending_action(Shutdown(reason=reason))

    def _action_for(self, command: dict):
        kind = command.get('type')
        if kind == 'shutdown':
            self._shutdown('stopped from the launcher')
        elif kind == 'stop_process':
            self.add_pending_action(EmitEvent(event=SignalProcess(
                signal_number=signal.SIGINT, process_matcher=matches_pid(command['pid']))))
        elif kind == 'lifecycle':
            self.add_pending_action(EmitEvent(event=ChangeState(
                lifecycle_node_matcher=matches_node_name(command['node_name']),
                transition_id=command['transition_id'])))
        else:
            self._writer.send({'type': 'error', 'message': 'Unknown command: {}'.format(command)})

    def spin_once(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            self._action_for(command)
        if self._launch_busy():
            self._idle_since = None
            return
        now = time.monotonic()
        if self._idle_since is None:
            self._idle_since = now
        elif now - self._idle_since >= IDLE_SHUTDOWN_DELAY:
            self._shutdown('nothing left running')

    def on_process_started(self, process_name, pid, action):
        self._running.add(pid)
        is_node = action.type_name in ('Node', 'LifecycleNode', 'ComposableNodeContainer')
        self._writer.send({
            'type': 'process_started', 'name': process_name, 'pid': pid,
            'node_name': action.label if is_node else '',
            'is_lifecycle': action.type_name == 'LifecycleNode',
        })

    def on_process_exited(self, process_name, pid, action, return_code):
        self._running.discard(pid)
        self._exited.add(pid)
        for key in [k for k in self._assemblers if k[0] == process_name]:
            self._send_io(process_name, self._assemblers.pop(key).flush())
        self._writer.send({
            'type': 'process_exited', 'name': process_name, 'pid': pid,
            'return_code': return_code,
        })

    def _send_io(self, process_name: str, text: str) -> None:
        if text:
            self._writer.send({'type': 'process_io', 'name': process_name, 'text': text})

    def _on_process_io(self, event, context):
        # Overrides the base handler to keep stdout and stderr apart: ProcessIO.text is a raw
        # pipe chunk, so each stream needs its own line and UTF-8 reassembly.
        try:
            key = (event.process_name, 'stderr' if event.from_stderr else 'stdout')
            assembler = self._assemblers.get(key)
            if assembler is None:
                assembler = self._assemblers[key] = LineAssembler()
            text = event.text if isinstance(event.text, bytes) else event.text.encode('utf-8')
            self._send_io(event.process_name, assembler.feed(text))
            if event.pid in self._exited:  # output that arrives after the exit
                self._send_io(event.process_name, self._assemblers.pop(key).flush())
        except Exception as e:
            self._writer.send({'type': 'error', 'message': 'Reporter failed on output: {}'.format(
                e)})
        return None

    def on_state_transition(self, entity, start_state, goal_state):
        self._writer.send({
            'type': 'state_transition', 'node_name': entity.label,
            'start': start_state, 'goal': goal_state,
        })


def _is_poll_timer(entity) -> bool:
    """Whether entity is the UI poll TimerAction scheduled by OnQueryUserInterface."""
    if not isinstance(entity, TimerAction):
        return False
    return any(isinstance(action, EmitEvent) and isinstance(action.event, QueryUserInterface)
               for action in entity.actions)


def parse_launch_arguments(arguments: List[str]) -> List[Tuple[str, str]]:
    """
    Split 'name:=value' arguments; the value may be empty or contain ':='.

    ros2launch's own parser rejects 'name:=', which the launcher passes for an emptied field.
    """
    parsed = []
    for argument in arguments:
        name, separator, value = argument.partition(':=')
        if not separator or not name:
            raise ValueError("malformed launch argument '{}', expected 'name:=value'".format(
                argument))
        parsed.append((name, value))
    return parsed


class _DropProcessOutput(logging.Filter):
    """Keep process output off launch's screen handler; it reaches the window as events."""

    def filter(self, record: logging.LogRecord) -> bool:
        # launch.logging.get_output_loggers() names these '<process name>-stdout|stderr'.
        return not record.name.endswith(('-stdout', '-stderr'))


def _group_members(pgid: int) -> List[int]:
    """Return the pids in a process group, other than this process (Linux /proc)."""
    members = []
    for entry in os.listdir('/proc'):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            with open('/proc/{}/stat'.format(entry)) as f:
                stat = f.read()
        except OSError:
            continue
        # Fields after the parenthesised command name: state ppid pgrp ...
        fields = stat[stat.rfind(')') + 2:].split()
        if len(fields) > 2 and fields[2] == str(pgid) and fields[0] != 'Z':
            members.append(int(entry))
    return members


def _kill_group_members(grace: float = 1.0) -> None:
    """End processes launch left behind in this group (e.g. grandchildren ignoring SIGINT)."""
    pgid = os.getpgrp()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        members = _group_members(pgid)
        if not members:
            return
        for pid in members:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and _group_members(pgid):
            time.sleep(0.05)


def _run_main(launch_file_path: str, launch_arguments: List[str]) -> int:
    # Own process group: the window can then always take the whole launch down.
    os.setpgrp()
    # Keep the real stdout for the protocol; everything else printed goes to stderr.
    protocol_stream = os.fdopen(os.dup(1), 'wb', buffering=0)
    os.dup2(2, 1)
    writer = EventWriter(protocol_stream)
    writer.send({'type': 'started', 'pid': os.getpid()})

    commands = queue.Queue()
    threading.Thread(
        target=read_commands, args=(sys.stdin.fileno(), commands), daemon=True).start()
    try:
        code = _run_launch(launch_file_path, launch_arguments, writer, commands)
    except Exception as e:
        writer.send({'type': 'error', 'message': '{}: {}'.format(type(e).__name__, e)})
        code = 1
    try:
        _kill_group_members()
    except OSError as e:
        writer.send({'type': 'error', 'message': 'Process group cleanup failed: {}'.format(e)})
    writer.send({'type': 'launch_exited', 'return_code': code})
    writer.close()
    return code


def _run_launch(launch_file_path: str, launch_arguments: List[str], writer: EventWriter,
                commands: queue.Queue) -> int:
    # Mirrors ros2launch.api.api.launch_a_launch_file() (Humble), with the launcher's
    # argument parsing and the reporter UI wrapped around the included file.
    parsed_arguments = parse_launch_arguments(launch_arguments)
    launch.logging.launch_config.get_screen_handler().addFilter(_DropProcessOutput())
    launch_service = LaunchService(argv=list(launch_arguments), noninteractive=True)

    def ui_launcher(description, context, debug):
        return ReporterUserInterface(description, writer, commands, launch_service, debug)

    include = LaunchDescription([
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(launch_file_path),
            launch_arguments=parsed_arguments),
    ])
    launch_service.include_launch_description(LaunchDescription([
        DisplayUserInterface(launch_description=include, ui_launcher=ui_launcher),
    ]))
    return launch_service.run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='ros2launch_gui.launcher.runner')
    commands = parser.add_subparsers(dest='command', required=True)
    describe = commands.add_parser('describe', help='print declared launch arguments as JSON')
    describe.add_argument('launch_file')
    run = commands.add_parser('run', help='run a launch file, streaming events on stdout')
    run.add_argument('launch_file')
    run.add_argument('launch_arguments', nargs='*', help="'name:=value' pairs")
    args = parser.parse_args(argv)
    if args.command == 'describe':
        return _describe_main(args.launch_file)
    return _run_main(args.launch_file, args.launch_arguments)


if __name__ == '__main__':
    sys.exit(main())
