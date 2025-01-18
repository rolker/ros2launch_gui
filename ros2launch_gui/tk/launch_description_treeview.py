from tkinter import ttk

from ros2launch_gui.api.describe import DescribedLaunchEntity

class LaunchDescriptionTreeview(ttk.Frame):
    """A widget that displays a launch description as a tree."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.tree = ttk.Treeview(self, columns=('name', 'description', 'status'))
        self.tree.heading('#0', text='Launch Entity')
        self.tree.column('#0', width=350, stretch=False)
        self.tree.heading('name', text='Name')
        self.tree.column('name', width=200, stretch=False)
        self.tree.heading('description', text='Description')
        self.tree.heading('status', text='Status')
        self.tree.column('status', width=80, stretch=False)
        self.tree.grid(column=0, row=0, sticky=('N', 'W', 'E', 'S'))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.tree_ids = {}
        self.process_ids = {}

        self.process_selected_callbacks = []

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_item_selected)



    def add_process_selected_callback(self, callback):
        self.process_selected_callbacks.append(callback)

    def on_describe_launch_entity(self, entity: DescribedLaunchEntity) -> None:        
        self.add_launch_entity_to_tree(entity)

    def on_execution_complete(self, entity: DescribedLaunchEntity) -> None:
        self.updated_launch_entity(entity, status='done')

    def on_entity_process_started(self, entity: DescribedLaunchEntity, process_name: str, pid: int) -> None:
        if entity.id in self.tree_ids:
            item_id = self.tree_ids[entity.id]
            self.tree.item(item_id, open=True)
            self.process_ids[process_name] = self.tree.insert(item_id, 'end', text="Process", values=(process_name, 'PID: {}'.format(pid), 'running'))

    def on_entity_process_exited(self, entity: DescribedLaunchEntity, process_name: str, pid: int, return_code) -> None:
        if process_name in self.process_ids:
            item_id = self.process_ids[process_name]
            self.tree.item(item_id, values=(process_name, 'PID: {}'.format(pid), 'exit: {}'.format(return_code)))

    def updated_launch_entity(self, launch_entity: DescribedLaunchEntity, status=None):
        if launch_entity.id in self.tree_ids:
            item_id = self.tree_ids[launch_entity.id]
            status_text = status if status is not None else ''
            self.tree.item(item_id, values=(launch_entity.label, launch_entity.description, status_text))
            if launch_entity.type_name == "IncludeLaunchDescription":
                for child in launch_entity.children:
                    if child.id not in self.tree_ids:
                        self.add_launch_entity_to_tree(child, item_id)
        for child in launch_entity.children:
            self.updated_launch_entity(child)

    def add_launch_entity_to_tree(
        self,
        launch_entity: DescribedLaunchEntity,
        parent='',
        status=None
    ):
        if launch_entity.id in self.tree_ids:
            item_id = self.tree_ids[launch_entity.id]
        else:
            item_id = self.tree.insert(parent, 'end', text=launch_entity.type_name, open=True)
            self.tree_ids[launch_entity.id] = item_id
        status_text = status if status is not None else ''
        self.tree.item(item_id, values=(launch_entity.label, launch_entity.description, status_text))
        for child in launch_entity.children:
            self.add_launch_entity_to_tree(child, item_id)

    def on_tree_item_selected(self, event):
        selected_id = self.tree.selection()[0]
        for name in self.process_ids:
            if selected_id == self.process_ids[name]:
                for callback in self.process_selected_callbacks:
                    callback(name)
                return
