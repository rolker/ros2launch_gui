from launch.actions import TimerAction
from launch.actions import EmitEvent
from launch.actions import LogInfo
from launch.event_handler import BaseEventHandler
from ros2launch_gui.events import QueryUserInterface

class OnUserInterfaceEvent(BaseEventHandler):
    def __init__(self, ui, debug: bool = False):
        super().__init__(matcher=lambda event: True)
        self._ui = ui
        self._debug = debug

    def handle(self, event, context):
        super().handle(event, context)
        if self._ui.close_requested:
            return None
        if isinstance(event, QueryUserInterface):
            return [TimerAction(
                    period=0.5,
                    actions=[EmitEvent(event=QueryUserInterface())])
            ] + self._ui.get_pending_actions()
        try:
            return self._ui.handle(event, context)
        except Exception as e:
            if self._debug:
                self._ui.close()
                raise
            return [LogInfo(msg=f'Exception while ui was handling event: {event.name}, exception: {e}')]
