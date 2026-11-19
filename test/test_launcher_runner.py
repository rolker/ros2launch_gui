import json
import os
import threading
import time

from launcher_helpers import ARGS_LAUNCH
from launcher_helpers import run_runner
from launcher_helpers import RunnerProcess
from launcher_helpers import SLEEPER_LAUNCH
from launcher_helpers import wait_group_gone
from launcher_helpers import write_launch_file
import pytest

from ros2launch_gui.launcher.protocol import LineDecoder
from ros2launch_gui.launcher.runner import describe_arguments
from ros2launch_gui.launcher.runner import EventWriter


def test_event_writer_never_blocks_on_a_full_pipe():
    read_fd, write_fd = os.pipe()
    writer = EventWriter(os.fdopen(write_fd, 'wb', buffering=0), max_queued_io=100)
    start = time.monotonic()
    for i in range(5000):
        writer.send({'type': 'process_io', 'name': 'chatty-1', 'text': 'x' * 100 + '\n'})
    writer.send({'type': 'process_exited', 'name': 'chatty-1', 'pid': 1, 'return_code': 0})
    assert time.monotonic() - start < 1.0  # nobody reads the pipe, yet send() returned

    received = []
    decoder = LineDecoder()

    def drain():
        while True:
            data = os.read(read_fd, 65536)
            if not data:
                break
            received.extend(decoder.feed(data))

    reader = threading.Thread(target=drain)
    reader.start()
    writer.close(timeout=10)
    reader.join(timeout=10)
    os.close(read_fd)
    types = [m['type'] for m in received]
    assert 'process_exited' in types  # control events are never dropped
    assert 0 < types.count('process_io') <= 5000
    assert any(m['type'] == 'error' and 'dropped' in m['message'] for m in received)


@pytest.fixture
def runners():
    started = []

    def start(launch_file, *arguments):
        runner = RunnerProcess(launch_file, *arguments)
        started.append(runner)
        return runner

    yield start
    for runner in started:
        runner.close()


def _is(event_type, **fields):
    return lambda e: e.get('type') == event_type and all(
        e.get(k) == v for k, v in fields.items())


def test_run_streams_events(tmp_path, runners):
    runner = runners(write_launch_file(tmp_path, 'sleeper.launch.py', SLEEPER_LAUNCH))
    started = runner.wait_for(_is('started'))
    assert started['pid'] == runner.pgid
    proc = runner.wait_for(lambda e: e.get('type') == 'process_started')
    assert proc['name'].startswith('talker')
    assert proc['is_lifecycle'] is False
    runner.wait_for(lambda e: e.get('type') == 'process_io' and 'hello' in e['text'])
    runner.send({'type': 'shutdown'})
    runner.wait_for(_is('process_exited', pid=proc['pid']))
    runner.wait_for(_is('launch_exited'))
    assert runner.process.wait(timeout=15) == 0
    assert wait_group_gone(runner.pgid)


def test_stdin_eof_shuts_down(tmp_path, runners):
    runner = runners(write_launch_file(tmp_path, 'sleeper.launch.py', SLEEPER_LAUNCH))
    runner.wait_for(lambda e: e.get('type') == 'process_started')
    runner.process.stdin.close()
    runner.process.wait(timeout=15)
    assert wait_group_gone(runner.pgid)


def test_launch_arguments_passed(tmp_path, runners):
    path = write_launch_file(tmp_path, 'echo.launch.py', """
        from launch import LaunchDescription
        from launch.actions import DeclareLaunchArgument
        from launch.actions import ExecuteProcess
        from launch.substitutions import LaunchConfiguration


        def generate_launch_description():
            code = ('import sys, time; print("msg=[" + sys.argv[1] + "]", flush=True); '
                    'time.sleep(600)')
            return LaunchDescription([
                DeclareLaunchArgument('msg'),
                ExecuteProcess(cmd=['python3', '-c', code, LaunchConfiguration('msg')],
                               name='echo', output='screen'),
            ])
        """)
    runner = runners(path, 'msg:=a b:=c')
    runner.wait_for(lambda e: e.get('type') == 'process_io' and 'msg=[a b:=c]' in e['text'])
    runner.send({'type': 'shutdown'})
    runner.process.wait(timeout=15)


