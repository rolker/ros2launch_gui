import signal

from typing import Callable

from python_qt_binding.QtCore import Qt
from python_qt_binding.QtGui import QBrush
from python_qt_binding.QtGui import QColor
from python_qt_binding.QtWidgets import QCheckBox
from python_qt_binding.QtWidgets import QMenu
from python_qt_binding.QtWidgets import QTreeWidgetItem
from python_qt_binding.QtWidgets import QTreeWidget
from python_qt_binding.QtWidgets import QVBoxLayout
from python_qt_binding.QtWidgets import QWidget

from launch.actions import EmitEvent
from launch.events.process import SignalProcess
from launch.events.process.process_matchers import matches_pid
from launch_ros.events.lifecycle import ChangeState
from launch_ros.events import matches_node_name
from ros2launch_gui.api.describe import DescribedLaunchEntity

from lifecycle_msgs.msg import Transition


class LaunchDescriptionWidget(QWidget):
    """
    A widget that displays a launch description as a tree.
    
    The tree is updated when the launch is executed showing the status of processes.
    """

    DetailsCallbackRole = Qt.UserRole
    ContextMenuRole = Qt.UserRole + 1


    lifecycle_transitions = {
        'unconfigured': (
            ('Configure', Transition.TRANSITION_CONFIGURE),
            ('Shutdown', Transition.TRANSITION_UNCONFIGURED_SHUTDOWN)
        ),
        'inactive': (
            ('Activate', Transition.TRANSITION_ACTIVATE),
            ('Shutdown', Transition.TRANSITION_INACTIVE_SHUTDOWN),
            ('Cleanup', Transition.TRANSITION_CLEANUP)
        ),
        'active': (
            ('Deactivate', Transition.TRANSITION_DEACTIVATE),
            ('Shutdown', Transition.TRANSITION_ACTIVE_SHUTDOWN)
        ),
    }

    tree_types = ('simple', 'detailed')

    def __init__(self, ui, parent=None):
        super().__init__(parent)
        self._ui = ui

        self.show_detailed_configuration_checkbox = QCheckBox('Show Detailed Configuration', self)

        self.trees = {}
        for tree_type in self.tree_types:
            self.trees[tree_type] = self.create_tree_widget()
            self.trees[tree_type].setObjectName(tree_type + '_tree')
            self.trees[tree_type].setVisible(False)


        self.show_detailed_configuration_checkbox.stateChanged.connect(self.show_detailed_configuration_checkbox_state_changed)
        self.show_detailed_configuration_checkbox.setChecked(False)


        layout = QVBoxLayout()
        layout.addWidget(self.show_detailed_configuration_checkbox)
        for tree_type in self.tree_types:
            layout.addWidget(self.trees[tree_type])
        self.trees['simple'].show()

        self.setLayout(layout)

        self.entity_items = {}
        self.process_items = {}
        self.launch_arguments_items = {}
        self.entity_condition_items = {}

    def create_tree_widget(self):
        tree = QTreeWidget(self)
        tree.setHeaderLabels(['Launch Entity', 'Status', 'Name', 'Description'])
        tree.header().resizeSection(0, 200)
        tree.header().resizeSection(1, 150)
        tree.header().resizeSection(2, 275)

        tree.itemActivated.connect(self.on_item_selected)
        tree.itemClicked.connect(self.on_item_selected)
        tree.currentItemChanged.connect(self.on_item_selected)

        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(lambda pos: self.show_context_menu(pos, tree))
        return tree

    def show_detailed_configuration_checkbox_state_changed(self, state):
        if state == Qt.Checked:
            self.trees['simple'].hide()
            self.trees['detailed'].show()
        else:
            self.trees['detailed'].hide()
            self.trees['simple'].show()


    def on_item_selected(self, item, column):
        if item is not None:
            selected_callback = item.data(0, self.DetailsCallbackRole)
            if selected_callback is not None:
                selected_callback()

    def on_describe_launch_entity(self, entity: DescribedLaunchEntity) -> None:
        self.add_launch_entity_to_trees(entity)
        for tree_type in self.tree_types:
            self.trees[tree_type].expandAll()

    def on_execution_complete(self, entity: DescribedLaunchEntity) -> None:
        self.updated_launch_entity(entity, status='done')

    def on_entity_process_started(
            self,
            entity: DescribedLaunchEntity,
            process_name: str,
            pid: int,
            selected_callback=None
    ) -> None:
        if process_name in self.process_items:
            process_items = self.process_items[process_name]
        else:
            process_items = {}
            for item_label in self.tree_types:
                process_items[item_label] = QTreeWidgetItem(['Process', 'running', process_name, f'PID: {pid}'])
            self.process_items[process_name] = process_items
        if entity.id in self.entity_items:
            items = self.entity_items[entity.id]
            for tree_type in self.tree_types:
                item = items[tree_type]
                if item is not None:
                    item.addChild(process_items[tree_type])
                    item.setExpanded(True)
                    item.setData(0, self.DetailsCallbackRole, selected_callback)

            if entity.type_name == "LifecycleNode":
                self.on_state_transition(entity, 'unknown', 'unconfigured')
        else:
            for tree_type in self.tree_types:
                self.trees[tree_type].addTopLevelItem(process_items[tree_type])

        for tree_type in self.tree_types:
            process_items[tree_type].setText(1, 'running')
            process_items[tree_type].setText(3, f'PID: {pid}')
            process_items[tree_type].setData(0, self.DetailsCallbackRole, selected_callback)
            process_items[tree_type].setData(1, Qt.BackgroundRole, QBrush(QColor(150, 255, 100)))
            process_items[tree_type].setData(
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

    def get_lifecycle_menu_items(self, menu: QMenu, node_name: str, current_state: str) -> None:
        for label, transition_id in self.lifecycle_transitions[current_state]:
            menu.addAction(
                f'{label} {node_name}',
                lambda id=transition_id: self._ui.add_pending_action(
                    EmitEvent(
                        event=ChangeState(
                            lifecycle_node_matcher=matches_node_name(node_name),
                            transition_id=id
                        )
                    )
                )
            )


    def on_entity_process_exited(self, entity: DescribedLaunchEntity, process_name: str, pid: int, return_code) -> None:
        if process_name in self.process_items:
            items = self.process_items[process_name]
            for tree_type in self.tree_types:
                item = items[tree_type]
                item.setText(1, f'exit: {return_code}')
                if return_code == 0:
                    item.setData(1, Qt.BackgroundRole, QBrush(QColor(200, 255, 200)))
                else:
                    item.setData(1, Qt.BackgroundRole, QBrush(QColor(255, 128, 128)))
                item.setData(0, self.ContextMenuRole, None)

    def updated_launch_entity(self, launch_entity: DescribedLaunchEntity, status=None):
        if launch_entity.condition is not None:
            if launch_entity.id in self.entity_condition_items:
                item = self.entity_condition_items[launch_entity.id]
                item.setText(2, launch_entity.condition)
        if launch_entity.id in self.entity_items:
            items = self.entity_items[launch_entity.id]
            for tree_type in self.tree_types:
                item = items[tree_type]
                if item is not None:
                    item.setText(2, launch_entity.label)
                    item.setText(3, str(launch_entity.description))
                    if status is not None:
                        item.setText(1, status)
                if launch_entity.type_name == "IncludeLaunchDescription":
                    for child in launch_entity.children:
                        if child.id not in self.entity_items:
                            self.add_launch_entity_to_trees(child, launch_entity)
        for child in launch_entity.children:
            self.updated_launch_entity(child)

    def on_state_transition(self, entity: DescribedLaunchEntity, start_state: str, goal_state: str) -> None:
        if entity.id in self.entity_items:
            items = self.entity_items[entity.id]
            for tree_type in self.tree_types:
                item = items[tree_type]
                if item is not None:
                    item.setText(1, f'{goal_state}')
                    if goal_state == 'active':
                        item.setData(1, Qt.BackgroundRole, QBrush(QColor(100, 255, 150)))
                    else:
                        item.setData(1, Qt.BackgroundRole, QBrush(QColor(255, 255, 150)))
                    if goal_state in self.lifecycle_transitions:
                        item.setData(0, self.ContextMenuRole, lambda menu: self.get_lifecycle_menu_items(menu, entity.label, goal_state))
                    else:
                        item.setData(0, self.ContextMenuRole, None)





    def add_launch_entity_to_trees(
        self,
        launch_entity: DescribedLaunchEntity,
        parent: DescribedLaunchEntity=None,
        status=None
    ):
        if launch_entity.id in self.entity_items:
            items = self.entity_items[launch_entity.id]
            if status is not None:
                for tree_type in self.tree_types:
                    item = items[tree_type]
                    item.setText(1, status)
        else:
            items = {}
            for tree_type in self.tree_types:
                if tree_type != "simple" or launch_entity.type_name in ("Node", "LifecycleNode"):

                    status_text = status if status is not None else ''
                    item = QTreeWidgetItem([launch_entity.type_name, status_text, launch_entity.label, str(launch_entity.description), status])
                    parent_item = None
                    expand_parent = True
                    if parent is not None:
                        if parent.id in self.entity_items:
                            parent_item = self.entity_items[parent.id][tree_type]
                            if parent_item is not None:
                                if launch_entity.type_name == "DeclareLaunchArgument":
                                    if not parent.id in self.launch_arguments_items:
                                        self.launch_arguments_items[parent.id] = QTreeWidgetItem(['Launch Arguments', '', '', ''])
                                        parent_item.addChild(self.launch_arguments_items[parent.id])
                                    parent_item = self.launch_arguments_items[parent.id]
                                    expand_parent = False
                    if tree_type == 'detailed':
                        if launch_entity.condition is not None:
                            if launch_entity.id in self.entity_condition_items:
                                condition_item = self.entity_condition_items[launch_entity.id]
                            else:
                                condition_item = QTreeWidgetItem(['Condition', '', launch_entity.condition, ''])
                                self.entity_condition_items[launch_entity.id] = condition_item
                                if parent_item is not None:
                                    parent_item.addChild(condition_item)
                                    parent_item.setExpanded(True)
                                else:
                                    self.trees[tree_type].addTopLevelItem(condition_item)
                            parent_item = condition_item
                    if parent_item is not None:
                        parent_item.addChild(item)
                        if expand_parent:
                            parent_item.setExpanded(True)
                    else:
                        self.trees[tree_type].addTopLevelItem(item)
                    item.setExpanded(True)
                    items[tree_type] = item
                    self.update_lifecycle_callbacks(launch_entity, item, status)
                else:
                    items[tree_type] = None

            self.entity_items[launch_entity.id] = items
            

        for child in launch_entity.children:
            self.add_launch_entity_to_trees(child, launch_entity)
        for condition, sub_entities in launch_entity.conditional_children:
            for sub_entity in sub_entities:
                self.add_launch_entity_to_trees(sub_entity, launch_entity)

    def update_lifecycle_callbacks(
        self,
        launch_entity: DescribedLaunchEntity,
        item: QTreeWidgetItem,
        status: str
    ):
        if launch_entity.type_name == "LifecycleNode":
            item.setData(1, Qt.BackgroundRole, QBrush(QColor(255, 255, 150)))
            if status is None:
                # assuming lifecycle node is unconfigured until we know otherwise
                status = 'unconfigured'
            if status in self.lifecycle_transitions:
                item.setData(0, self.ContextMenuRole, lambda menu: self.get_lifecycle_menu_items(menu, launch_entity.label, status))
        

    def show_context_menu(self, pos, tree):
        item = tree.itemAt(pos)
        if item is not None:
            context_menu_callback = item.data(0, self.ContextMenuRole)
            if context_menu_callback is not None:
                menu = QMenu(self)
                context_menu_callback(menu)
                menu.exec_(tree.mapToGlobal(pos))

