
from typing import Callable
from typing import List
from typing import Optional

from launch import Action
from launch import LaunchContext
from launch import LaunchDescription
from launch import LaunchDescriptionEntity

from ..api.create_default_user_interface import create_default_user_interface
from ..api import UserInterface

class DisplayUserInterface(Action):
    """Action to display a user interface for the launch system."""
    def __init__(
            self,
            *,
            launch_description: LaunchDescription,
            ui_launcher: Callable[[LaunchDescription, LaunchContext, bool], UserInterface] = create_default_user_interface,
            debug: bool = False
            ):
        super().__init__()
        self._launch_description = launch_description
        self._ui_launcher = ui_launcher
        self._debug = debug

    def execute(self, context) -> Optional[List[LaunchDescriptionEntity]]:
        return self._ui_launcher(self._launch_description, context, self._debug).get_pending_actions()