def test_stop_process_command(tmp_path, runners):
    path = write_launch_file(tmp_path, 'two.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            code = 'import time; time.sleep(600)'
            return LaunchDescription([
                ExecuteProcess(cmd=['python3', '-c', code], name='first'),
                ExecuteProcess(cmd=['python3', '-c', code], name='second'),
            ])
        """)
    runner = runners(path)
    first = runner.wait_for(
        lambda e: e.get('type') == 'process_started' and e['name'].startswith('first'))
    second = runner.wait_for(
        lambda e: e.get('type') == 'process_started' and e['name'].startswith('second'))
    runner.send({'type': 'stop_process', 'pid': first['pid']})
    runner.wait_for(_is('process_exited', pid=first['pid']))
    assert runner.process.poll() is None
    assert not any(e.get('type') == 'process_exited' and e['pid'] == second['pid']
                   for e in runner.events)
    runner.send({'type': 'shutdown'})
    runner.wait_for(_is('process_exited', pid=second['pid']))
    runner.process.wait(timeout=15)


def test_runner_exits_when_processes_finish(tmp_path, runners):
    path = write_launch_file(tmp_path, 'short.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            return LaunchDescription([
                ExecuteProcess(cmd=['python3', '-c', 'import sys; sys.exit(3)'], name='quitter'),
            ])
        """)
    runner = runners(path)
    runner.wait_for(_is('process_exited', return_code=3))
    runner.wait_for(_is('launch_exited'))
    runner.process.wait(timeout=15)
    assert wait_group_gone(runner.pgid)


def test_timer_action_keeps_launch_alive(tmp_path, runners):
    path = write_launch_file(tmp_path, 'timer.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess
        from launch.actions import TimerAction


        def generate_launch_description():
            late = ExecuteProcess(cmd=['python3', '-c', 'import time; time.sleep(600)'],
                                  name='late')
            return LaunchDescription([
                ExecuteProcess(cmd=['true'], name='prep'),
                TimerAction(period=4.0, actions=[late]),
            ])
        """)
    runner = runners(path)
    runner.wait_for(lambda e: e.get('type') == 'process_started' and e['name'].startswith('late'),
                    timeout=15)
    assert runner.process.poll() is None
    runner.send({'type': 'shutdown'})
    runner.process.wait(timeout=15)


def test_respawn_delay_keeps_launch_alive(tmp_path, runners):
    path = write_launch_file(tmp_path, 'respawn.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            return LaunchDescription([
                ExecuteProcess(cmd=['python3', '-c', 'import sys; sys.exit(1)'], name='flaky',
                               respawn=True, respawn_delay=3.0),
            ])
        """)
    runner = runners(path)
    runner.wait_for(lambda e: sum(
        1 for x in runner.events if x.get('type') == 'process_started') >= 2, timeout=15)
    assert runner.process.poll() is None
    runner.send({'type': 'shutdown'})
    runner.process.wait(timeout=15)


def test_launch_without_processes_ends(tmp_path, runners):
    runner = runners(write_launch_file(tmp_path, 'args.launch.py', ARGS_LAUNCH), 'c:=1')
    runner.wait_for(_is('launch_exited'), timeout=15)
    runner.process.wait(timeout=15)


