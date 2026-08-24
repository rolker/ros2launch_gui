from typing import List

from launch import LaunchDescription
from launch import LaunchDescriptionEntity
from launch.actions import EmitEvent
from launch.actions import LogInfo
from launch.actions import RegisterEventHandler
from launch.actions import Shutdown
from launch.event_handler import BaseEventHandler
from launch.event_handlers import OnExecutionComplete
from launch.event_handlers import OnProcessExit
from launch.event_handlers import OnProcessStart
from launch.event_handlers import OnShutdown
from launch.events import IncludeLaunchDescription
from launch.events.process import ProcessIO
from launch.logging import get_logger

from launch_ros.events.lifecycle import StateTransition

from .describe import DescribedLaunchEntity
from ..event_handlers import OnQueryUserInterface
from ..events import QueryUserInterface


class _TargetedEventHandler(BaseEventHandler):
    """Route a single event type to a callback."""

    def __init__(self, event_cls, callback):
        super().__init__(
            matcher=lambda event: isinstance(event, event_cls)
        )
        self._callback = callback

    def handle(self, event, context):
        super().handle(event, context)
        return self._callback(event, context)


class UserInterface:
    """Base class for a launch system user interface."""

    def __init__(
            self,
            launch_description: LaunchDescription,
            debug: bool = False
    ):
        self._debug = debug
        self._close_requested = False

        # This rate is also a floor on shutdown latency. The UI poll timer
        # runs with cancel_on_shutdown=False (see OnQueryUserInterface.handle
        # for why), so launch waits out the in-flight timer rather than
        # cancelling it: shutdown takes up to one period (~100 ms at 10 Hz,
        # 200 ms on the 5 Hz debug path). Lowering the rate slows shutdown by
        # the same amount.
        update_rate = 5.0 if debug else 10.0
        period = 1.0 / update_rate

        self._pending_actions = [
            # Targeted event handlers
            RegisterEventHandler(
                OnProcessStart(
                    on_start=self._on_process_started)),
            RegisterEventHandler(
                OnProcessExit(
                    on_exit=self._on_process_exited)),
            RegisterEventHandler(
                OnExecutionComplete(
                    on_completion=self._on_execution_complete)),
            RegisterEventHandler(
                OnShutdown(
                    on_shutdown=self._on_shutdown)),
            RegisterEventHandler(
                _TargetedEventHandler(
                    ProcessIO, self._on_process_io)),
            RegisterEventHandler(
                _TargetedEventHandler(
                    IncludeLaunchDescription,
                    self._on_include_launch_description)),
            RegisterEventHandler(
                _TargetedEventHandler(
                    StateTransition,
                    self._on_state_transition)),
            # UI polling timer
            RegisterEventHandler(
                OnQueryUserInterface(self, period=period)),
            # Kick off
            EmitEvent(event=QueryUserInterface()),
            EmitEvent(
                event=IncludeLaunchDescription(launch_description))
        ]

    # -- safe callback wrapper ------------------------------------------

    def _safe_callback(self, fn, event, context):
        if self._close_requested:
            return None
        try:
            fn(event, context)
        except Exception as e:
            if self._debug:
                self.close()
                raise
            return [
                LogInfo(
                    msg='Exception in UI for '
                        '{}: {}'.format(event.name, e))
            ]
        return None

    # -- per-event handler methods --------------------------------------

    def _on_process_started(self, event, context):
        return self._safe_callback(
            lambda ev, ctx: self.on_process_started(
                ev.process_name, ev.pid,
                DescribedLaunchEntity(ev.action, ctx)),
            event, context)

    def _on_process_exited(self, event, context):
        return self._safe_callback(
            lambda ev, ctx: self.on_process_exited(
                ev.process_name, ev.pid,
                DescribedLaunchEntity(ev.action, ctx),
                ev.returncode),
            event, context)

    def _on_process_io(self, event, context):
        return self._safe_callback(
            lambda ev, ctx: self.on_process_io(
                ev.process_name, ev.text),
            event, context)

    def _on_include_launch_description(self, event, context):
        return self._safe_callback(
            lambda ev, ctx: self.on_describe_launch_entity(
                DescribedLaunchEntity(
                    ev.launch_description, ctx)),
            event, context)

    def _on_execution_complete(self, event, context):
        return self._safe_callback(
            lambda ev, ctx: self.on_execution_complete(
                DescribedLaunchEntity(ev.action, ctx)),
            event, context)

    def _on_state_transition(self, event, context):
        return self._safe_callback(
            lambda ev, ctx: self.on_state_transition(
                DescribedLaunchEntity(ev.action, ctx),
                ev.start_state, ev.goal_state),
            event, context)

    def _on_shutdown(self, event, context):
        # Re-entry guard, matching _safe_callback's. Launch can deliver
        # Shutdown to this handler more than once: if any OnShutdown handler
        # raises, LaunchService.__process_event aborts before reaching
        # LaunchService.__on_shutdown, so __shutting_down is never set and
        # run_async's catch-all emits a second Shutdown. Backend teardown is
        # rarely safe to run twice (a second tk root.destroy() raises
        # TclError), so the repeat must be swallowed here.
        if self._close_requested:
            return None

        # Set the flag *before* tearing anything down. It is one of the two
        # things that stop the UI poll chain (OnQueryUserInterface.handle
        # returns None once it is set), and the poll timer is no longer
        # cancelled by launch, so a backend close() that raises before
        # reaching super().close() would otherwise leave the loop
        # rescheduling.
        #
        # Setting it first is also what lets the Qt backend's
        # close() -> main_window.close() -> closeEvent -> on_close() path
        # avoid re-emitting Shutdown.
        self._close_requested = True
        try:
            self.close()
        except Exception as e:
            # Re-raising under _debug does not merely get logged: launch's
            # __process_event has no per-handler try, so the raise aborts the
            # remaining Shutdown handlers (including
            # LaunchService.__on_shutdown, registered first and therefore last
            # in the deque), skips the matching context._pop_locals(), and
            # leaves run() returning 1. That is acceptable in debug mode —
            # surfacing the failure is the point — and termination is
            # unaffected because _close_requested is already set above and
            # OnQueryUserInterface also stops on context.is_shutdown.
            if self._debug:
                raise
            # Error level, not LogInfo: a failed teardown means the window is
            # still up or the terminal is still in raw mode, which the user
            # has to know about even though the exit code stays 0.
            get_logger('ros2launch_gui').error(
                'Exception closing UI on shutdown: {}'.format(e))
            return None
        return None

    # -- public interface -----------------------------------------------

    def spin_once(self) -> None:
        """Process a single iteration of the GUI event loop."""
        raise NotImplementedError(
            'Subclasses must implement spin_once()')

    def close(self) -> None:
        """Request the GUI to close."""
        self._close_requested = True

    @property
    def close_requested(self) -> bool:
        """Check if the GUI has been requested to close."""
        return self._close_requested

    def get_pending_actions(self) -> List[LaunchDescriptionEntity]:
        """Return and clear pending actions for the launch system."""
        actions = self._pending_actions
        self._pending_actions = []
        return actions

    def add_pending_action(
            self, action: LaunchDescriptionEntity) -> None:
        """Add an action to be sent to the launch system."""
        self._pending_actions.append(action)

    def on_process_started(
            self, process_name: str,
            pid: int,
            action: DescribedLaunchEntity) -> None:
        """Display a process start event in the GUI."""
        pass

    def on_process_exited(
            self, process_name: str,
            pid: int,
            action: DescribedLaunchEntity,
            return_code) -> None:
        """Display a process exit event in the GUI."""
        pass

    def on_process_io(
            self, process_name: str, text: str) -> None:
        """Display process output in the GUI."""
        pass

    def on_describe_launch_entity(
            self, entity: DescribedLaunchEntity) -> None:
        """Display a description of a launch entity in the GUI."""
        pass

    def on_execution_complete(
            self, entity: DescribedLaunchEntity) -> None:
        """Display a completion event in the GUI."""
        pass

    def on_state_transition(
            self, entity: DescribedLaunchEntity,
            start_state: str,
            goal_state: str) -> None:
        """Display a state transition in the GUI."""
        pass

    def on_close(self):
        """Handle GUI close by requesting launch shutdown."""
        # only shutdown the launch if close was requested from the gui
        if not self.close_requested:
            self.add_pending_action(Shutdown())
