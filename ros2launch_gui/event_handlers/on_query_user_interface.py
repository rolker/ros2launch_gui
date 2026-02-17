from launch.actions import EmitEvent
from launch.actions import TimerAction
from launch.event_handler import BaseEventHandler

from ros2launch_gui.events import QueryUserInterface


class OnQueryUserInterface(BaseEventHandler):
    """Handle QueryUserInterface events to poll the UI and relay pending actions."""

    def __init__(self, ui, period: float = 0.2):
        super().__init__(
            matcher=lambda event: isinstance(event, QueryUserInterface)
        )
        if period <= 0.0:
            raise ValueError('period must be > 0.0')
        self._ui = ui
        self._period = period

    def handle(self, event, context):
        super().handle(event, context)
        if self._ui.close_requested:
            return None
        self._ui.spin_once()
        return [
            TimerAction(
                period=self._period,
                actions=[EmitEvent(event=QueryUserInterface())]
            )
        ] + self._ui.get_pending_actions()
