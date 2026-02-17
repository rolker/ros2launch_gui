
from typing import List
from typing import Optional

from launch import Event
from launch import LaunchContext
from launch import LaunchDescription
from launch import LaunchDescriptionEntity

from launch.actions import EmitEvent
from launch.actions import RegisterEventHandler
from launch.actions import Shutdown

from launch.events import ExecutionComplete
from launch.events import IncludeLaunchDescription

from launch.events.process import ProcessStarted
from launch.events.process import ProcessExited
from launch.events.process import ProcessIO
from launch.events.process import RunningProcessEvent

import os

# Get ROS distro
__installed_distro = os.environ.get("ROS_DISTRO", "").lower()

if __installed_distro in ["humble", "galactic", "foxy"]:
    # Get some_action_type for older distributions
    from launch.some_actions_type import SomeActionsType as SomeEntitiesType
else:
    from launch.some_entities_type import SomeEntitiesType

from launch_ros.events.lifecycle import ChangeState
from launch_ros.events.lifecycle import StateTransition

from .describe import DescribedLaunchEntity

from ..event_handlers import OnUserInterfaceEvent
from ..events import QueryUserInterface

class UserInterface:
    """Base class for a launch system user interface"""

    def __init__(
            self,
            launch_description: LaunchDescription,
            debug: bool = False
    ):
        
        if debug:
            ui_handler = OnUserInterfaceEvent(self, debug=True, update_rate=1.0)
        else:
            ui_handler = OnUserInterfaceEvent(self)
        self._pending_actions = [
            RegisterEventHandler(ui_handler),
            EmitEvent(event=QueryUserInterface()),
            EmitEvent(event=IncludeLaunchDescription(launch_description))
        ]
        self._close_requested = False

    def spin_once(self) -> None:
        """Process a single iteration of the GUI event loop."""
        # This method should be overridden by subclasses to implement the GUI event loop
        raise NotImplementedError("Subclasses must implement spin_once()")

    def close(self) -> None:
        """Request the GUI to close."""
        self._close_requested = True

    @property
    def close_requested(self) -> bool:
        """Check if the GUI has been requested to close."""
        return self._close_requested

    def get_pending_actions(self) -> List[LaunchDescriptionEntity]:
        actions = self._pending_actions
        self._pending_actions = []
        return actions
    
    def add_pending_action(self, action: LaunchDescriptionEntity) -> None:
        self._pending_actions.append(action)

    def on_process_started(self, process_name: str, pid: int, action: DescribedLaunchEntity) -> None:
        """Display a process start event in the GUI."""
        pass

    def on_process_exited(self, process_name: str, pid: int, action: DescribedLaunchEntity, return_code) -> None:
        """Display a process exit event in the GUI."""
        pass

    def on_process_io(self, process_name: str, text: str) -> None:
        """Display process output in the GUI."""
        pass

    def on_describe_launch_entity(self, entity: DescribedLaunchEntity) -> None:
        """Display a description of a launch entity in the GUI."""
        pass

    def on_execution_complete(self, entity: DescribedLaunchEntity) -> None:
        """Display a completion event in the GUI."""
        pass

    def on_state_transition(self, entity: DescribedLaunchEntity, start_state: str, goal_state: str) -> None:
        """Display a state transition in the GUI."""
        pass

    def on_close(self):
        """Called when the GUI is closed."""
        # only shutdown the launch if close was requested from the gui
        if not self.close_requested:
            self.add_pending_action(Shutdown())

    def handle(self, event: Event, context: LaunchContext) -> Optional[SomeEntitiesType]:
        """Handle a launch event."""
        if isinstance(event, RunningProcessEvent):
            if isinstance(event, ProcessStarted):
                self.on_process_started(event.process_name, event.pid, DescribedLaunchEntity(event.action, context))
            elif isinstance(event, ProcessExited):
                self.on_process_exited(event.process_name, event.pid, DescribedLaunchEntity(event.action, context), event.returncode)
            elif isinstance(event, ProcessIO):
                self.on_process_io(event.process_name, event.text)
        elif isinstance(event, ExecutionComplete):
            self.on_execution_complete(DescribedLaunchEntity(event.action, context))
        elif isinstance(event, IncludeLaunchDescription):
            self.on_describe_launch_entity(DescribedLaunchEntity(event.launch_description, context))
        elif isinstance(event, StateTransition):
            self.on_state_transition(
                DescribedLaunchEntity(event.action, context),
                event.start_state,
                event.goal_state
            )
        return None
