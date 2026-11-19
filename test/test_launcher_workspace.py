import os
import stat
import time

from launcher_helpers import make_workspace
import pytest
from python_qt_binding.QtCore import QSettings
from python_qt_binding.QtWidgets import QApplication

from ros2launch_gui.launcher import workspace
from ros2launch_gui.launcher.workspace import ENV_MARKER
from ros2launch_gui.launcher.workspace import find_setup_script
from ros2launch_gui.launcher.workspace import LaunchLock
from ros2launch_gui.launcher.workspace import packages_with_prefixes
from ros2launch_gui.launcher.workspace import parse_env
from ros2launch_gui.launcher.workspace import RecentWorkspaces
from ros2launch_gui.launcher.workspace import source_workspace
from ros2launch_gui.launcher.workspace import WorkspaceError
from ros2launch_gui.launcher.workspace import write_desktop_entry


@pytest.fixture(scope='module')
def qapp():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    yield QApplication.instance() or QApplication([])


def base_env(home):
    """Return the test process environment, with a HOME whose .bashrc we control."""
    env = dict(os.environ)
    env['HOME'] = str(home)
    return env


def wait_for(app, results, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not results and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert results, 'no result before the timeout'
    return results[0]


def test_find_setup_script(tmp_path):
    root = make_workspace(tmp_path / 'ws')
    expected = str(root / 'install' / 'setup.bash')
    assert find_setup_script(str(root)) == expected
    assert find_setup_script(str(root / 'install')) == expected
    assert find_setup_script(str(root) + '/') == expected


def test_find_setup_script_unbuilt(tmp_path):
    (tmp_path / 'src').mkdir()
    with pytest.raises(WorkspaceError, match='build'):
        find_setup_script(str(tmp_path))
    with pytest.raises(WorkspaceError, match='does not exist'):
        find_setup_script(str(tmp_path / 'missing'))


def test_parse_env_skips_shell_output_and_shell_variables():
    out = (b'hello from bashrc\n' + ENV_MARKER +
           b'A=1\0B=x=y\nz\0SHLVL=3\0PWD=/tmp\0_=/usr/bin/env\0EMPTY=\0')
    assert parse_env(out) == {'A': '1', 'B': 'x=y\nz', 'EMPTY': ''}


def test_parse_env_without_marker():
    with pytest.raises(WorkspaceError):
        parse_env(b'A=1\0')


def test_source_workspace_reads_bashrc_and_setup(qapp, tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.bashrc').write_text('echo noise from bashrc\nexport FROM_BASHRC=1\n')
    root = make_workspace(tmp_path / 'ws')
    results = []
    source_workspace(str(root), lambda ws, err: results.append((ws, err)),
                     base_env=base_env(home))
    ws, err = wait_for(qapp, results)
    assert err is None
    assert ws.root == str(root)
    assert ws.prefix == str(root / 'install')
    assert ws.env['FROM_BASHRC'] == '1'
    assert ws.env['FROM_WORKSPACE'] == 'yes'
    assert ws.env['AMENT_PREFIX_PATH'].split(':')[0] == str(root / 'install')


def test_source_workspace_that_does_not_add_its_prefix(qapp, tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    root = make_workspace(tmp_path / 'ws', setup_body='echo broken >&2\nreturn 1\n')
    results = []
    source_workspace(str(root), lambda ws, err: results.append((ws, err)),
                     base_env=base_env(home))
    ws, err = wait_for(qapp, results)
    assert ws is None
    assert 'AMENT_PREFIX_PATH' in err and 'broken' in err


def test_source_workspace_unbuilt_reports_without_blocking(qapp, tmp_path):
    results = []
    source_workspace(str(tmp_path), lambda ws, err: results.append((ws, err)))
    assert results == []  # reported from the event loop, like every other outcome
    ws, err = wait_for(qapp, results)
    assert ws is None and 'build' in err


def test_source_workspace_timeout(qapp, tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    root = make_workspace(tmp_path / 'ws', setup_body='sleep 30\n')
    results = []
    t0 = time.monotonic()
    source_workspace(str(root), lambda ws, err: results.append((ws, err)),
                     base_env=base_env(home), timeout=1.0)
    ws, err = wait_for(qapp, results)
    assert ws is None and 'timed out' in err
    assert time.monotonic() - t0 < 10


def test_packages_with_prefixes_first_prefix_wins(tmp_path):
    overlay = make_workspace(tmp_path / 'overlay', packages=('a', 'b')) / 'install'
    underlay = make_workspace(tmp_path / 'underlay', packages=('b', 'c')) / 'install'
    found = packages_with_prefixes(
        os.pathsep.join([str(overlay), str(tmp_path / 'missing'), str(underlay)]))
    assert found == {'a': str(overlay), 'b': str(overlay), 'c': str(underlay)}
    assert packages_with_prefixes('') == {}


def test_recent_workspaces(tmp_path, monkeypatch):
    path = str(tmp_path / 'recent.ini')
    monkeypatch.setattr(workspace, 'MAX_RECENT', 3)
    recent = RecentWorkspaces(QSettings(path, QSettings.IniFormat))
    assert recent.paths() == []
    for name in ('a', 'b', 'c', 'b', 'd'):
        recent.add('/ws/' + name)
    assert recent.paths() == ['/ws/d', '/ws/b', '/ws/c']
    # Another launcher instance sees the same list.
    other = RecentWorkspaces(QSettings(path, QSettings.IniFormat))
    assert other.paths() == ['/ws/d', '/ws/b', '/ws/c']
    other.remove('/ws/b')
    assert RecentWorkspaces(QSettings(path, QSettings.IniFormat)).paths() == ['/ws/d', '/ws/c']


def test_launch_lock_is_exclusive(tmp_path):
    first = LaunchLock('/ws/install/pkg/share/pkg/launch/a.launch.py', str(tmp_path))
    second = LaunchLock('/ws/install/pkg/share/pkg/launch/a.launch.py', str(tmp_path))
    other = LaunchLock('/ws/install/pkg/share/pkg/launch/b.launch.py', str(tmp_path))
    assert first.acquire()
    assert not second.acquire()
    assert second.holder() == str(os.getpid())
    assert other.acquire()
    first.release()
    assert second.acquire()
    second.release()
    other.release()


def test_write_desktop_entry(tmp_path):
    setup = tmp_path / 'install' / 'setup.bash'
    setup.parent.mkdir()
    setup.write_text('')
    wrapper, desktop = write_desktop_entry(str(tmp_path / 'home'), str(setup))
    assert wrapper == str(tmp_path / 'home' / '.local' / 'bin' / 'ros2-launcher')
    assert os.stat(wrapper).st_mode & stat.S_IXUSR
    text = open(wrapper).read()
    assert text.startswith('#!/bin/bash\n')
    assert "source '{}'".format(setup) in text
    assert 'exec python3 -m ros2launch_gui.launcher.main "$@"' in text
    entry = open(desktop).read()
    assert desktop.endswith('/.local/share/applications/ros2-launcher.desktop')
    assert 'Exec={} %f'.format(wrapper) in entry
    assert 'Name=ROS 2 Launcher' in entry and 'Terminal=false' in entry
