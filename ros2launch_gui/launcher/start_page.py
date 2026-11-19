"""Start page: choose the workspace this launcher window works on."""

import os
from typing import List

from python_qt_binding.QtCore import Qt
from python_qt_binding.QtCore import Signal
from python_qt_binding.QtWidgets import QFileDialog
from python_qt_binding.QtWidgets import QHBoxLayout
from python_qt_binding.QtWidgets import QLabel
from python_qt_binding.QtWidgets import QListWidget
from python_qt_binding.QtWidgets import QListWidgetItem
from python_qt_binding.QtWidgets import QPushButton
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

PATH_ROLE = Qt.UserRole + 1


def display_path(path: str) -> str:
    """Return path with the home directory shortened to ~."""
    home = os.path.expanduser('~')
    if path == home or path.startswith(home + os.sep):
        return '~' + path[len(home):]
    return path


class StartPage(QWidget):
    """'Open workspace…' and the recently opened workspaces."""

    open_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        title = QLabel('<h2>ROS 2 Launcher</h2>'
                       'Open a workspace to list its launch files. It is sourced for you '
                       '(with your ~/.bashrc, as in a new terminal); it must be built.', self)
        title.setWordWrap(True)
        self.open_button = QPushButton('Open workspace…', self)
        self.open_button.clicked.connect(self.choose_workspace)
        self.recent_list = QListWidget(self)
        self.recent_list.itemActivated.connect(
            lambda item: self.open_requested.emit(item.data(PATH_ROLE)))
        self.message_label = QLabel(self)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addLayout(buttons)
        layout.addWidget(QLabel('Recent workspaces (double-click to open):', self))
        layout.addWidget(self.recent_list, 1)
        layout.addWidget(self.message_label)
        self.setLayout(layout)

    def set_recent(self, paths: List[str]) -> None:
        self.recent_list.clear()
        for path in paths:
            item = QListWidgetItem(display_path(path))
            item.setData(PATH_ROLE, path)
            item.setToolTip(path)
            if not os.path.isdir(path):
                item.setForeground(Qt.gray)
                item.setToolTip(path + ' (missing)')
            self.recent_list.addItem(item)

    def recent_paths(self) -> List[str]:
        return [self.recent_list.item(i).data(PATH_ROLE)
                for i in range(self.recent_list.count())]

    def set_busy(self, message: str) -> None:
        self.message_label.setStyleSheet('')
        self.message_label.setText(message)
        self.open_button.setEnabled(False)
        self.recent_list.setEnabled(False)

    def set_error(self, message: str) -> None:
        self.message_label.setStyleSheet('color: #e57373')
        self.message_label.setText(message)
        self.open_button.setEnabled(True)
        self.recent_list.setEnabled(True)

    def choose_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, 'Open workspace (its root or install directory)', os.path.expanduser('~'))
        if path:
            self.open_requested.emit(path)
