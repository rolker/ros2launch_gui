"""Left pane: packages, their launch files, launch arguments and running processes."""

from typing import Dict
from typing import List
from typing import Optional

from python_qt_binding.QtCore import Qt
from python_qt_binding.QtCore import Signal
from python_qt_binding.QtGui import QBrush
from python_qt_binding.QtGui import QColor
from python_qt_binding.QtWidgets import QAbstractItemView
from python_qt_binding.QtWidgets import QComboBox
from python_qt_binding.QtWidgets import QLineEdit
from python_qt_binding.QtWidgets import QMenu
from python_qt_binding.QtWidgets import QTreeWidget
from python_qt_binding.QtWidgets import QTreeWidgetItem
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

from .discovery import LaunchFile
from ..qt.launch_description_widget import LaunchDescriptionWidget

STATE_COLOURS = {
    'stopped': '#9e9e9e',
    'running': '#66bb6a',
    'stopping': '#ffb74d',
    'failed': '#e57373',
}
# Exit codes of a process that was asked to stop (SIGINT, SIGTERM) are not shown as errors.
_CLEAN_EXIT_CODES = (0, -2, -15)

KIND_ROLE = Qt.UserRole
PATH_ROLE = Qt.UserRole + 1
DATA_ROLE = Qt.UserRole + 2

COL_NAME, COL_VALUE, COL_INFO = range(3)


def _initial_value(argument: dict) -> str:
    if argument.get('default_text') is not None:
        return argument['default_text']
    return argument.get('default') or ''


def _argument_info(argument: dict) -> str:
    parts = []
    if argument.get('default') is None:
        parts.append('required')
    else:
        parts.append('default: {}'.format(argument['default']))
    if argument.get('choices'):
        parts.append('choices: {}'.format(' | '.join(argument['choices'])))
    if argument.get('description'):
        parts.append(argument['description'])
    if argument.get('conditional'):
        parts.append('(only used under some conditions)')
    return ' — '.join(parts)


