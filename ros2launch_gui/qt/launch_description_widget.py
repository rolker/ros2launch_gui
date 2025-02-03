import signal

from python_qt_binding.QtCore import Qt
from python_qt_binding.QtGui import QBrush
from python_qt_binding.QtGui import QColor
from python_qt_binding.QtWidgets import QMenu
from python_qt_binding.QtWidgets import QTreeWidgetItem
from python_qt_binding.QtWidgets import QTreeWidget
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

from launch.actions import EmitEvent
from launch.events.process import SignalProcess
from launch.events.process.process_matchers import matches_pid
from ros2launch_gui.api.describe import DescribedLaunchEntity

class LaunchDescriptionWidget(QWidget):
    """
    A widget that displays a launch description as a tree.
    
    The tree is updated when the launch is executed showing the status of processes.
    """

    DetailsCallbackRole = Qt.UserRole
    ContextMenuRole = Qt.UserRole + 1

    def __init__(self, ui, parent=None):
        super().__init__(parent)

        self._ui = ui
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(['Launch Entity', 'Name', 'Description', 'Status'])
        self.tree.header().resizeSection(0, 350)
        self.tree.header().resizeSection(1, 200)
        self.tree.header().resizeSection(2, 450)

        self.tree.itemActivated.connect(self.on_item_selected)
        self.tree.itemClicked.connect(self.on_item_selected)
        self.tree.currentItemChanged.connect(self.on_item_selected)

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        layout = QVBoxLayout()
        layout.addWidget(self.tree)
        self.setLayout(layout)

        self.entity_items = {}
        self.process_items = {}


    def on_item_selected(self, item, column):
        if item is not None:
            selected_callback = item.data(0, self.DetailsCallbackRole)
            if selected_callback is not None:
                selected_callback()

    def on_describe_launch_entity(self, entity: DescribedLaunchEntity) -> None:
        self.add_launch_entity_to_tree(entity)
        self.tree.expandAll()

    def on_execution_complete(self, entity: DescribedLaunchEntity) -> None:
        self.updated_launch_entity(entity, status='done')

    def on_entity_process_started(
            self,
            entity: DescribedLaunchEntity,
            process_name: str,
            pid: int,
            selected_callback=None
    ) -> None:
        if entity.id in self.entity_items:
            item = self.entity_items[entity.id]
            process_item = QTreeWidgetItem(item, ['Process', process_name, f'PID: {pid}', 'running'])
            self.process_items[process_name] = process_item
            process_item.setData(0, self.DetailsCallbackRole, selected_callback)
            item.setExpanded(True)
            process_item.setData(3, Qt.BackgroundRole, QBrush(QColor(100, 255, 100)))
            process_item.setData(
                0,
                self.ContextMenuRole,
                lambda menu: menu.addAction(
                    f'Stop {process_name}',
                    lambda: self._ui.add_pending_action(
                        EmitEvent(
                            event=SignalProcess(
                                signal_number= signal.SIGINT,
                                process_matcher=matches_pid(pid)
                            )
                        )
                    )
                )
            )

    def on_entity_process_exited(self, entity: DescribedLaunchEntity, process_name: str, pid: int, return_code) -> None:
        if process_name in self.process_items:
            item = self.process_items[process_name]
            item.setText(3, f'exit: {return_code}')
            if return_code == 0:
                item.setData(3, Qt.BackgroundRole, QBrush(QColor(200, 255, 200)))
            else:
                item.setData(3, Qt.BackgroundRole, QBrush(QColor(255, 128, 128)))
            item.setData(0, self.ContextMenuRole, None)

    def updated_launch_entity(self, launch_entity: DescribedLaunchEntity, status=None):
        if launch_entity.id in self.entity_items:
            item = self.entity_items[launch_entity.id]
            item.setText(1, launch_entity.label)
            item.setText(2, str(launch_entity.description))
            status_text = status if status is not None else ''
            item.setText(3, status_text)
            if launch_entity.type_name == "IncludeLaunchDescription":
                for child in launch_entity.children:
                    if child.id not in self.entity_items:
                        self.add_launch_entity_to_tree(child, item)
        for child in launch_entity.children:
            self.updated_launch_entity(child)

    def add_launch_entity_to_tree(
        self,
        launch_entity: DescribedLaunchEntity,
        parent=None,
        status=None
    ):
        if launch_entity.id in self.entity_items:
            item = self.entity_items[launch_entity.id]
        else:
            item = QTreeWidgetItem([launch_entity.type_name, launch_entity.label, str(launch_entity.description), status])
            if parent is not None:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            item.setExpanded(True)
            self.entity_items[launch_entity.id] = item
            
        status_text = status if status is not None else ''
        item.setText(3, status_text)

        for child in launch_entity.children:
            self.add_launch_entity_to_tree(child, item)

    def show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is not None:
            context_menu_callback = item.data(0, self.ContextMenuRole)
            if context_menu_callback is not None:
                menu = QMenu(self)
                menu.addAction(f'Process {item.text(1)}')
                menu.addSeparator()
                context_menu_callback(menu)
                menu.exec_(self.tree.mapToGlobal(pos))
