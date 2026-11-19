import os
import time

from launcher_helpers import ARGS_LAUNCH
from launcher_helpers import kill_group
from launcher_helpers import SLEEPER_LAUNCH
from launcher_helpers import TEST_DOMAIN_ID
from launcher_helpers import wait_group_gone
from launcher_helpers import write_launch_file
import pytest
from python_qt_binding.QtWidgets import QApplication

from ros2launch_gui.launcher.session import describe_launch_file
from ros2launch_gui.launcher.session import LaunchSession


@pytest.fixture(scope='module')
def qapp():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['ROS_DOMAIN_ID'] = TEST_DOMAIN_ID
    app = QApplication.instance() or QApplication([])
    yield app


def spin_until(app, predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    app.processEvents()
    return predicate()


class Recorder:
    """Collects a session's signals."""

    def __init__(self, session):
        self.states = []
        self.output = []
        self.started = []
        self.exited = []
        session.state_changed.connect(self.states.append)
        session.process_output.connect(lambda name, text: self.output.append((name, text)))
        session.process_started.connect(lambda *a: self.started.append(a))
        session.process_exited.connect(lambda *a: self.exited.append(a))

    def saw_output(self, needle):
        return any(needle in text for _, text in self.output)


@pytest.fixture
def sessions(qapp):
    created = []

    def make(path, **kwargs):
        session = LaunchSession(path, **kwargs)
        created.append(session)
        return session, Recorder(session)

    yield make
    for session in created:
        session.kill()
        if session.pgid:
            kill_group(session.pgid)


def test_start_stop(tmp_path, qapp, sessions):
    session, rec = sessions(write_launch_file(tmp_path, 's.launch.py', SLEEPER_LAUNCH))
    session.start([])
    assert spin_until(qapp, lambda: rec.saw_output('hello'))
    assert session.state == 'running'
    assert rec.started and rec.started[0][0].startswith('talker')
    pgid = session.pgid
    session.stop()
    assert spin_until(qapp, lambda: session.state == 'stopped', 20)
    assert rec.states == ['running', 'stopping', 'stopped']
    assert wait_group_gone(pgid)


def test_launch_ends_by_itself(tmp_path, qapp, sessions):
    path = write_launch_file(tmp_path, 'q.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            return LaunchDescription([
                ExecuteProcess(cmd=['python3', '-c', 'import sys; sys.exit(3)'], name='quitter'),
            ])
        """)
    session, rec = sessions(path)
    session.start([])
    assert spin_until(qapp, lambda: session.state == 'failed', 20)
    session.start([])
    assert spin_until(qapp, lambda: rec.states.count('failed') == 2, 20)
    assert rec.states == ['running', 'failed', 'running', 'failed']


def test_stopping_one_process_is_not_a_failure(tmp_path, qapp, sessions):
    session, rec = sessions(write_launch_file(tmp_path, 's.launch.py', SLEEPER_LAUNCH))
    session.start([])
    assert spin_until(qapp, lambda: rec.started)
    session.stop_process(rec.started[0][1])
    assert spin_until(qapp, lambda: session.state != 'running', 20)
    assert session.state == 'stopped'


def test_stubborn_process_is_killed(tmp_path, qapp, sessions):
    path = write_launch_file(tmp_path, 'stubborn.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            return LaunchDescription([
                ExecuteProcess(cmd=['sh', '-c', 'trap "" INT TERM; sleep 600 & wait'],
                               name='stubborn', sigterm_timeout='60', sigkill_timeout='60'),
            ])
        """)
    session, rec = sessions(path, stop_timeout=3.0)
    session.start([])
    assert spin_until(qapp, lambda: rec.started)
    pgid = session.pgid
    start = time.monotonic()
    session.stop()
    assert spin_until(qapp, lambda: session.state in ('stopped', 'failed'), 15)
    assert time.monotonic() - start < 10
    assert wait_group_gone(pgid, 5)


def test_non_utf8_output(tmp_path, qapp, sessions):
    path = write_launch_file(tmp_path, 'b.launch.py', """
        from launch import LaunchDescription
        from launch.actions import ExecuteProcess


        def generate_launch_description():
            code = ('import sys, time; sys.stdout.buffer.write(b"bad:\\\\xff\\\\n"); '
                    'sys.stdout.flush(); time.sleep(600)')
            return LaunchDescription([
                ExecuteProcess(cmd=['python3', '-c', code], name='binary', output='screen'),
            ])
        """)
    session, rec = sessions(path)
    session.start([])
    assert spin_until(qapp, lambda: rec.saw_output('bad:�'))
    session.stop()
    assert spin_until(qapp, lambda: session.state == 'stopped', 20)


class _FakeProcess:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def readAllStandardError(self):
        return self._chunks.pop(0) if self._chunks else b''


def test_runner_stderr_reassembled_into_lines(qapp):
    session = LaunchSession('/unused.launch.py')
    rec = Recorder(session)
    session._process = _FakeProcess([b'[INFO] [launch]: half', b' line \xc3', b'\xa9\nnext'])
    for _ in range(3):
        session._on_stderr()
    assert rec.output == [('', '[INFO] [launch]: half line é\n')]


def test_describe_async(tmp_path, qapp):
    path = write_launch_file(tmp_path, 'args.launch.py', ARGS_LAUNCH)
    results = []
    describe_launch_file(path, lambda args, error: results.append((args, error)))
    assert spin_until(qapp, lambda: results, 20)
    arguments, error = results[0]
    assert error is None
    assert [a['name'] for a in arguments] == ['a', 'b', 'c']


def test_describe_error(tmp_path, qapp):
    path = write_launch_file(tmp_path, 'bad.launch.py', """
        def generate_launch_description():
            raise RuntimeError('boom')
        """)
    results = []
    describe_launch_file(path, lambda args, error: results.append((args, error)))
    assert spin_until(qapp, lambda: results, 20)
    arguments, error = results[0]
    assert arguments is None
    assert 'boom' in error