class LaunchTree(QWidget):
    """Tree of launch files with editable arguments, status colours and process control."""

    start_requested = Signal(str)
    stop_requested = Signal(str)
    restart_requested = Signal(str)
    describe_requested = Signal(str)
    source_selected = Signal(object, object)
    stop_process_requested = Signal(str, int)
    lifecycle_requested = Signal(str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._launch_items = {}
        self._launch_files = {}
        self._described = set()

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText('Filter launch files…')
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(['Name', 'Value / Status', 'Info'])
        self.tree.header().resizeSection(COL_NAME, 280)
        self.tree.header().resizeSection(COL_VALUE, 160)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout()
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.tree)
        self.setLayout(layout)

    # -- building --------------------------------------------------------

    def set_launch_files(self, launch_files: Dict[str, List[LaunchFile]]) -> None:
        """Replace the tree with these packages and launch files."""
        self.tree.clear()
        self._launch_items = {}
        self._launch_files = {}
        self._described = set()
        for package in sorted(launch_files):
            package_item = QTreeWidgetItem([package, '', ''])
            package_item.setData(0, KIND_ROLE, 'package')
            self.tree.addTopLevelItem(package_item)
            for launch_file in sorted(launch_files[package], key=lambda f: f.name):
                item = QTreeWidgetItem([launch_file.name, '', launch_file.path])
                item.setData(0, KIND_ROLE, 'launch')
                item.setData(0, PATH_ROLE, launch_file.path)
                item.setToolTip(COL_INFO, launch_file.path)
                package_item.addChild(item)
                arguments_item = QTreeWidgetItem(['Arguments', '', 'expand to read…'])
                arguments_item.setData(0, KIND_ROLE, 'arguments')
                arguments_item.setData(0, PATH_ROLE, launch_file.path)
                item.addChild(arguments_item)
                self._launch_items[launch_file.path] = item
                self._launch_files[launch_file.path] = launch_file
                self.set_launch_state(launch_file.path, 'stopped')
            package_item.setExpanded(True)
        self._apply_filter()

    def launch_item(self, path: str) -> Optional[QTreeWidgetItem]:
        return self._launch_items.get(path)

    def _group(self, path: str, kind: str, create: bool = False):
        item = self._launch_items[path]
        for i in range(item.childCount()):
            if item.child(i).data(0, KIND_ROLE) == kind:
                return item.child(i)
        if not create:
            return None
        group = QTreeWidgetItem(['Processes', '', ''])
        group.setData(0, KIND_ROLE, kind)
        group.setData(0, PATH_ROLE, path)
        item.addChild(group)
        return group

    # -- arguments -------------------------------------------------------

    def set_arguments(self, path: str, arguments: List[dict]) -> None:
        """Show the declared arguments of a launch file."""
        group = self._group(path, 'arguments')
        group.takeChildren()
        group.setText(COL_INFO, '' if arguments else 'no arguments')
        for argument in arguments:
            name = argument['name'] + ('*' if argument.get('conditional') else '')
            item = QTreeWidgetItem([name, _initial_value(argument), _argument_info(argument)])
            item.setData(0, KIND_ROLE, 'argument')
            item.setData(0, PATH_ROLE, path)
            item.setData(0, DATA_ROLE, dict(argument))
            item.setToolTip(COL_INFO, _argument_info(argument))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            group.addChild(item)
            if argument.get('choices'):
                combo = QComboBox()
                combo.setEditable(True)
                combo.addItems(argument['choices'])
                combo.setCurrentText(_initial_value(argument))
                combo.currentTextChanged.connect(lambda text, i=item: i.setText(COL_VALUE, text))
                self.tree.setItemWidget(item, COL_VALUE, combo)
        group.setExpanded(True)

    def set_arguments_error(self, path: str, message: str) -> None:
        """Show that the arguments of a launch file could not be read."""
        group = self._group(path, 'arguments')
        group.takeChildren()
        group.setText(COL_INFO, 'could not read arguments')
        item = QTreeWidgetItem(['error', '', message])
        item.setData(0, KIND_ROLE, 'error')
        item.setData(0, PATH_ROLE, path)
        item.setToolTip(COL_INFO, message)
        item.setForeground(COL_INFO, QBrush(QColor(STATE_COLOURS['failed'])))
        group.addChild(item)
        group.setExpanded(True)

    def _argument_items(self, path: str) -> List[QTreeWidgetItem]:
        group = self._group(path, 'arguments')
        items = [group.child(i) for i in range(group.childCount())]
        return [i for i in items if i.data(0, KIND_ROLE) == 'argument']

    def argument_item(self, path: str, name: str) -> Optional[QTreeWidgetItem]:
        for item in self._argument_items(path):
            if item.data(0, DATA_ROLE)['name'] == name:
                return item
        return None

    def set_argument_value(self, path: str, name: str, value: str) -> None:
        item = self.argument_item(path, name)
        combo = self.tree.itemWidget(item, COL_VALUE)
        if combo is not None:
            combo.setCurrentText(value)
        item.setText(COL_VALUE, value)

    def launch_arguments(self, path: str) -> List[str]:
        """Return 'name:=value' for every argument whose value was changed."""
        result = []
        for item in self._argument_items(path):
            argument = item.data(0, DATA_ROLE)
            value = item.text(COL_VALUE)
            if value != _initial_value(argument):
                result.append('{}:={}'.format(argument['name'], value))
        return result

    def reset_arguments(self, path: str) -> None:
        for item in self._argument_items(path):
            argument = item.data(0, DATA_ROLE)
            self.set_argument_value(path, argument['name'], _initial_value(argument))

    # -- launch and process state ------------------------------------------

    def set_launch_state(self, path: str, state: str) -> None:
        item = self._launch_items[path]
        item.setData(0, DATA_ROLE, state)
        item.setText(COL_VALUE, state)
        item.setBackground(COL_VALUE, QBrush(QColor(STATE_COLOURS.get(state, '#ffffff'))))

    def launch_state(self, path: str) -> str:
        return self._launch_items[path].data(0, DATA_ROLE)

    def add_process(self, path: str, name: str, pid: int, node_name: str,
                    is_lifecycle: bool) -> None:
        group = self._group(path, 'processes', create=True)
        item = self.process_item(path, name)
        if item is None:
            item = QTreeWidgetItem([name, '', ''])
            item.setData(0, KIND_ROLE, 'process')
            item.setData(0, PATH_ROLE, path)
            group.addChild(item)
        item.setData(0, DATA_ROLE, {
            'name': name, 'pid': pid, 'node_name': node_name, 'is_lifecycle': is_lifecycle,
            'lifecycle_state': 'unconfigured' if is_lifecycle else None, 'running': True})
        item.setText(COL_INFO, 'PID {}{}'.format(pid, ', node ' + node_name if node_name else ''))
        self._show_process_status(item)
        group.setExpanded(True)
        self._launch_items[path].setExpanded(True)

    def _show_process_status(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, DATA_ROLE)
        if data['running']:
            text = 'running'
            if data['lifecycle_state']:
                text += ' · ' + data['lifecycle_state']
            colour = STATE_COLOURS['running']
        else:
            text = 'exit: {}'.format(data['return_code'])
            clean = data['return_code'] in _CLEAN_EXIT_CODES
            colour = STATE_COLOURS['stopped' if clean else 'failed']
        item.setText(COL_VALUE, text)
        item.setBackground(COL_VALUE, QBrush(QColor(colour)))

    def process_item(self, path: str, name: str) -> Optional[QTreeWidgetItem]:
        group = self._group(path, 'processes')
        if group is None:
            return None
        for i in range(group.childCount()):
            if group.child(i).text(COL_NAME) == name:
                return group.child(i)
        return None

    def process_exited(self, path: str, name: str, return_code: int) -> None:
        item = self.process_item(path, name)
        if item is None:
            return
        data = item.data(0, DATA_ROLE)
        data.update(running=False, return_code=return_code)
        item.setData(0, DATA_ROLE, data)
        self._show_process_status(item)

    def set_lifecycle_state(self, path: str, node_name: str, state: str) -> None:
        group = self._group(path, 'processes')
        if group is None:
            return
        for i in range(group.childCount()):
            item = group.child(i)
            data = item.data(0, DATA_ROLE)
            if data['node_name'] == node_name and data['is_lifecycle']:
                data['lifecycle_state'] = state
                item.setData(0, DATA_ROLE, data)
                self._show_process_status(item)

    def clear_processes(self, path: str) -> None:
        group = self._group(path, 'processes')
        if group is not None:
            self._launch_items[path].removeChild(group)

    # -- context menu ----------------------------------------------------

    def _context_entries(self, item: QTreeWidgetItem):
        if item is None:
            return []
        kind = item.data(0, KIND_ROLE)
        path = item.data(0, PATH_ROLE)
        if kind == 'launch':
            state = self.launch_state(path)
            entries = []
            if state in ('stopped', 'failed'):
                entries.append(('Start', lambda: self.start_requested.emit(path)))
            if state == 'running':
                entries.append(('Stop', lambda: self.stop_requested.emit(path)))
                entries.append(('Restart', lambda: self.restart_requested.emit(path)))
            entries.append(('Reset arguments', lambda: self.reset_arguments(path)))
            entries.append(('Refresh arguments', lambda: self.describe_requested.emit(path)))
            return entries
        if kind == 'process':
            data = item.data(0, DATA_ROLE)
            if not data['running']:
                return []
            entries = [('Stop ' + data['name'],
                        lambda: self.stop_process_requested.emit(path, data['pid']))]
            if data['is_lifecycle']:
                transitions = LaunchDescriptionWidget.lifecycle_transitions.get(
                    data['lifecycle_state'], ())
                for label, transition_id in transitions:
                    entries.append((
                        '{} {}'.format(label, data['node_name']),
                        lambda t=transition_id: self.lifecycle_requested.emit(
                            path, data['node_name'], t)))
            return entries
        return []

    def context_actions(self, item: QTreeWidgetItem) -> List[str]:
        """Return the labels of the context menu for an item."""
        return [label for label, _ in self._context_entries(item)]

    def trigger_context_action(self, item: QTreeWidgetItem, label: str) -> None:
        for entry_label, callback in self._context_entries(item):
            if entry_label == label:
                callback()
                return
        raise ValueError('No context action {!r}'.format(label))

    def _show_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        entries = self._context_entries(item)
        if not entries:
            return
        menu = QMenu(self)
        for label, callback in entries:
            menu.addAction(label, callback)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    # -- interaction -----------------------------------------------------

    def _on_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, KIND_ROLE) == 'argument' and \
                self.tree.itemWidget(item, COL_VALUE) is None:
            self.tree.editItem(item, COL_VALUE)

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, KIND_ROLE) != 'launch':
            return
        path = item.data(0, PATH_ROLE)
        if path not in self._described:
            self._described.add(path)
            self.describe_requested.emit(path)

    def _on_current_changed(self, current, previous) -> None:
        if current is None:
            return
        kind = current.data(0, KIND_ROLE)
        path = current.data(0, PATH_ROLE)
        if kind == 'process':
            self.source_selected.emit(path, current.text(COL_NAME))
        elif path is not None:
            self.source_selected.emit(path, None)
        else:
            self.source_selected.emit(None, None)

    def _apply_filter(self, *_) -> None:
        needle = self.filter_edit.text().lower()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            package_item = root.child(i)
            package_match = needle in package_item.text(COL_NAME).lower()
            any_visible = False
            for j in range(package_item.childCount()):
                item = package_item.child(j)
                visible = package_match or needle in item.text(COL_NAME).lower()
                item.setHidden(not visible)
                any_visible = any_visible or visible
            package_item.setHidden(not any_visible)
