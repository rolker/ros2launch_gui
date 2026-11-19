"""Find packages and their launch files in a chosen set of workspaces."""

from dataclasses import dataclass
import os
import re
from typing import Dict
from typing import List
from typing import Optional

SYSTEM_PREFIX = '/opt/ros'

# Read at most this much of a candidate file when deciding whether it is a launch file.
_SNIFF_BYTES = 256 * 1024

# ros2launch's own is_launch_file() accepts every .xml/.yaml file, which would list
# package.xml, parameter files and behavior trees, so candidates are checked by content.
_SNIFFERS = {
    '.py': re.compile(r'^\s*def\s+generate_launch_description\s*\(', re.MULTILINE),
    '.xml': re.compile(r'<launch[\s>/]'),
    '.launch': re.compile(r'<launch[\s>/]'),
    '.yaml': re.compile(r'^launch\s*:', re.MULTILINE),
    '.yml': re.compile(r'^launch\s*:', re.MULTILINE),
}


def is_launch_file(path: str) -> bool:
    """Return True if the file's content marks it as a ROS 2 launch file."""
    sniffer = _SNIFFERS.get(os.path.splitext(path)[1])
    if sniffer is None or not os.path.isfile(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            head = f.read(_SNIFF_BYTES)
    except OSError:
        return False
    return sniffer.search(head) is not None


def get_launch_file_paths(path: str) -> List[str]:
    """Return the launch files below a directory."""
    found = []
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if is_launch_file(file_path):
                found.append(file_path)
    return found


@dataclass
class LaunchFile:
    """A launch file installed by a package."""

    package: str
    path: str
    name: str


def resolve_prefixes(workspaces: List[str]) -> List[str]:
    """Map workspace roots to their install directory; keep install prefixes as they are."""
    prefixes = []
    for workspace in workspaces:
        install = os.path.join(workspace, 'install')
        prefixes.append(os.path.realpath(install if os.path.isdir(install) else workspace))
    return prefixes


def _is_under(path: str, prefix: str) -> bool:
    path = os.path.realpath(path)
    prefix = os.path.realpath(prefix)
    return path == prefix or path.startswith(prefix.rstrip(os.sep) + os.sep)


def find_launch_files(
        packages: Dict[str, str],
        prefixes: Optional[List[str]],
        include_system: bool = False
) -> Dict[str, List[LaunchFile]]:
    """
    Return the launch files of the selected packages, keyed by package name.

    :param packages: package name to install prefix, as from
        ament_index_python.get_packages_with_prefixes()
    :param prefixes: keep only packages installed under one of these; None keeps every
        package that is not installed under /opt/ros
    :param include_system: keep every package
    """
    result = {}
    for package in sorted(packages):
        prefix = packages[package]
        if not include_system:
            if prefixes is None:
                if _is_under(prefix, SYSTEM_PREFIX):
                    continue
            elif not any(_is_under(prefix, p) for p in prefixes):
                continue
        share = os.path.join(prefix, 'share', package)
        if not os.path.isdir(share):
            continue
        files = [
            LaunchFile(package=package, path=path, name=os.path.relpath(path, share))
            for path in get_launch_file_paths(share)
        ]
        if files:
            result[package] = sorted(files, key=lambda f: f.name)
    return result
