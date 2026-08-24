# Plan: `ros2 launch -g` leaks one Shutdown event handler per UI poll — shutdown cost grows quadratically with session length

## Issue

https://github.com/rolker/ros2launch_gui/issues/30

## Context

`OnQueryUserInterface.handle()` returns a fresh `TimerAction` on every UI poll
(`event_handlers/on_query_user_interface.py:26`). Upstream
`launch/actions/timer_action.py:197-220` sentinel-guards the shared `TimerEvent`
handler but registers the `Shutdown`-matching cancel handler **unguarded**
whenever `cancel_on_shutdown` is true (the default). So each poll permanently
adds one handler to the launch context, and every subsequent event scans the
whole list — cost grows quadratically with session length. Measured with
`.agent/scratchpad/ros2launch_gui_timer_leak_test.py`: handlers track polls 1:1;
shutdown 0.053 s @15 s → 2.855 s @120 s, fitted exponent 2.01. A 30 h session
pegged a core throughout and never finished shutting down.

`on_query_user_interface.py:26` is the only `TimerAction` in the repo, so passing
`cancel_on_shutdown=False` there is a complete fix. Shutdown then depends on
`handle()` returning `None` once `close_requested` is set — which makes that flag
load-bearing, and it is not currently fail-safe (see step 3).

**Architecture is unchanged.** The launch-driven poll loop exists so the UI can
return actions to the launch system through the handler's return value
(`[TimerAction(...)] + self._ui.get_pending_actions()`); a Qt-side timer cannot do
that. Replacing the loop is out of scope.

**Operator decisions already settled** (recorded here so review does not relitigate):
Q1 both secondary items land in this PR and the rate goes to 10 Hz in both places;
Q2 upstream cause is recorded as a local code comment only — no `ros2/launch`
report, no tracking item; Q3 both test forms; Q4 harden `_close_requested` here.

## Approach

1. **Stop the leak** — `on_query_user_interface.py`: pass `cancel_on_shutdown=False`
   to the `TimerAction`, with a call-site comment stating (a) the upstream cause
   (unguarded `Shutdown` handler registration in `TimerAction.execute()`), (b) that
   `close_requested` is now what stops the loop, and (c) that the poll period is
   therefore also a floor on shutdown latency. The comment is the only record of
   the upstream bug — no upstream issue is filed (Q2).
2. **Align the poll rate at 10 Hz in both places** (Q1) — `OnQueryUserInterface.__init__`
   default `period: float = 0.2` → `0.1`, and `UserInterface.__init__`
   (`api/user_interface.py:49`) non-debug `update_rate = 20.0` → `10.0`, so the
   default and the value actually passed agree. The debug rate stays `5.0`: it is
   already slower than the new default and its 200 ms shutdown floor is acceptable
   for a debug session — noting the floor is the reason to revisit it, not to change
   it blind.
3. **Make `_close_requested` fail-safe** (Q4) — `UserInterface._on_shutdown` is not
   wrapped by `_safe_callback`, and today the flag is set only by the subclass
   reaching `super().close()`. With `cancel_on_shutdown=False` a backend whose
   teardown raises first turns a cosmetic bug into a shutdown **hang**. Set
   `self._close_requested = True` in `_on_shutdown` **before** calling
   `self.close()`, and guard the `close()` call so a raising teardown is reported,
   not propagated: re-raise when `self._debug`, otherwise return a `LogInfo`
   matching `_safe_callback`'s style. Setting the flag first is also correct for the
   Qt backend, whose `close()` → `closeEvent` → `on_close()` path checks
   `close_requested` to avoid re-emitting `Shutdown`. Base `close()` keeps setting
   the flag (idempotent); the three backends keep calling `super().close()` first.
4. **Unit test** (`test/test_on_query_user_interface.py`) — with a stub UI:
   `handle()` returns a `TimerAction` carrying `cancel_on_shutdown=False`, and
   returns `None` once `close_requested` is set (asserting `spin_once()` was not
   called). Reading `cancel_on_shutdown` requires the launch-private
   `_TimerAction__cancel_on_shutdown` attribute — isolate that in one commented
   helper so the coupling is visible and has a single fix site.
