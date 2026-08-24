import asyncio
import unittest

from launch import LaunchContext
from launch.actions import TimerAction
from launch.events import Shutdown

from ros2launch_gui.event_handlers import OnQueryUserInterface
from ros2launch_gui.events import QueryUserInterface


class _StubUserInterface:
    """Minimal stand-in for UserInterface, recording what the handler calls."""

    def __init__(self, close_requested=False):
        self.close_requested = close_requested
        self.spin_count = 0
        self.pending_actions_calls = 0

    def spin_once(self):
        self.spin_count += 1

    def get_pending_actions(self):
        self.pending_actions_calls += 1
        return []


def _count_shutdown_handlers(action: TimerAction) -> int:
    """
    Execute a TimerAction in isolation and count the Shutdown handlers it left.

    TimerAction.execute() registers a Shutdown-matching cancel handler when
    cancel_on_shutdown is true, and does so unguarded — once per execute().
    That registration is the leak this package works around, so the test
    asserts on the observable result (no Shutdown handler in the context)
    rather than on the private cancel_on_shutdown attribute.
    """
    context = LaunchContext()
    loop = asyncio.new_event_loop()
    try:
        context._set_asyncio_loop(loop)
        action.execute(context)
        shutdown_event = Shutdown()
        count = sum(
            1 for handler in context._event_handlers
            if handler.matches(shutdown_event)
        )
        # Drain the timer task the action started, so the loop closes cleanly.
        action.cancel()
        loop.run_until_complete(action.get_asyncio_future())
    finally:
        loop.close()
    return count


class TestOnQueryUserInterface(unittest.TestCase):
    """Tests for the UI poll event handler."""

    def test_rejects_non_positive_period(self):
        with self.assertRaises(ValueError):
            OnQueryUserInterface(_StubUserInterface(), period=0.0)

    def test_default_period_is_10_hz(self):
        # Must agree with UserInterface.__init__'s non-debug update_rate.
        handler = OnQueryUserInterface(_StubUserInterface())
        assert handler._period == 0.1

    def test_handle_polls_ui_and_reschedules(self):
        ui = _StubUserInterface()
        handler = OnQueryUserInterface(ui, period=0.1)

        result = handler.handle(QueryUserInterface(), LaunchContext())

        assert ui.spin_count == 1
        assert ui.pending_actions_calls == 1
        assert len(result) == 1
        assert isinstance(result[0], TimerAction)

    def test_rescheduled_timer_registers_no_shutdown_handler(self):
        # The regression under test: with cancel_on_shutdown left at its
        # default this count is 1, and one handler leaks per poll.
        ui = _StubUserInterface()
        handler = OnQueryUserInterface(ui, period=0.1)

        result = handler.handle(QueryUserInterface(), LaunchContext())

        assert _count_shutdown_handlers(result[0]) == 0

    def test_handle_stops_when_close_requested(self):
        ui = _StubUserInterface(close_requested=True)
        handler = OnQueryUserInterface(ui, period=0.1)

        result = handler.handle(QueryUserInterface(), LaunchContext())

        assert result is None
        assert ui.spin_count == 0
