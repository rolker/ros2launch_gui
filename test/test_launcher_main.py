import os
import time

from launcher_helpers import ARGS_LAUNCH
from launcher_helpers import ENV_LAUNCH
from launcher_helpers import kill_group
from launcher_helpers import make_workspace
from launcher_helpers import SLEEPER_LAUNCH
from launcher_helpers import TEST_DOMAIN_ID
from launcher_helpers import wait_group_gone
from launcher_helpers import write_launch_file
import pytest
from python_qt_binding.QtCore import QSettings
from python_qt_binding.QtWidgets import QApplication

from ros2launch_gui.launcher.discovery import LaunchFile
from ros2launch_gui.launcher.main import LauncherWindow
from ros2launch_gui.launcher.main import new_window_command
from ros2launch_gui.launcher.main import parse_args
from ros2launch_gui.launcher.workspace import RecentWorkspaces


@pytest.fixture(scope='module')
def qapp():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['ROS_DOMAIN_ID'] = TEST_DOMAIN_ID
    yield QApplication.instance() or QApplication([])


def spin_until(app, predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    app.processEvents()
    return predicate()


@pytest.fixture
def window(qapp, tmp_path):
    sleeper = write_launch_file(tmp_path, 's.launch.py', SLEEPER_LAUNCH)
    args = write_launch_file(tmp_path, 'args.launch.py', ARGS_LAUNCH)
    win = LauncherWindow({'pkg': [LaunchFile('pkg', sleeper, 'launch/s.launch.py'),
                                  LaunchFile('pkg', args, 'launch/args.launch.py')]},
                         lock_directory=str(tmp_path / 'locks'))
    win.show()
    win.paths = {'sleeper': sleeper, 'args': args}
    yield win
    close_window(win)


def close_window(win):
    for session in win.sessions.values():
        session.kill()
        if session.pgid:
            kill_group(session.pgid)
    win.close()


def test_parse_args():
    args = parse_args([])
    assert args.workspace is None and args.all is False and not args.install_desktop_entry
    args = parse_args(['~/ws', '--all'])
    assert args.workspace == '~/ws' and args.all is True
    assert parse_args(['--install-desktop-entry']).install_desktop_entry


@pytest.fixture
def app_window(qapp, tmp_path):
    """Create windows without a workspace, isolated from the user's settings and bashrc."""
    home = tmp_path / 'home'
    home.mkdir()
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    windows = []

    def create(**kwargs):
        win = LauncherWindow(settings=settings, base_env=dict(os.environ, HOME=str(home)),
                             lock_directory=str(tmp_path / 'locks'), **kwargs)
        win.spawned = []
        win.spawn_window = lambda *args: win.spawned.append(args)
        win.show()
        windows.append(win)
        return win

    create.settings = settings
    yield create
    for win in windows:
        close_window(win)


def built_workspace(tmp_path, name='ws'):
    root = make_workspace(tmp_path / name)
    path = write_launch_file(root / 'install' / 'share' / 'pkg' / 'launch',
                             'env.launch.py', ENV_LAUNCH)
    return root, path


def test_start_page_lists_recent_workspaces(app_window, tmp_path):
    RecentWorkspaces(app_window.settings).add('/ws/old')
    RecentWorkspaces(app_window.settings).add(str(tmp_path))
    win = app_window()
    assert win.on_start_page()
    assert win.start_page.recent_paths() == [str(tmp_path), '/ws/old']
    assert not win.reload_action.isEnabled()


def test_open_workspace_sources_lists_and_launches_with_its_env(qapp, app_window, tmp_path):
    root, path = built_workspace(tmp_path)
    win = app_window()
    win.open_workspace(str(root))
    assert spin_until(qapp, lambda: not win.on_start_page(), 30)
    assert win.tree.launch_item(path) is not None
    assert str(root.name) in win.windowTitle()
    assert 'ROS_DOMAIN_ID=' + TEST_DOMAIN_ID in win.environment_label.text()
    assert RecentWorkspaces(app_window.settings).paths()[0] == str(root)
    assert win.reload_action.isEnabled()

    win.start(path)
    assert spin_until(qapp, lambda: any(
        'FROM_WORKSPACE=yes' in line for line in win.log_view.visible_lines()), 30)
    assert spin_until(qapp, lambda: win.tree.launch_state(path) == 'stopped', 30)


def test_open_unbuilt_workspace_stays_on_start_page(qapp, app_window, tmp_path):
    win = app_window()
    win.open_workspace(str(tmp_path))
    assert spin_until(qapp, lambda: 'build' in win.start_page.message_label.text(), 10)
    assert win.on_start_page()


def test_second_workspace_opens_in_a_new_window(qapp, app_window, tmp_path):
    root, _ = built_workspace(tmp_path)
    win = app_window()
    win.open_workspace(str(root))
    assert spin_until(qapp, lambda: not win.on_start_page(), 30)
    win.open_workspace('/some/other/ws')
    win.new_window()
    assert win.spawned == [new_window_command('/some/other/ws'), new_window_command()]
    assert win.workspace.root == str(root)


def test_new_window_command():
    program, args = new_window_command('/ws', include_system=True)
    assert program == 'setsid'
    assert args[1:] == ['-m', 'ros2launch_gui.launcher.main', '/ws', '--all']
    assert new_window_command()[1][1:] == ['-m', 'ros2launch_gui.launcher.main']


def test_reload_is_refused_while_a_launch_runs(qapp, app_window, tmp_path):
    root, _ = built_workspace(tmp_path)
    sleeper = write_launch_file(root / 'install' / 'share' / 'pkg' / 'launch',
                                's.launch.py', SLEEPER_LAUNCH)
    win = app_window()
    win.open_workspace(str(root))
    assert spin_until(qapp, lambda: not win.on_start_page(), 30)
    win.start(sleeper)
    assert spin_until(qapp, lambda: win.tree.launch_state(sleeper) == 'running', 30)
    assert not win.reload_action.isEnabled()
    win.reload()
    assert win.tree.launch_state(sleeper) == 'running'
    win.stop(sleeper)
    assert spin_until(qapp, lambda: win.tree.launch_state(sleeper) == 'stopped', 30)
    assert win.reload_action.isEnabled()


def test_duplicate_launch_in_another_window_asks_first(qapp, app_window, tmp_path):
    sleeper = write_launch_file(tmp_path, 's.launch.py', SLEEPER_LAUNCH)
    files = {'pkg': [LaunchFile('pkg', sleeper, 'launch/s.launch.py')]}
    first = app_window(launch_files=files)
    second = app_window(launch_files=files)
    asked = []
    second.confirm_duplicate = lambda path, holder: asked.append(holder) or False
    first.start(sleeper)
    assert spin_until(qapp, lambda: first.tree.launch_state(sleeper) == 'running', 30)
    second.start(sleeper)
    assert asked == [str(os.getpid())]
    assert second.tree.launch_state(sleeper) == 'stopped'
    first.stop(sleeper)
    assert spin_until(qapp, lambda: first.tree.launch_state(sleeper) == 'stopped', 30)
    second.start(sleeper)
    assert len(asked) == 1
    assert spin_until(qapp, lambda: second.tree.launch_state(sleeper) == 'running', 30)


def test_window_title(window):
    assert window.windowTitle().startswith('ROS 2 Launcher')


def test_describe_on_expand(qapp, window):
    path = window.paths['args']
    window.tree.launch_item(path).setExpanded(True)
    assert spin_until(qapp, lambda: window.tree.argument_item(path, 'b') is not None, 20)


def test_window_start_restart_close_end_to_end(qapp, window):
    path = window.paths['sleeper']
    tree = window.tree
    tree.trigger_context_action(tree.launch_item(path), 'Start')
    assert spin_until(qapp, lambda: tree.launch_state(path) == 'running' and any(
        'hello' in line for line in window.log_view.visible_lines()))
    assert spin_until(qapp, lambda: tree.process_item(path, 'talker-1') is not None)
    first_pgid = window.sessions[path].pgid

    tree.trigger_context_action(tree.launch_item(path), 'Restart')
    assert spin_until(qapp, lambda: window.sessions[path].pgid != first_pgid
                      and tree.launch_state(path) == 'running', 30)
    assert wait_group_gone(first_pgid)
    second_pgid = window.sessions[path].pgid

    window.close()
    assert spin_until(qapp, lambda: not window.isVisible(), 30)
    assert tree.launch_state(path) == 'stopped'
    assert wait_group_gone(second_pgid)
