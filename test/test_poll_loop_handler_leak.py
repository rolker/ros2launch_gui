"""
Headless regression tests for the UI poll loop (issue #30).

Each poll used to leave one Shutdown event handler behind in the launch
context, and the launch service copies the whole handler deque for every event
it processes — so a long session pegged a CPU core and shutdown cost grew
quadratically. These tests run a real LaunchService with a no-op user
interface and assert the steady-state invariant that failure violated (the
registered handler count stays constant while polling), plus the termination
invariants that removing launch's own timer-cancel path made load-bearing.
"""

import threading
import time
import unittest

from launch import LaunchDescription
from launch import LaunchService
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnShutdown

from ros2launch_gui.actions import DisplayUserInterface
from ros2launch_gui.api import UserInterface

# Poll rate is the real one: UserInterface.__init__ has no poll-period knob and
# must not grow one to make a test convenient. At 10 Hz a fixed 20-sample run
# polls ~25 times, which is unambiguous against a leak of one handler per poll.
SAMPLE_PERIOD = 0.1
# Samples taken while startup is still registering handlers, discarded.
SETTLE_SAMPLES = 5
# Samples the invariant is asserted over. A *count*, not a wall-clock duration:
# a load-sensitive deadline would turn a slow machine into a test failure that
# blames the code under test.
STEADY_SAMPLES = 20
# Upper bound on how long the sampler waits for the launch run loop to come up
# before giving up. shutdown() is a no-op while the service has no run loop, so
# requesting shutdown before then would be silently dropped.
STARTUP_TIMEOUT = 10.0
# How long after the requested shutdown the watchdog waits before forcing the
# poll chain to stop. Without it a regression hangs the test run instead of
# failing it: the launch service logs an exception raised by an event handler,
# sets return_code = 1 and *continues*, so a poll chain that never learns to
# stop reschedules forever.
WATCHDOG_SECONDS = 5.0
# Total sampling budget, used to size the watchdog.
SAMPLING_SECONDS = (SETTLE_SAMPLES + STEADY_SAMPLES) * SAMPLE_PERIOD


def _raise_on_shutdown(event, context):
    """Stand in for a user launch description whose OnShutdown handler fails."""
    raise RuntimeError('simulated sibling OnShutdown failure')


class _HeadlessUserInterface(UserInterface):
    """A UserInterface with no toolkit, optionally raising on teardown."""

    def __init__(self, launch_description, debug=False, close_raises=False,
                 close_after_spins=None):
        super().__init__(launch_description, debug=debug)
        self._close_raises = close_raises
        self._close_after_spins = close_after_spins
        self.spin_count = 0
        self.close_count = 0

    def spin_once(self):
        self.spin_count += 1
        if (self._close_after_spins is not None
                and self.spin_count == self._close_after_spins):
            # The path a real user takes: GUI window close / TUI 'q' calls
            # on_close(), which queues a Shutdown *action* rather than going
            # through LaunchService._shutdown().
            self.on_close()

    def close(self):
        self.close_count += 1
        if self._close_raises:
            # Mimic a backend whose teardown fails before it can reach
            # super().close(), i.e. before the base class would set the flag.
            raise RuntimeError('simulated backend teardown failure')
        super().close()


class _HeadlessRun:
    """Run a LaunchService with a headless UI, sampling the handler count."""

    def __init__(self, close_raises=False, close_after_spins=None,
                 sibling_shutdown_raises=False, shutdown_from_sampler=True,
                 debug=False):
        self._close_raises = close_raises
        self._debug = debug
        self._close_after_spins = close_after_spins
        self._sibling_shutdown_raises = sibling_shutdown_raises
        self._shutdown_from_sampler = shutdown_from_sampler
        self.samples = []
        self.ui = None
        self.return_code = None
        self.timed_out = False
        self.startup_timed_out = False

    def _launch_ui(self, launch_description, context, debug):
        self.ui = _HeadlessUserInterface(
            launch_description, debug=debug,
            close_raises=self._close_raises,
            close_after_spins=self._close_after_spins)
        return self.ui

    def _inner_launch_description(self):
        if not self._sibling_shutdown_raises:
            return LaunchDescription()
        # Registered from the *included* description, i.e. after the UI's own
        # handlers, and register_event_handler appends left — so this handler
        # is dispatched before UserInterface._on_shutdown and, by raising,
        # stops that handler from ever running.
        return LaunchDescription([
            RegisterEventHandler(OnShutdown(on_shutdown=_raise_on_shutdown))
        ])

    def run(self):
        launch_service = LaunchService()
        launch_service.include_launch_description(
            LaunchDescription([
                DisplayUserInterface(
                    launch_description=self._inner_launch_description(),
                    ui_launcher=self._launch_ui,
                    debug=self._debug)
            ]))
        # The registered handler deque is what this test is about.
        context = launch_service.context

        finished = threading.Event()
        live = threading.Event()

        def _wait_for_live_loop():
            """Block until the service is actually processing events."""
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                if finished.is_set():
                    return True
                if self.ui is not None and self.ui.spin_count > 0:
                    live.set()
                    return True
                time.sleep(0.01)
            return False

        def sampler():
            if not _wait_for_live_loop():
                self.startup_timed_out = True
                launch_service.shutdown()
                return
            for _ in range(SETTLE_SAMPLES + STEADY_SAMPLES):
                if finished.is_set():
                    return
                time.sleep(SAMPLE_PERIOD)
                self.samples.append(len(context._event_handlers))
            if self._shutdown_from_sampler:
                launch_service.shutdown()

        def watchdog():
            # Don't start the shutdown budget until the run loop is actually
            # up, so a slow machine costs startup time but not a false
            # timeout — and a real hang still fails within the budget rather
            # than wedging the test run.
            live.wait(STARTUP_TIMEOUT)
            if finished.wait(SAMPLING_SECONDS + WATCHDOG_SECONDS):
                return
            self.timed_out = True
            if self.ui is not None:
                # Force the stop condition the code under test failed to
                # reach, so the test fails instead of hanging forever. This
                # must come *before* launch_service.shutdown() below: that
                # call routes to emit_event -> future.result() with no
                # timeout, which would itself block forever while the poll
                # chain is wedged. Setting the flag first guarantees the run
                # loop drains and the future completes.
                self.ui._close_requested = True
            launch_service.shutdown()

        sampler_thread = threading.Thread(target=sampler, daemon=True)
        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        sampler_thread.start()
        watchdog_thread.start()
        try:
            # LaunchService.run() must be called on the main thread.
            self.return_code = launch_service.run(shutdown_when_idle=False)
        finally:
            finished.set()
        sampler_thread.join(timeout=WATCHDOG_SECONDS)
        watchdog_thread.join(timeout=WATCHDOG_SECONDS)
        return self