def test_launch_whose_process_fails_to_start_ends(tmp_path, runners):
    path = write_launch_file(tmp_path, 'missing.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            return LaunchDescription([
                ExecuteProcess(cmd=['/nonexistent/binary'], name='ghost'),
            ])
        """)
    runner = runners(path)
    runner.wait_for(_is('launch_exited'), timeout=15)
    runner.process.wait(timeout=15)


def test_empty_argument_value(tmp_path, runners):
    path = write_launch_file(tmp_path, 'echo.launch.py', """
        from launch import LaunchDescription
        from launch.actions import DeclareLaunchArgument
        from launch.actions import ExecuteProcess
        from launch.substitutions import LaunchConfiguration


        def generate_launch_description():
            code = ('import sys, time; print("msg=[" + sys.argv[1] + "]", flush=True); '
                    'time.sleep(600)')
            return LaunchDescription([
                DeclareLaunchArgument('msg', default_value='default'),
                ExecuteProcess(cmd=['python3', '-c', code, LaunchConfiguration('msg')],
                               name='echo', output='screen'),
            ])
        """)
    runner = runners(path, 'msg:=')
    runner.wait_for(lambda e: e.get('type') == 'process_io' and 'msg=[]' in e['text'])
    runner.send({'type': 'shutdown'})
    runner.process.wait(timeout=15)


def test_screen_output_not_duplicated_on_stderr(tmp_path, runners):
    runner = runners(write_launch_file(tmp_path, 'sleeper.launch.py', SLEEPER_LAUNCH))
    runner.wait_for(lambda e: e.get('type') == 'process_io' and 'hello' in e['text'])
    runner.send({'type': 'shutdown'})
    runner.process.wait(timeout=15)
    stderr = runner.stderr()
    assert 'process started' in stderr  # launch's own messages still reach stderr
    # The screen formatter prefixes process output with '[<process name>] '.
    assert '[talker-1] hello' not in stderr


def test_output_split_across_writes_arrives_as_one_line(tmp_path, runners):
    path = write_launch_file(tmp_path, 'split.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            code = ('import sys, time; out = sys.stdout.buffer\\n'
                    'chunks = (b"part-one ", b"\\\\xc3", b"\\\\xa9 part-two\\\\n", b"tail")\\n'
                    'for chunk in chunks:\\n'
                    '    out.write(chunk); out.flush(); time.sleep(0.3)\\n')
            return LaunchDescription([
                ExecuteProcess(cmd=['python3', '-c', code], name='splitter'),
            ])
        """)
    runner = runners(path)
    runner.wait_for(_is('launch_exited'), timeout=20)
    texts = [e['text'] for e in runner.events if e.get('type') == 'process_io']
    assert texts == ['part-one é part-two\n', 'tail']
    exited = next(i for i, e in enumerate(runner.events) if e.get('type') == 'process_exited')
    last_io = max(i for i, e in enumerate(runner.events) if e.get('type') == 'process_io')
    assert last_io < exited


def test_stubborn_process_group_is_gone_after_runner_exit(tmp_path, runners):
    path = write_launch_file(tmp_path, 'stubborn.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            return LaunchDescription([
                ExecuteProcess(cmd=['sh', '-c', 'trap "" INT TERM; sleep 600 & wait'],
                               name='stubborn', sigterm_timeout='1', sigkill_timeout='1'),
            ])
        """)
    runner = runners(path)
    runner.wait_for(lambda e: e.get('type') == 'process_started')
    runner.send({'type': 'shutdown'})
    runner.process.wait(timeout=20)
    assert wait_group_gone(runner.pgid)


def test_describe_arguments(tmp_path):
    path = write_launch_file(tmp_path, 'args.launch.py', ARGS_LAUNCH)
    arguments = {a['name']: a for a in describe_arguments(path)}
    assert list(arguments) == ['a', 'b', 'c']
    assert arguments['a']['default_text'] == '1'
    assert '1' in arguments['a']['default']
    assert arguments['a']['description'] == 'first'
    assert arguments['a']['choices'] is None
    assert arguments['b']['choices'] == ['x', 'y']
    assert arguments['c']['default'] is None
    assert arguments['c']['default_text'] is None
    assert arguments['a']['conditional'] is False


def test_describe_cli_json(tmp_path):
    path = write_launch_file(tmp_path, 'args.launch.py', ARGS_LAUNCH)
    result = run_runner('describe', path)
    assert result.returncode == 0, result.stderr
    names = [a['name'] for a in json.loads(result.stdout)['arguments']]
    assert names == ['a', 'b', 'c']


def test_describe_cli_error(tmp_path):
    path = write_launch_file(tmp_path, 'bad.launch.py', """
        def generate_launch_description():
            raise RuntimeError('boom')
        """)
    result = run_runner('describe', path)
    assert result.returncode == 1
    assert 'boom' in json.loads(result.stdout)['error']
