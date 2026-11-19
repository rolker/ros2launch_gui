"""Shared helpers for the launcher tests."""

import os
import select
import signal
import subprocess
import sys
import tempfile
import textwrap
import time

import ros2launch_gui
from ros2launch_gui.launcher.protocol import encode
from ros2launch_gui.launcher.protocol import LineDecoder

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(ros2launch_gui.__file__)))
TEST_DOMAIN_ID = '142'


def runner_env():
    """Return an environment that runs this source tree's runner on the test domain."""
    env = dict(os.environ)
    env['PYTHONPATH'] = PACKAGE_ROOT + os.pathsep + env.get('PYTHONPATH', '')
    env['ROS_DOMAIN_ID'] = TEST_DOMAIN_ID
    return env


def run_runner(*args, **kwargs):
    """Run the runner CLI to completion."""
    return subprocess.run(
        [sys.executable, '-m', 'ros2launch_gui.launcher.runner', *args],
        env=runner_env(), capture_output=True, timeout=60, **kwargs)


def write_launch_file(directory, name, body):
    """Write a Python launch file whose generate_launch_description returns body."""
    path = os.path.join(str(directory), name)
    with open(path, 'w') as f:
        f.write(textwrap.dedent(body))
    return path


def group_alive(pgid):
    """Return True while any process is left in the process group."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_group_gone(pgid, timeout=15.0):
    """Wait until the process group is empty; return True if it emptied in time."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not group_alive(pgid):
            return True
        time.sleep(0.1)
    return not group_alive(pgid)


def kill_group(pgid):
    """Kill whatever is left in a process group (test cleanup)."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class RunnerProcess:
    """A runner started in run mode, with helpers to read events and send commands."""

    def __init__(self, launch_file, *arguments):
        self._stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'ros2launch_gui.launcher.runner', 'run', launch_file,
             *arguments],
            env=runner_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._stderr)
        self.pgid = self.process.pid
        self.events = []
        self._decoder = LineDecoder()

    def _read_some(self, timeout):
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        if ready:
            data = os.read(self.process.stdout.fileno(), 65536)
            if data:
                self.events.extend(self._decoder.feed(data))
                return True
        return False

    def wait_for(self, predicate, timeout=30.0):
        """Read events until one satisfies predicate; return it or raise AssertionError."""
        deadline = time.monotonic() + timeout
        checked = 0
        while True:
            for event in self.events[checked:]:
                if predicate(event):
                    return event
            checked = len(self.events)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    'event not seen; events: {}\nstderr: {}'.format(self.events, self.stderr()))
            self._read_some(min(remaining, 0.2))

    def send(self, message):
        self.process.stdin.write(encode(message))
        self.process.stdin.flush()

    def stderr(self):
        self._stderr.seek(0)
        return self._stderr.read().decode('utf-8', errors='replace')

    def close(self):
        kill_group(self.pgid)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self._stderr.close()


SLEEPER_LAUNCH = """
from launch import LaunchDescription
from launch.actions import ExecuteProcess


def generate_launch_description():
    code = 'print("hello", flush=True); import time; time.sleep(600)'
    return LaunchDescription([
        ExecuteProcess(cmd=['python3', '-c', code], name='talker', output='screen'),
    ])
"""

ARGS_LAUNCH = """
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('a', default_value='1', description='first'),
        DeclareLaunchArgument('b', default_value='x', choices=['x', 'y']),
        DeclareLaunchArgument('c'),
    ])
"""


def make_workspace(root, setup_body=None, packages=('pkg',)):
    """Create a built-looking workspace: install/setup.bash and an ament index."""
    install = root / 'install'
    index = install / 'share' / 'ament_index' / 'resource_index' / 'packages'
    index.mkdir(parents=True)
    for package in packages:
        (index / package).write_text('')
        (install / 'share' / package / 'launch').mkdir(parents=True)
    if setup_body is None:
        setup_body = 'export AMENT_PREFIX_PATH="{}${{AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}}"\n' \
                     'export FROM_WORKSPACE=yes\n'.format(install)
    (install / 'setup.bash').write_text(setup_body)
    return root


ENV_LAUNCH = """
from launch import LaunchDescription
from launch.actions import ExecuteProcess


def generate_launch_description():
    return LaunchDescription([
        ExecuteProcess(cmd=['sh', '-c', 'echo FROM_WORKSPACE=$FROM_WORKSPACE'],
                       name='env', output='screen'),
    ])
"""
