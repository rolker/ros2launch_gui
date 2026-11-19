"""The launcher window: browse launch files, run several launches, read their logs."""

import argparse
import os
import signal
import sys
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from python_qt_binding.QtCore import QProcess
from python_qt_binding.QtCore import QTimer
from python_qt_binding.QtWidgets import QAction
from python_qt_binding.QtWidgets import QApplication
from python_qt_binding.QtWidgets import QLabel
from python_qt_binding.QtWidgets import QMainWindow
from python_qt_binding.QtWidgets import QMessageBox
from python_qt_binding.QtWidgets import QSplitter
from python_qt_binding.QtWidgets import QStackedWidget

from .discovery import find_launch_files
from .discovery import LaunchFile
from .launch_tree import LaunchTree
from .log_view import LogView
from .session import describe_launch_file
from .session import LaunchSession
from .start_page import display_path
from .start_page import StartPage
from .workspace import LaunchLock
from .workspace import packages_with_prefixes
from .workspace import RecentWorkspaces
from .workspace import source_workspace
from .workspace import Workspace

TITLE = 'ROS 2 Launcher'
# Upper bound on waiting for launches to stop when the window closes; then they are killed.
CLOSE_TIMEOUT = 30.0
MAIN_MODULE = 'ros2launch_gui.launcher.main'


def new_window_command(workspace: Optional[str] = None,
                       include_system: bool = False) -> Tuple[str, List[str]]:
    """Return the program and arguments that start another launcher window."""
    args = [sys.executable, '-m', MAIN_MODULE]
    if workspace:
        args.append(workspace)
    if include_system:
        args.append('--all')
    # Its own session: a Ctrl-C in this launcher's terminal must not close the other window.
    return 'setsid', args


def environment_summary(env: Dict[str, str]) -> str:
    """Describe the ROS settings the launches get."""
    text = 'ROS_DOMAIN_ID={}'.format(env.get('ROS_DOMAIN_ID') or '0 (default)')
    if env.get('ROS_LOCALHOST_ONLY') == '1':
        text += ' · localhost only'
    return text


