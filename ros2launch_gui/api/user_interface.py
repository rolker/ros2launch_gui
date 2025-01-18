
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

from launch.some_entities_type import SomeEntitiesType


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
        self._pending_actions = [
            RegisterEventHandler(OnUserInterfaceEvent(self, debug)),
            EmitEvent(event=QueryUserInterface()),
            EmitEvent(event=IncludeLaunchDescription(launch_description))
        ]

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

    def on_close(self):
        """Called when the GUI is closed."""
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
        if isinstance(event, ExecutionComplete):
            self.on_execution_complete(DescribedLaunchEntity(event.action, context))
        if isinstance(event, IncludeLaunchDescription):
            self.on_describe_launch_entity(DescribedLaunchEntity(event.launch_description, context))
        return None