5. **Headless `LaunchService` regression test** (`test/test_poll_loop_handler_leak.py`,
   ~2-3 s) — the test that would actually have caught this. Register a headless
   `UserInterface` subclass (no-op `spin_once`) at a fast poll period, run
   `LaunchService.run(shutdown_when_idle=False)` on the main thread with a helper
   thread that samples `len(context._event_handlers)` repeatedly and then calls
   `shutdown()`. Assert the handler count is **constant** across samples after
   startup settles (steady-state symptom = the pegged core), and that `run()`
   returns. Assert counts, not wall-clock timings — CI-stable. Add a second case
   where the subclass's `close()` raises before `super().close()`, asserting
   shutdown still completes (step 3's guarantee).
6. **README** — the "Design" paragraph (line 39) documents the `TimerAction` poll
   loop; state that the timer is no longer cancelled by launch and the loop
   self-terminates via `close_requested`.
7. **Verify** — run the package suite (`colcon test`), including the existing
   `ament_flake8` / `ament_pep257` gates, and re-run the scratchpad harness at
   two durations to confirm handler count is flat and shutdown no longer scales
   with run length.

## Files to Change

| File | Change |
|------|--------|
| `ros2launch_gui/event_handlers/on_query_user_interface.py` | `cancel_on_shutdown=False` + rationale comment; default `period` 0.2 → 0.1 |
| `ros2launch_gui/api/user_interface.py` | non-debug `update_rate` 20.0 → 10.0; `_on_shutdown` sets `_close_requested` before `close()` and guards a raising teardown |
| `test/test_on_query_user_interface.py` | New — fast unit test of `handle()` |
| `test/test_poll_loop_handler_leak.py` | New — headless `LaunchService` test: handler count constant; shutdown completes even when backend teardown raises |
| `README.md` | Design paragraph: poll loop self-terminates via `close_requested` |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| A change includes its consequences | README Design paragraph and both tests land in this PR; the shutdown-latency floor is stated at the call site |
| Test what breaks | The integration test asserts the steady-state invariant (constant handler count) that the field failure violated, not just shutdown duration |
| Capture decisions, not just implementations | The upstream cause and the "why `cancel_on_shutdown=False` is safe here" rationale live at the call site (Q2: local note only, no upstream item); operator decisions Q1-Q4 recorded above |
| Only what's needed | One-line core fix plus the two operator-scoped items; the poll-loop architecture is untouched |
| Improve incrementally | Single reviewable PR; governance gaps deliberately not fanned out |
| Human control and transparency | No operator-visible behavior change except faster shutdown and a 10 Hz UI refresh; the halved refresh rate is stated in the PR body |
| Workspace vs. project separation | Entirely within the project repo |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 — ROS 2 conventions | Yes | New tests and comments must pass the package's `ament_flake8` / `ament_pep257` tests; match existing style (`test/test_tui_interface.py`) |
| 0013 — progress.md vocabulary | Yes | `## Plan Authored` entry appended via `progress_append.sh` |
| 0018 — Local-first CI | Yes (at merge) | Repo has no `.github/` workflows — merge gate is a full-scope `ci_local.sh` attestation on the PR head |
| 0002 — Worktree isolation | Satisfied | `issue-ros2launch_gui-30`, branch `feature/issue-30` |
| 0017 — AGENTS.md in project repos | Gap, not this PR | Repo has no root `AGENTS.md` / `.agents/README.md` / pre-commit config — recorded as a follow-up |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| Timer no longer cancelled on shutdown | Shutdown latency gains a bounded floor of one poll period (~100 ms at 10 Hz; 200 ms on the 5 Hz debug path) — stated at the call site and in the PR body | Yes |
| `close_requested` becomes the only stop path | `_on_shutdown` hardened so a raising backend teardown cannot hang shutdown; all three backends keep calling `super().close()` first | Yes |
| Poll rate 20 Hz → 10 Hz | UI refresh halves; the debug path (5 Hz) is left alone deliberately | Yes |
| `OnQueryUserInterface` default period changes | No in-repo caller relies on the default (`api/user_interface.py` always passes an explicit period); grep-verified | Yes |
| README documents the poll loop | Design paragraph updated | Yes |
| Repo lacks `AGENTS.md` / `.agents/README.md` / pre-commit | Governance follow-up | No — follow-up, deliberately not fanned out |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): `README.md` "Design" paragraph — it
  describes the `TimerAction` poll loop and becomes inaccurate about how the loop
  ends.
- **Agent-instruction candidates** (proposals only): a note that upstream
  `launch.actions.TimerAction` registers an **unguarded** per-instance `Shutdown`
  handler, so any repeatedly-constructed `TimerAction` in a long-running launch
  session leaks handlers unless `cancel_on_shutdown=False` — a candidate for
  `.agent/knowledge/` ROS 2 patterns, since the trap is not specific to this repo.

## Open Questions

- None — Q1-Q4 were decided by the operator and are recorded under Approach.

## Estimated Scope

Single PR.