class LauncherWindow(QMainWindow):
    """
    Launch tree on the left, logs on the right; one LaunchSession per launch file.

    Without launch_files the window opens on the start page and lists the chosen workspace.
    """

    def __init__(self, launch_files: Optional[Dict[str, List[LaunchFile]]] = None,
                 scope: str = '', parent=None, *, settings=None,
                 base_env: Optional[Dict[str, str]] = None, include_system: bool = False,
                 lock_directory: Optional[str] = None):
        super().__init__(parent)
        self.sessions = {}
        self.workspace = None  # type: Optional[Workspace]
        self.include_system = include_system
        self._keys = {}
        self._locks = {}
        self._lock_directory = lock_directory
        self._restart_pending = set()
        self._closing = False
        self._loading = False
        self._base_env = base_env
        self._recent = RecentWorkspaces(settings)

        self.tree = LaunchTree(self)
        self.log_view = LogView(self)
        splitter = QSplitter(self)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.log_view)
        splitter.setSizes([560, 840])
        self.start_page = StartPage(self)
        self.start_page.open_requested.connect(self.open_workspace)
        self._pages = QStackedWidget(self)
        self._pages.addWidget(self.start_page)
        self._pages.addWidget(splitter)
        self.setCentralWidget(self._pages)
        self.environment_label = QLabel(self)
        self.statusBar().addPermanentWidget(self.environment_label)
        self._create_menus()

        self.tree.start_requested.connect(self.start)
        self.tree.stop_requested.connect(self.stop)
        self.tree.restart_requested.connect(self.restart)
        self.tree.describe_requested.connect(self.describe)
        self.tree.source_selected.connect(
            lambda path, name: self.log_view.set_source(
                self._keys.get(path) if path else None, name))
        self.tree.stop_process_requested.connect(
            lambda path, pid: self.sessions[path].stop_process(pid))
        self.tree.lifecycle_requested.connect(
            lambda path, node, transition: self.sessions[path].lifecycle(node, transition))

        if launch_files is None:
            self.setWindowTitle(TITLE)
            self.start_page.set_recent(self._recent.paths())
        else:
            self.setWindowTitle(TITLE + (' — ' + scope if scope else ''))
            self._set_launch_files(launch_files)
            self._pages.setCurrentIndex(1)
        self._update_actions()

    # --- menus -------------------------------------------------------------------------

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu('&File')
        self.open_action = QAction('&Open workspace…', self)
        self.open_action.setShortcut('Ctrl+O')
        self.open_action.triggered.connect(self.start_page.choose_workspace)
        self.new_window_action = QAction('&New window', self)
        self.new_window_action.setShortcut('Ctrl+Shift+N')
        self.new_window_action.triggered.connect(lambda: self.new_window())
        self.reload_action = QAction('&Reload workspace', self)
        self.reload_action.setShortcut('F5')
        self.reload_action.setToolTip(
            'Source the workspace again and re-list its launch files (after a build)')
        self.reload_action.triggered.connect(self.reload)
        quit_action = QAction('&Quit', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.close)
        for action in (self.open_action, self.new_window_action, self.reload_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu('&View')
        self.system_action = QAction('Show &underlay packages (e.g. /opt/ros)', self)
        self.system_action.setCheckable(True)
        self.system_action.setChecked(self.include_system)
        self.system_action.toggled.connect(self.set_include_system)
        view_menu.addAction(self.system_action)

    def _update_actions(self) -> None:
        idle = not self._active_sessions() and not self._loading
        self.reload_action.setEnabled(self.workspace is not None and idle)
        self.system_action.setEnabled(self.workspace is not None and idle)

    def on_start_page(self) -> bool:
        return self._pages.currentIndex() == 0

    # --- workspaces --------------------------------------------------------------------

    def open_workspace(self, path: str) -> None:
        """Source and list a workspace here; a window that has one opens a new window."""
        if self.workspace is not None or self._loading:
            self.new_window(path)
            return
        self._loading = True
        self.start_page.set_busy('Sourcing {} …'.format(display_path(path)))
        source_workspace(path, self._on_sourced, base_env=self._base_env)

    def _on_sourced(self, workspace: Optional[Workspace], error: Optional[str]) -> None:
        self._loading = False
        if workspace is None:
            if self.workspace is None:
                self.start_page.set_error(error)
            else:
                self.statusBar().showMessage('Reload failed: ' + error)
            self._update_actions()
            return
        self.workspace = workspace
        self._recent.add(workspace.root)
        self.setWindowTitle('{} — {} ({})'.format(
            TITLE, os.path.basename(workspace.root), display_path(workspace.root)))
        self.environment_label.setText('{} · {}'.format(
            display_path(workspace.root), environment_summary(workspace.env)))
        self._list_workspace()
        self._pages.setCurrentIndex(1)
        self._update_actions()

    def _list_workspace(self) -> None:
        packages = packages_with_prefixes(self.workspace.env.get('AMENT_PREFIX_PATH', ''))
        self._set_launch_files(
            find_launch_files(packages, [self.workspace.prefix], self.include_system))

    def reload(self) -> None:
        """Source the workspace again and re-list it; refused while a launch runs."""
        if self.workspace is None or self._loading:
            return
        if self._active_sessions():
            self.statusBar().showMessage('Stop the running launches before reloading.', 5000)
            return
        self._loading = True
        self._update_actions()
        self.statusBar().showMessage('Sourcing {} …'.format(display_path(self.workspace.root)))
        previous = self.workspace

        def done(workspace, error):
            if workspace is not None:
                self.workspace = None
            self._on_sourced(workspace, error)
            if workspace is not None:
                self.statusBar().showMessage('Reloaded.', 3000)
            else:
                self.workspace = previous

        source_workspace(previous.root, done, base_env=self._base_env)

    def set_include_system(self, include: bool) -> None:
        if include == self.include_system:
            return
        if self._active_sessions() or self.workspace is None:
            self.system_action.setChecked(self.include_system)
            return
        self.include_system = include
        self._list_workspace()

    def new_window(self, workspace: Optional[str] = None) -> None:
        self.spawn_window(*new_window_command(workspace, self.include_system))

    def spawn_window(self, program: str, args: List[str]) -> None:
        if not QProcess.startDetached(program, args):
            self.statusBar().showMessage('Could not start a new launcher window.', 5000)

    @property
    def environment(self) -> Optional[Dict[str, str]]:
        """Return the environment launches run in; None means this process's own."""
        return self.workspace.env if self.workspace is not None else None

    def _set_launch_files(self, launch_files: Dict[str, List[LaunchFile]]) -> None:
        self.sessions = {}
        self._keys = {}
        for files in launch_files.values():
            for launch_file in files:
                self._keys[launch_file.path] = '{}/{}'.format(
                    launch_file.package, launch_file.name)
        self.tree.set_launch_files(launch_files)
        if not launch_files:
            self.statusBar().showMessage('No launch files found — is the workspace built?')

    # --- launches ----------------------------------------------------------------------

    def _session(self, path: str) -> LaunchSession:
        session = self.sessions.get(path)
        if session is None:
            key = self._keys[path]
            session = LaunchSession(path, self, environment=self.environment)
            session.state_changed.connect(lambda state: self._on_state_changed(path, state))
            session.process_started.connect(
                lambda name, pid, node, lifecycle: self.tree.add_process(
                    path, name, pid, node, lifecycle))
            session.process_output.connect(
                lambda name, text: self.log_view.append(key, name, text))
            session.process_exited.connect(
                lambda name, pid, code: self.tree.process_exited(path, name, code))
            session.state_transition.connect(
                lambda node, start, goal: self.tree.set_lifecycle_state(path, node, goal))
            self.sessions[path] = session
        return session

    def confirm_duplicate(self, path: str, holder: str) -> bool:
        """Ask whether to start a launch another launcher window is already running."""
        answer = QMessageBox.question(
            self, 'Already running',
            '{} is already running in another launcher window{}.\n\n'
            'Starting it again runs a second copy of its nodes. Start anyway?'.format(
                self._keys.get(path, path), ' (pid {})'.format(holder) if holder else ''),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def start(self, path: str) -> None:
        if self._closing:
            return
        session = self._session(path)
        if session.state in ('running', 'stopping'):
            return
        lock = self._locks.get(path) or LaunchLock(path, self._lock_directory)
        if lock.acquire():
            self._locks[path] = lock
        elif not self.confirm_duplicate(path, lock.holder()):
            return
        arguments = self.tree.launch_arguments(path)
        self.tree.clear_processes(path)
        self.log_view.append(self._keys[path], '', '[launcher] starting {}{}'.format(
            self._keys[path], ' ' + ' '.join(arguments) if arguments else ''))
        session.start(arguments)
        self._update_actions()

    def stop(self, path: str) -> None:
        session = self.sessions.get(path)
        if session is not None:
            self._restart_pending.discard(path)
            session.stop()

    def restart(self, path: str) -> None:
        session = self.sessions.get(path)
        if session is not None and session.state == 'running':
            self._restart_pending.add(path)
            session.stop()
        else:
            self.start(path)

    def describe(self, path: str) -> None:
        def done(arguments, error):
            if error is None:
                self.tree.set_arguments(path, arguments)
            else:
                self.tree.set_arguments_error(path, error)

        describe_launch_file(path, done, environment=self.environment)

    def _on_state_changed(self, path: str, state: str) -> None:
        self.tree.set_launch_state(path, state)
        if state in ('stopped', 'failed'):
            lock = self._locks.pop(path, None)
            if lock is not None:
                lock.release()
            self.log_view.append(self._keys[path], '', '[launcher] {} {}'.format(
                self._keys[path], state))
            if path in self._restart_pending:
                self._restart_pending.discard(path)
                self.start(path)
            if self._closing and not self._active_sessions():
                self.close()
        self._update_actions()

    def _active_sessions(self) -> List[LaunchSession]:
        return [s for s in self.sessions.values() if s.state in ('running', 'stopping')]

    def _force_close(self) -> None:
        for session in self._active_sessions():
            session.kill()

    def closeEvent(self, event) -> None:
        active = self._active_sessions()
        if not active:
            event.accept()
            return
        event.ignore()
        if not self._closing:
            self._closing = True
            self._restart_pending.clear()
            self.statusBar().showMessage(
                'Stopping {} launch(es) before closing…'.format(len(active)))
            for session in active:
                session.stop()
            QTimer.singleShot(int(CLOSE_TIMEOUT * 1000), self._force_close)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='ros2 run ros2launch_gui launcher',
        description='Open a workspace, start and stop its launch files, read their logs. '
                    'The launcher sources the workspace itself.')
    parser.add_argument(
        'workspace', nargs='?',
        help='workspace root or install directory to open (default: show the start page)')
    parser.add_argument(
        '--all', action='store_true',
        help='also list the packages of underlay workspaces such as /opt/ros')
    parser.add_argument(
        '--install-desktop-entry', action='store_true',
        help='add "ROS 2 Launcher" to the applications menu and ~/.local/bin/ros2-launcher, '
             'then exit')
    return parser.parse_args(argv)


def install_desktop_entry() -> int:
    from .workspace import launcher_setup_script
    from .workspace import write_desktop_entry
    from .workspace import WorkspaceError

    try:
        setup_script = launcher_setup_script()
    except WorkspaceError as e:
        print(e, file=sys.stderr)
        return 1
    wrapper, desktop = write_desktop_entry(os.path.expanduser('~'), setup_script)
    print('Wrote {} (sources {})'.format(wrapper, setup_script))
    print('Wrote {}'.format(desktop))
    print('Start "ROS 2 Launcher" from the applications menu, or run ros2-launcher.')
    return 0


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.install_desktop_entry:
        return install_desktop_entry()

    app = QApplication(sys.argv[:1])
    app.setApplicationName(TITLE)
    app.setDesktopFileName('ros2-launcher')
    window = LauncherWindow(include_system=args.all)
    window.resize(1400, 800)
    window.show()
    if args.workspace:
        window.open_workspace(args.workspace)

    # Ctrl-C in the terminal closes the window, which stops every launch first.
    signal.signal(signal.SIGINT, lambda *_: window.close())
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # let Python run its signal handlers
    timer.start(200)
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