class TestPollLoopHandlerLeak(unittest.TestCase):
    """The poll loop must not accumulate event handlers, and must terminate."""

    def test_handler_count_is_constant_while_polling(self):
        run = _HeadlessRun().run()

        assert not run.startup_timed_out, \
            'launch run loop never started polling within {} s'.format(
                STARTUP_TIMEOUT)
        assert not run.timed_out, 'launch service did not shut down in time'
        assert run.return_code == 0, \
            'run() returned {}'.format(run.return_code)
        # Non-vacuous: the invariant only means something if polls happened.
        assert run.ui.spin_count >= 10, \
            'only {} polls observed'.format(run.ui.spin_count)

        steady = run.samples[SETTLE_SAMPLES:]
        assert len(steady) == STEADY_SAMPLES, \
            'sampler collected {} of {} steady samples — the run ended ' \
            'early, so this says nothing about the handler count'.format(
                len(steady), STEADY_SAMPLES)
        assert len(set(steady)) == 1, \
            'handler count grew during polling: {}'.format(run.samples)

    def test_shutdown_completes_when_backend_teardown_raises(self):
        # _on_shutdown sets _close_requested before calling close(), so a
        # raising teardown cannot leave the poll chain rescheduling forever.
        run = _HeadlessRun(close_raises=True).run()

        assert not run.timed_out, \
            'shutdown hung after a raising backend teardown'
        assert run.return_code == 0, \
            'run() returned {}'.format(run.return_code)

    def test_shutdown_completes_when_sibling_shutdown_handler_raises(self):
        # The second termination path. A sibling OnShutdown handler that
        # raises aborts the whole Shutdown dispatch — including
        # UserInterface._on_shutdown — so _close_requested is never set.
        # Only OnQueryUserInterface's context.is_shutdown check stops the
        # loop here.
        run = _HeadlessRun(sibling_shutdown_raises=True).run()

        assert not run.timed_out, \
            'shutdown hung: a sibling OnShutdown handler raised, so ' \
            'UserInterface._on_shutdown never ran and the poll chain kept ' \
            'rescheduling'
        # Launch marks the aborted handler dispatch as an error; the point of
        # this test is that run() returns at all.
        assert run.return_code == 1, \
            'run() returned {}'.format(run.return_code)

    def test_shutdown_completes_via_ui_close_action(self):
        # The path users actually take: on_close() queues a Shutdown *action*,
        # bypassing LaunchService._shutdown(), so LaunchService.__on_shutdown
        # is the only thing that marks the context shut down.
        run = _HeadlessRun(close_after_spins=5,
                           shutdown_from_sampler=False).run()

        assert not run.timed_out, \
            'shutdown hung after the UI requested close'
        assert run.return_code == 0, \
            'run() returned {}'.format(run.return_code)
        assert run.ui.close_requested

    def test_close_is_not_called_twice_on_shutdown(self):
        # _on_shutdown must be re-entrant. In debug mode a raising close() is
        # re-raised, which aborts the Shutdown dispatch before
        # LaunchService.__on_shutdown can set __shutting_down; run_async's
        # catch-all then emits a *second* Shutdown. A backend's teardown is
        # rarely safe to run twice (tk's root.destroy() raises TclError), so
        # the guard must swallow the repeat.
        run = _HeadlessRun(close_raises=True, close_after_spins=5,
                           shutdown_from_sampler=False, debug=True).run()

        assert not run.timed_out, 'shutdown hung in debug mode'
        assert run.ui.close_count == 1, \
            'close() ran {} times, expected exactly 1'.format(
                run.ui.close_count)
