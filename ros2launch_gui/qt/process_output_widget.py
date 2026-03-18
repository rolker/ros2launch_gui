from python_qt_binding.QtWidgets import QPlainTextEdit
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

from ros2launch_gui.ansi import ansi_to_html


class ProcessOutputWidget(QWidget):
    """Widget to display output from launch processes."""

    def __init__(self, parent, show_process_name = True):
        """Create a ProcessOutputWidget."""
        super().__init__(parent)

        self.show_process_name = show_process_name

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        self.setLayout(layout)
        self.text_edit.show()


    def on_process_io(self, process_name, text):
        for line in text.split('\n'):
            line = line.rstrip()
            if line:
                line = ansi_to_html(line)
                if self.show_process_name:
                    self.text_edit.appendHtml(f'[{process_name}] {line}')
                else:
                    self.text_edit.appendHtml(line)
