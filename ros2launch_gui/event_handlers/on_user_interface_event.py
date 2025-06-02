from launch.actions import TimerAction
from launch.actions import EmitEvent
from launch.actions import LogInfo
from launch.event_handler import BaseEventHandler
from launch.events import Shutdown
from ros2launch_gui.events import QueryUserInterface

class OnUserInterfaceEvent(BaseEventHandler):
    def __init__(self, ui, debug: bool = False, update_rate: float = 5.0):
        super().__init__(matcher=lambda event: True)
        self._ui = ui
        self._debug = debug
        if update_rate <= 0.0:
            raise ValueError("Update rate must be greater than 0.0")
        self._period = 1.0 / update_rate

    def handle(self, event, context):
        super().handle(event, context)
        if self._ui is None:
            return None
        if isinstance(event, Shutdown):
            self._ui.close()
            self._ui = None
            return None
        if isinstance(event, QueryUserInterface):
            self._ui.spin_once()
            return [TimerAction(
                    period=self._period,
                    actions=[EmitEvent(event=QueryUserInterface())])
            ] + self._ui.get_pending_actions()
        try:
            return self._ui.handle(event, context)
        except Exception as e:
            if self._debug:
                self._ui.close()
                self._ui = None
                raise
            return [LogInfo(msg=f'Exception while ui was handling event: {event.name}, exception: {e}')]
