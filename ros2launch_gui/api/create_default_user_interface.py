
from launch import LaunchContext
from launch import LaunchDescription

from ros2launch_gui.api import UserInterface

def create_default_user_interface(
        launch_description: LaunchDescription,
        context: LaunchContext,
        debug: bool = False
) -> UserInterface:
    """Create a ui for monitoring launch events."""

    from ros2launch_gui.qt import UserInterface

    return UserInterface(launch_description, debug=debug)

