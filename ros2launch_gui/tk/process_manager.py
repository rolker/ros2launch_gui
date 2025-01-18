from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ros2launch_gui.api.describe import DescribedLaunchEntity

class ProcessList(ttk.Frame):
    """A widget that displays a list of launch processes and their status."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.tree = ttk.Treeview(self, columns=('pid', 'status'))
        self.tree.heading('#0', text='Name')
        self.tree.heading('pid', text='PID')
        self.tree.heading('status', text='Status')
        self.tree.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.tree.column('pid', width=100)
        self.tree.column('status', width=100)

        self.tree_ids = {}


    def get_item_id(self, process_name: str) -> str:
        if not process_name in self.tree_ids:
            self.tree_ids[process_name] = self.tree.insert('', 'end', text=process_name, values=(0, 'unknown'))
        return self.tree_ids[process_name]


    def on_process_started(
            self,
            process_name: str,
            pid: int,
            action: DescribedLaunchEntity
    ) -> None:
        item_id = self.get_item_id(process_name)
        self.tree.item(item_id, values=(pid, 'active'))

    def on_process_exited(
            self,
            process_name: str,
            pid: int,
            action: DescribedLaunchEntity,
            return_code
    ) -> None:
        item_id = self.get_item_id(process_name)
        self.tree.item(item_id, values=(pid, 'exit: {}'.format(return_code)))

class ProcessIOView(ttk.Frame):
    def __init__(self, parent=None, show_process_name: bool = False):
        super().__init__(parent)

        self.text = ScrolledText(self, state='disabled')
        self.text.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.show_process_name = show_process_name


    def on_process_io(self, process_name: str, data: str) -> None:
        self.text.config(state='normal')
        if self.show_process_name:
            for line in data.splitlines():
                self.text.insert('end', '[{}] {}\n'.format(process_name, line.decode()))
        else:
            self.text.insert('end', data)
        #self.text.see('end')
        self.text.config(state='disabled')

class ProcessIONotebook(ttk.Frame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.io_widgets = {}
        self.all = ProcessIOView(self, show_process_name=True)
        self.notebook.add(self.all, text='All')

    def on_select_process(self, process_name: str) -> None:
        if process_name in self.io_widgets:
            self.notebook.select(self.io_widgets[process_name])

    def on_process_io(
            self,
            process_name: str,
            data: str
    ) -> None:
        if process_name in self.io_widgets:
            io_widget = self.io_widgets[process_name]
        else:
            io_widget = ProcessIOView(self)
            self.io_widgets[process_name] = io_widget
            self.notebook.add(io_widget, text=process_name)

        io_widget.on_process_io(process_name, data)
        self.all.on_process_io(process_name, data)

    def on_process_started(
            self,
            process_name: str,
            pid: int,
            action: DescribedLaunchEntity
    ) -> None:
        if process_name in self.io_widgets:
            io_widget = self.io_widgets[process_name]
        else:
            io_widget = ProcessIOView(self)
            self.io_widgets[process_name] = io_widget
            self.notebook.add(io_widget, text=process_name)
        io_widget.on_process_io(process_name, 'Process {} started for action: {}\n'.format(pid, action))

    def on_process_exited(
            self,
            process_name: str,
            pid: int,
            action: DescribedLaunchEntity,
            return_code
    ) -> None:
        if process_name in self.io_widgets:
            io_widget = self.io_widgets[process_name]
            io_widget.on_process_io(process_name, 'Process {} exited with return code: {}\n'.format(pid, return_code))

class ProcessManager(ttk.Frame):
    """A widget that displays a list of launch processes as well as their output in a tabbed display."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.io_notebook = ProcessIONotebook(self)
        self.io_notebook.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def on_select_process(self, process_name: str) -> None:
        self.io_notebook.on_select_process(process_name)

    def on_process_io(
            self,
            process_name: str,
            data: str
    ) -> None:
        self.io_notebook.on_process_io(process_name, data)

    def on_process_started(
            self,
            process_name: str,
            pid: int,
            action: DescribedLaunchEntity
    ) -> None:
        self.io_notebook.on_process_started(process_name, pid, action)

    def on_process_exited(
            self,
            process_name: str,
            pid: int,
            action: DescribedLaunchEntity,
            return_code
    ) -> None:
        self.io_notebook.on_process_exited(process_name, pid, action, return_code)
