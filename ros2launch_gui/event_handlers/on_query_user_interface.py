from launch.actions import EmitEvent
from launch.actions import TimerAction
from launch.event_handler import BaseEventHandler

from ros2launch_gui.events import QueryUserInterface


class OnQueryUserInterface(BaseEventHandler):
    """Handle QueryUserInterface events to poll the UI and relay pending actions."""

    def __init__(self, ui, period: float = 0.1):
        super().__init__(
            matcher=lambda event: isinstance(event, QueryUserInterface)
        )
        if period <= 0.0:
            raise ValueError('period must be > 0.0')
        self._ui = ui
        self._period = period

    def handle(self, event, context):
        super().handle(event, context)
        # Two independent stop conditions, and both are load-bearing — do not
        # "simplify" either one away.
        #
        # close_requested is the primary one: UserInterface._on_shutdown sets
        # it before any backend teardown runs, so it covers the ordinary
        # shutdown and a teardown that raises.
        #
        # context.is_shutdown is the belt to that suspenders, because
        # close_requested depends on the UI's own OnShutdown handler actually
        # running, and that is not guaranteed. LaunchService.__process_event
        # iterates the handler deque with no per-handler try, and
        # register_event_handler appends left (newest first), so *any* sibling
        # OnShutdown handler that raises — one in the user launch description
        # this tool exists to display, or ExecuteLocal's per-process handler —
        # aborts dispatch before UserInterface._on_shutdown is reached, leaving
        # close_requested False and this chain rescheduling forever. The launch
        # context's is_shutdown flag is set by LaunchService._shutdown() (which
        # runs on SIGINT, on shutdown(), on idle, and from run_async's
        # catch-all for exactly the raising-handler case), so it does not
        # depend on any event handler completing.
        if self._ui.close_requested or context.is_shutdown:
            return None
        self._ui.spin_once()
        return [
            # cancel_on_shutdown=False is required, not a preference.
            #
            # A fresh TimerAction is constructed on every poll. Upstream
            # TimerAction.execute() sentinel-guards the shared TimerEvent
            # handler it installs, but registers the Shutdown-matching cancel
            # handler *unguarded* whenever cancel_on_shutdown is true (the
            # default). Every poll therefore leaves one more Shutdown handler
            # in the launch context, and LaunchService copies the whole handler
            # deque for every event it processes — so CPU cost grows
            # quadratically with session length. A 30 h session pegged a core
            # throughout and never finished shutting down. This is the only
            # record of that upstream cause; no ros2/launch issue is filed.
            #
            # With the cancel handler gone, what stops this poll chain is the
            # early return above: it declines to schedule the next timer once
            # either UserInterface.close_requested or LaunchContext.is_shutdown
            # is set. See that comment for why both are needed.
            #
            # Consequence: the poll period is now also a floor on shutdown
            # latency — launch waits out the in-flight timer instead of
            # cancelling it (~100 ms at the 10 Hz default). Any future change
            # to the poll rate is a change to shutdown latency; see
            # UserInterface.__init__ where the rate is chosen.
            TimerAction(
                period=self._period,
                actions=[EmitEvent(event=QueryUserInterface())],
                cancel_on_shutdown=False
            )
        ] + self._ui.get_pending_actions()
