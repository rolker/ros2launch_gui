from launch.actions import EmitEvent
from launch.actions import TimerAction
from launch.event_handler import BaseEventHandler
from launch.logging import get_logger

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
        # shutdown and a teardown that raises. On that route the UI has
        # already been torn down, so there is nothing to do but decline to
        # reschedule.
        if self._ui.close_requested:
            return None

        # context.is_shutdown is the belt to that suspenders, because
        # close_requested depends on the UI's own OnShutdown handler actually
        # running, and that is not guaranteed. LaunchService.__process_event
        # iterates the handler deque with no per-handler try, and
        # register_event_handler appends left (newest first), so *any* sibling
        # OnShutdown handler that raises — one in the user launch description
        # this tool exists to display, or ExecuteLocal's per-process handler —
        # aborts dispatch before UserInterface._on_shutdown is reached, leaving
        # close_requested False.
        #
        # Where is_shutdown comes from depends on the route, and only one of
        # the two is handler-independent:
        #   * SIGINT, LaunchService.shutdown(), shutdown-when-idle and
        #     run_async's catch-all all reach LaunchService._shutdown(), which
        #     calls context._set_is_shutdown(True) unconditionally, outside
        #     its `if not self.__shutting_down` guard. No handler has to run.
        #   * A launch.actions.Shutdown — what UserInterface.on_close() queues,
        #     i.e. the route a user takes — never calls _shutdown(). There the
        #     flag is set by LaunchService.__on_shutdown, which *is* an event
        #     handler; if a sibling raise aborts that dispatch too, the
        #     exception reaches run_async's catch-all, which calls _shutdown()
        #     on the next iteration. The flag always arrives, but by that
        #     second mechanism rather than directly.
        #
        # Reaching here means _on_shutdown did not run, so nothing has torn
        # the UI down — and close() is the only thing that stops urwid's
        # MainLoop or destroys the tk root. Skipping it leaves the operator a
        # terminal in raw mode, exit code 1 and no message. Tear down here.
        # This handler gets at most one dispatch after the flag is set (it
        # declines to reschedule, so no further QueryUserInterface is emitted),
        # and close() sets close_requested, so the re-entry guard in
        # _on_shutdown covers any later Shutdown dispatch. Log rather than
        # re-raise even under debug: a raise from here would abort the
        # QueryUserInterface dispatch inside launch without telling the
        # operator anything close() has not already failed to say.
        if context.is_shutdown:
            try:
                self._ui.close()
            except Exception as e:
                get_logger('ros2launch_gui').error(
                    'Exception closing UI on shutdown: {}'.format(e))
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
            # early returns above: they decline to schedule the next timer once
            # either UserInterface.close_requested or LaunchContext.is_shutdown
            # is set. See those comments for why both are needed.
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
