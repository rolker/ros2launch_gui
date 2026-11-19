import os

from lifecycle_msgs.msg import Transition
import pytest
from python_qt_binding.QtWidgets import QApplication

from ros2launch_gui.launcher.discovery import LaunchFile
from ros2launch_gui.launcher.launch_tree import LaunchTree

A = '/ws/install/pkg_a/share/pkg_a/launch/world.launch.py'
B = '/ws/install/pkg_a/share/pkg_a/launch/spawn.launch.py'
C = '/ws/install/pkg_b/share/pkg_b/launch/localization_launch.py'

ARGUMENTS = [
    {'name': 'a', 'default': "'1'", 'default_text': '1', 'description': 'first',
     'choices': None, 'conditional': False},
    {'name': 'b', 'default': "'x'", 'default_text': 'x', 'description': '',
     'choices': ['x', 'y'], 'conditional': False},
    {'name': 'c', 'default': None, 'default_text': None, 'description': 'required',
     'choices': None, 'conditional': False},
]


@pytest.fixture(scope='module')
def qapp():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def tree(qapp):
    widget = LaunchTree()
    widget.set_launch_files({
        'pkg_a': [LaunchFile('pkg_a', B, 'launch/spawn.launch.py'),
                  LaunchFile('pkg_a', A, 'launch/world.launch.py')],
        'pkg_b': [LaunchFile('pkg_b', C, 'launch/localization_launch.py')],
    })
    widget.set_arguments(A, ARGUMENTS)
    return widget


def test_lists_packages_and_files(tree):
    top = tree.tree.invisibleRootItem()
    assert [top.child(i).text(0) for i in range(top.childCount())] == ['pkg_a', 'pkg_b']
    pkg_a = top.child(0)
    assert [pkg_a.child(i).text(0) for i in range(pkg_a.childCount())] == [
        'launch/spawn.launch.py', 'launch/world.launch.py']
    assert tree.launch_item(A).text(1) == 'stopped'


def test_filter_hides_non_matching(tree):
    tree.filter_edit.setText('LOCAL')
    assert tree.launch_item(C).isHidden() is False
    assert tree.launch_item(A).isHidden() is True
    assert tree.launch_item(A).parent().isHidden() is True
    tree.filter_edit.setText('pkg_a')
    assert tree.launch_item(A).isHidden() is False
    assert tree.launch_item(C).isHidden() is True
    tree.filter_edit.setText('')
    assert not tree.launch_item(C).isHidden()


def test_expand_requests_describe_once(tree):
    requested = []
    tree.describe_requested.connect(requested.append)
    tree.launch_item(B).setExpanded(True)
    tree.launch_item(B).setExpanded(False)
    tree.launch_item(B).setExpanded(True)
    assert requested == [B]


def test_arguments_shown_with_defaults(tree):
    a = tree.argument_item(A, 'a')
    assert a.text(1) == '1'
    assert 'first' in a.text(2)
    assert 'x | y' in tree.argument_item(A, 'b').text(2)
    assert 'required' in tree.argument_item(A, 'c').text(2)


def test_launch_arguments_only_edited(tree):
    assert tree.launch_arguments(A) == []
    tree.set_argument_value(A, 'a', 'x y')
    assert tree.launch_arguments(A) == ['a:=x y']
    tree.set_argument_value(A, 'b', 'y')
    assert tree.launch_arguments(A) == ['a:=x y', 'b:=y']


def test_launch_arguments_special_values(tree):
    tree.set_argument_value(A, 'a', '')
    tree.set_argument_value(A, 'c', 'k:=v')
    assert tree.launch_arguments(A) == ['a:=', 'c:=k:=v']


def test_reset_arguments(tree):
    tree.set_argument_value(A, 'a', '5')
    tree.set_argument_value(A, 'b', 'y')
    tree.reset_arguments(A)
    assert tree.launch_arguments(A) == []
    assert tree.argument_item(A, 'a').text(1) == '1'


def test_arguments_error_row(tree):
    tree.set_arguments_error(B, 'RuntimeError: boom')
    group = tree.launch_item(B).child(0)
    assert 'boom' in group.child(0).text(2)
    assert tree.launch_arguments(B) == []


def test_context_actions_by_state(tree):
    item = tree.launch_item(A)
    assert 'Start' in tree.context_actions(item)
    assert 'Stop' not in tree.context_actions(item)
    tree.set_launch_state(A, 'running')
    assert tree.launch_item(A).text(1) == 'running'
    assert {'Stop', 'Restart'} <= set(tree.context_actions(item))
    assert 'Start' not in tree.context_actions(item)
    tree.set_launch_state(A, 'failed')
    assert 'Start' in tree.context_actions(item)


def test_context_action_emits(tree):
    started = []
    tree.start_requested.connect(started.append)
    tree.trigger_context_action(tree.launch_item(A), 'Start')
    assert started == [A]


def test_processes_and_selection(tree):
    selected = []
    tree.source_selected.connect(lambda path, name: selected.append((path, name)))
    tree.set_launch_state(A, 'running')
    tree.add_process(A, 'gzserver-1', 101, '', False)
    item = tree.process_item(A, 'gzserver-1')
    assert item.text(1) == 'running'
    assert tree.context_actions(item) == ['Stop gzserver-1']
    stops = []
    tree.stop_process_requested.connect(lambda path, pid: stops.append((path, pid)))
    tree.trigger_context_action(item, 'Stop gzserver-1')
    assert stops == [(A, 101)]
    tree.tree.setCurrentItem(item)
    assert selected[-1] == (A, 'gzserver-1')
    tree.tree.setCurrentItem(tree.launch_item(A))
    assert selected[-1] == (A, None)
    tree.process_exited(A, 'gzserver-1', 1)
    assert item.text(1) == 'exit: 1'
    assert tree.context_actions(item) == []
    tree.clear_processes(A)
    assert tree.process_item(A, 'gzserver-1') is None


def test_lifecycle_actions(tree):
    tree.set_launch_state(C, 'running')
    tree.add_process(C, 'amcl-1', 202, '/amcl', True)
    item = tree.process_item(C, 'amcl-1')
    assert 'Configure /amcl' in tree.context_actions(item)
    tree.set_lifecycle_state(C, '/amcl', 'inactive')
    assert 'inactive' in item.text(1)
    assert 'Activate /amcl' in tree.context_actions(item)
    requests = []
    tree.lifecycle_requested.connect(lambda *a: requests.append(a))
    tree.trigger_context_action(item, 'Activate /amcl')
    assert requests == [(C, '/amcl', Transition.TRANSITION_ACTIVATE)]
