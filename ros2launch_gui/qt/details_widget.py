from python_qt_binding.QtWidgets import QPushButton
from python_qt_binding.QtWidgets import QWidget
from python_qt_binding.QtWidgets import QVBoxLayout

from .process_output_widget import ProcessOutputWidget

class DetailsWidget(QWidget):
    """A widget to manage and display detail widgets."""

    def __init__(self, parent=None):
        """Create a DetailsWidget."""
        super().__init__(parent)

        self.all_process_output_widget = ProcessOutputWidget(self)
        self.process_output_widgets = {}

        self.layout = QVBoxLayout()

        show_all_button = QPushButton('Show All Processes')
        show_all_button.clicked.connect(self.show_all_processes_output)
        self.layout.addWidget(show_all_button)

        self.layout.addWidget(self.all_process_output_widget)
        self.current_widget = self.all_process_output_widget

        self.setLayout(self.layout)

    def on_process_started(self, process_name, pid):
        if process_name in self.process_output_widgets:
            process_output_widget = self.process_output_widgets[process_name]
        else:
            process_output_widget = ProcessOutputWidget(self, show_process_name=False)
            self.process_output_widgets[process_name] = process_output_widget
            process_output_widget.hide()
            self.layout.addWidget(process_output_widget)

        process_output_widget.on_process_io(process_name, f'Process {pid} started for {process_name}')

    def on_process_io(self, process_name, text):
        self.all_process_output_widget.on_process_io(process_name, text)
        if process_name in self.process_output_widgets:
            self.process_output_widgets[process_name].on_process_io(process_name, text)

    def show_all_processes_output(self):
        self.current_widget.hide()
        self.current_widget = self.all_process_output_widget
        self.current_widget.show()

    def show_process_output(self, process_name):
        if process_name in self.process_output_widgets:
            self.current_widget.hide()
            self.current_widget = self.process_output_widgets[process_name]
            self.current_widget.show()
