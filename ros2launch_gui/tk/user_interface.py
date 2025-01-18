
import asyncio

from tkinter import Tk
from tkinter import ttk

from launch import LaunchDescription
from launch.actions import OpaqueCoroutine

from ..api import DescribedLaunchEntity
from ..api import UserInterface as UserInterfaceBase
from .launch_description_treeview import LaunchDescriptionTreeview
from .process_manager import ProcessManager

class UserInterface(UserInterfaceBase):
    def __init__(
            self,
            launch_description: LaunchDescription,
            debug: bool = False
    ):
        super().__init__(launch_description, debug)
        self.root = Tk()
        self.root.title("ROS 2 Launch GUI")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.closing = False
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        main_window = ttk.PanedWindow(self.root, orient='horizontal')
        main_window.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.launch_description_viewer = LaunchDescriptionTreeview(main_window)
        main_window.add(self.launch_description_viewer, weight=1)

        self.process_manager = ProcessManager(main_window)
        main_window.add(self.process_manager, weight=1)

        self.launch_description_viewer.add_process_selected_callback(self.process_manager.on_select_process)

        self.add_pending_action(OpaqueCoroutine(coroutine=self.run_tk))

    async def run_tk(self, *args, **kwargs):
        while not self.closing:
            self.root.update()
            await asyncio.sleep(0.05)
        self.root.destroy()

    def on_process_started(self, process_name, pid, action):
        if not self.closing:
            self.process_manager.on_process_started(process_name, pid, action)
            self.launch_description_viewer.on_entity_process_started(action, process_name, pid)

    def on_process_exited(self, process_name, pid, action, return_code):
        if not self.closing:
            self.process_manager.on_process_exited(process_name, pid, action, return_code)
            self.launch_description_viewer.on_entity_process_exited(action, process_name, pid, return_code)

    def on_process_io(self, process_name, text):
        if not self.closing:
            self.process_manager.on_process_io(process_name, text)

    def on_describe_launch_entity(self, entity):
        if not self.closing:
            self.launch_description_viewer.on_describe_launch_entity(entity)

    def on_execution_complete(self, entity):
        if not self.closing:
            self.launch_description_viewer.on_execution_complete(entity)

    def on_close(self):
        self.closing = True
        super().on_close()


