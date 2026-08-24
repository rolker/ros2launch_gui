"""
Headless regression tests for the UI poll loop (issue #30).

Each poll used to leave one Shutdown event handler behind in the launch
context, and the launch service copies the whole handler deque for every event
it processes — so a long session pegged a CPU core and shutdown cost grew
quadratically. These tests run a real LaunchService with a no-op user
interface and assert the steady-state invariant that failure violated: the
registered handler count stays constant while polling.
"""

import threading
import time
import unittest

from launch import LaunchDescription
from launch import LaunchService

from ros2launch_gui.actions import DisplayUserInterface
from ros2launch_gui.api import UserInterface

# Poll rate is the real one: UserInterface.__init__ has no poll-period knob and
# must not grow one to make a test convenient. At 10 Hz a 2.5 s run polls ~25
# times, which is unambiguous against a leak of one handler per poll.
RUN_SECONDS = 2.5
SAMPLE_PERIOD = 0.1
# Samples taken while startup is still registering handlers, discarded.
SETTLE_SAMPLES = 5
# How long after the requested shutdown the watchdog waits before forcing the
# poll chain to stop. Without it a regression hangs the test run instead of
# failing it: the launch service logs an exception raised by an event handler,
# sets return_code = 1 and *continues*, so a poll chain that never learns to
# stop reschedules forever.
WATCHDOG_SECONDS = 5.0


class _HeadlessUserInterface(UserInterface):
    """A UserInterface with no toolkit, optionally raising on teardown."""

    def __init__(self, launch_description, debug=False, close_raises=False):
        super().__init__(launch_description, debug=debug)
        self._close_raises = close_raises
        self.spin_count = 0

    def spin_once(self):
        self.spin_count += 1

    def close(self):
        if self._close_raises:
            # Mimic a backend whose teardown fails before it can reach
            # super().close(), i.e. before the base class would set the flag.
            raise RuntimeError('simulated backend teardown failure')
        super().close()


class _HeadlessRun:
    """Run a LaunchService with a headless UI, sampling the handler count."""

    def __init__(self, close_raises=False, run_seconds=RUN_SECONDS):
        self._close_raises = close_raises
        self._run_seconds = run_seconds
        self.samples = []
        self.ui = None
        self.return_code = None
        self.timed_out = False

    def _launch_ui(self, launch_description, context, debug):
        self.ui = _HeadlessUserInterface(
            launch_description, debug=debug,
            close_raises=self._close_raises)
        return self.ui

    def run(self):
        launch_service = LaunchService()
        launch_service.include_launch_description(
            LaunchDescription([
                DisplayUserInterface(
                    launch_description=LaunchDescription(),
                    ui_launcher=self._launch_ui)
            ]))
        # LaunchService exposes no public accessor for its context; the
        # registered handler deque is what this test is about.
        context = launch_service._LaunchService__context

        finished = threading.Event()

        def sampler():
            deadline = time.monotonic() + self._run_seconds
            while time.monotonic() < deadline:
                time.sleep(SAMPLE_PERIOD)
                self.samples.append(len(context._event_handlers))
            launch_service.shutdown()

        def watchdog():
            if finished.wait(self._run_seconds + WATCHDOG_SECONDS):
                return
            self.timed_out = True
            if self.ui is not None:
                # Force the stop condition the code under test failed to
                # reach, so the test fails instead of hanging forever.
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

        assert not run.timed_out, 'launch service did not shut down in time'
        assert run.return_code == 0, \
            'run() returned {}'.format(run.return_code)
        # Non-vacuous: the invariant only means something if polls happened.
        assert run.ui.spin_count >= 10, \
            'only {} polls observed'.format(run.ui.spin_count)

        steady = run.samples[SETTLE_SAMPLES:]
        assert len(steady) >= 10, 'too few samples: {}'.format(run.samples)
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
