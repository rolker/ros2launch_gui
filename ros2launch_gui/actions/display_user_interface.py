
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
        """
        Create a DisplayUserInterface action.
        
        

        :param launch_description: The launch description to display the user interface for.
        :param ui_launcher: The function to use to create the user interface.
        :param debug: Whether to run the user interface in debug mode.
        """
        super().__init__()
        self._launch_description = launch_description
        self._ui_launcher = ui_launcher
        self._debug = debug
        self._ui = None

    def execute(self, context) -> Optional[List[LaunchDescriptionEntity]]:
        self._ui = self._ui_launcher(self._launch_description, context, self._debug)
        return self._ui.get_pending_actions()
