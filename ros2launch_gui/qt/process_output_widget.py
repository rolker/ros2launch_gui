
from python_qt_binding.QtWidgets import QTextEdit
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

class ProcessOutputWidget(QWidget):
    """Widget to display output from launch processes."""

    def __init__(self, parent, show_process_name = True):
        """Create a ProcessOutputWidget."""
        super().__init__(parent)

        self.show_process_name = show_process_name

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        self.setLayout(layout)
        self.text_edit.show()


    def on_process_io(self, process_name, text):
        if self.show_process_name:
            self.text_edit.append(f'[{process_name}] {text}')
        else: 
            self.text_edit.append(text)
