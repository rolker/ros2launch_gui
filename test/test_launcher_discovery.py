import os

import pytest

from ros2launch_gui.launcher.discovery import find_launch_files
from ros2launch_gui.launcher.discovery import resolve_prefixes


PY_LAUNCH = 'def generate_launch_description():\n    pass\n'


def _touch(path, content=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


@pytest.fixture
def tree(tmp_path):
    ws = tmp_path / 'ws'
    share_a = ws / 'install' / 'pkg_a' / 'share' / 'pkg_a'
    prefix_a = ws / 'install' / 'pkg_a'
    _touch(str(share_a / 'launch' / 'a.launch.py'), PY_LAUNCH)
    _touch(str(share_a / 'launch' / 'b.launch.xml'), '<?xml version="1.0"?>\n<launch/>\n')
    _touch(str(share_a / 'launch' / 'c_launch.py'), PY_LAUNCH)
    _touch(str(share_a / 'launch' / 'd.launch.yaml'), 'launch:\n- node: {pkg: a, exec: b}\n')
    _touch(str(share_a / 'launch' / 'notes.txt'), 'launch')
    _touch(str(share_a / 'launch' / 'util.py'), 'X = 1\n')
    _touch(str(share_a / 'params' / 'p.yaml'), 'node:\n  ros__parameters: {}\n')
    _touch(str(share_a / 'behavior_trees' / 'bt.xml'), '<root main_tree_to_execute="x"/>\n')
    _touch(str(share_a / 'package.xml'), '<package format="3"></package>\n')
    prefix_empty = ws / 'install' / 'pkg_empty'
    _touch(str(prefix_empty / 'share' / 'pkg_empty' / 'package.xml'), '<package/>\n')
    prefix_sys = tmp_path / 'sys'
    _touch(str(prefix_sys / 'share' / 'pkg_s' / 'launch' / 's.launch.py'), PY_LAUNCH)
    packages = {
        'pkg_a': os.path.realpath(str(prefix_a)),
        'pkg_empty': os.path.realpath(str(prefix_empty)),
        'pkg_s': os.path.realpath(str(prefix_sys)),
    }
    return ws, packages


def test_workspace_root_resolves_to_install(tree):
    ws, _ = tree
    assert resolve_prefixes([str(ws)]) == [os.path.realpath(str(ws / 'install'))]
    install = str(ws / 'install')
    assert resolve_prefixes([install]) == [os.path.realpath(install)]


def test_filters_to_workspace(tree):
    ws, packages = tree
    result = find_launch_files(packages, resolve_prefixes([str(ws)]))
    assert list(result.keys()) == ['pkg_a']
    assert [f.name for f in result['pkg_a']] == [
        'launch/a.launch.py', 'launch/b.launch.xml', 'launch/c_launch.py', 'launch/d.launch.yaml']
    assert all(f.package == 'pkg_a' for f in result['pkg_a'])
    assert all(os.path.isfile(f.path) for f in result['pkg_a'])


def test_default_excludes_opt_ros(tree):
    _, packages = tree
    packages = dict(packages, rclcpp_like='/opt/ros/humble')
    result = find_launch_files(packages, None)
    assert 'rclcpp_like' not in result
    assert set(result.keys()) == {'pkg_a', 'pkg_s'}


def test_include_system(tree, monkeypatch):
    ws, packages = tree
    result = find_launch_files(packages, resolve_prefixes([str(ws)]), include_system=True)
    assert set(result.keys()) == {'pkg_a', 'pkg_s'}


def test_package_without_launch_files_omitted(tree):
    _, packages = tree
    assert 'pkg_empty' not in find_launch_files(packages, None)
