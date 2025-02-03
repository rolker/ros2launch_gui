import asyncio

from python_qt_binding.QtWidgets import QApplication
from python_qt_binding.QtWidgets import QMainWindow
from python_qt_binding.QtWidgets import QSplitter


from ..api import UserInterface as UserInterfaceBase

from launch import LaunchDescription
from launch.actions import OpaqueCoroutine

from .details_widget import DetailsWidget
from .launch_description_widget import LaunchDescriptionWidget


class MainWindow(QMainWindow):
    def __init__(self, ui: 'UserInterface'=None):
        super().__init__()

        self._ui = ui
        self.setWindowTitle("ROS 2 Launch GUI")
        self.launch_description_widget = LaunchDescriptionWidget(ui, self)
        self.details_widget = DetailsWidget(self)

        splitter = QSplitter()
        splitter.addWidget(self.launch_description_widget)
        splitter.addWidget(self.details_widget)


        self.setCentralWidget(splitter)
        self.show()

    def on_process_started(self, action, process_name, pid):
        self.details_widget.on_process_started(process_name, pid)
        self.launch_description_widget.on_entity_process_started(action, process_name, pid, lambda: self.details_widget.show_process_output(process_name))

    def on_process_exited(self, action, process_name, pid, return_code):
        self.details_widget.on_process_exited(process_name, return_code)
        self.launch_description_widget.on_entity_process_exited(action, process_name, pid, return_code)

    def on_process_io(self, process_name, text):
        self.details_widget.on_process_io(process_name, text)

    def on_describe_launch_entity(self, entity):
        self.launch_description_widget.on_describe_launch_entity(entity)

    def on_execution_complete(self, entity):
        self.launch_description_widget.on_execution_complete(entity)

    def closeEvent(self, event):
        if self._ui is not None:
            self._ui.on_close()
        event.accept()

class UserInterface(UserInterfaceBase):
    def __init__(
            self,
            launch_description: LaunchDescription,
            debug: bool = False,
           
    ):
        super().__init__(launch_description, debug)

        self.closing = False

        self.app = QApplication([])
        self.main_window = MainWindow(self)
        self.main_window.resize(1280, 720)
        self.main_window.show()

        self.add_pending_action(OpaqueCoroutine(coroutine=self.run_qt))

    async def run_qt(self, *args, **kwargs):
        while not self.closing:
            self.app.processEvents()
            await asyncio.sleep(0.05)

    def on_process_started(self, process_name, pid, action):
        self.main_window.on_process_started(action, process_name, pid)

    def on_process_exited(self, process_name, pid, action, return_code):
        self.main_window.on_process_exited(action, process_name, pid, return_code)

    def on_process_io(self, process_name, text):
        self.main_window.on_process_io(process_name, text.decode())

    def on_describe_launch_entity(self, entity):
        self.main_window.on_describe_launch_entity(entity)

    def on_execution_complete(self, entity):
        self.main_window.on_execution_complete(entity)

    def on_close(self):
        self.closing = True
        super().on_close()
        
