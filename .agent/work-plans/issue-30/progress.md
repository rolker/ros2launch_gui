---
issue: 30
---

# Issue #30 — ros2 launch -g leaks one Shutdown event handler per UI poll — shutdown cost grows quadratically with session length

## Issue Review
**Status**: complete
**When**: 2026-08-23 22:37 -04:00
**By**: Claude Code Agent (Claude Opus)

**Issue**: #30 — `ros2 launch -g` leaks one Shutdown event handler per UI poll (quadratic shutdown cost)
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped

### Summary

Root cause re-verified against source, not taken on trust:

- `/opt/ros/jazzy/lib/python3.12/site-packages/launch/actions/timer_action.py` —
  `execute()` sentinel-guards the general `TimerEvent` handler
  (`_TimerAction__event_handler_has_been_installed`) but registers the
  `Shutdown`-matching cancel handler **unguarded** whenever `cancel_on_shutdown`
  is true (the default). Confirmed as described in the issue.
- `ros2launch_gui/event_handlers/on_query_user_interface.py:26` is the **only**
  `TimerAction` construction in the repo (grep over all `*.py`), so the one-line
  fix is complete in itself — nothing else in this package depends on
  shutdown-cancel semantics.
- The `close_requested` stop path is intact in **all three** backends today:
  `UserInterface._on_shutdown` → `close()`, and `qt/main.py:71`, `tk/user_interface.py:43`,
  `tui/user_interface.py:76` each call `super().close()` **before** tearing down
  their toolkit. `handle()` returns `None` ahead of `spin_once()`, so no poll can
  touch a destroyed toolkit.

Architecture stays as-is (launch-driven poll loop returning actions through the
handler's return value). A `QTimer` replacement is explicitly out of scope.

### Findings

1. **Shutdown latency gains a bounded floor of one poll period.** `TimerAction.get_asyncio_future()`
   returns `_completed_future`, which the launch service waits on. With
   `cancel_on_shutdown=False` launch no longer cancels the in-flight timer, so
   shutdown waits up to one period (~50 ms at 20 Hz; 200 ms at the class default
   `period=0.2`). Bounded and far better than quadratic — but it makes the poll
   period a floor on shutdown latency, which is an argument against raising it
   much and belongs in the call-site comment.
2. **`_close_requested` becomes load-bearing and is not currently fail-safe.**
   `_on_shutdown` is not wrapped by `_safe_callback`, and the flag is set by the
   subclass calling `super().close()`. A future subclass whose teardown raises
   before that call converts a cosmetic bug into a **shutdown hang**. Recommend
   setting the flag in `_on_shutdown` (or `try/finally` in the base `close()`) so
   it survives a raising subclass teardown.
3. **Acceptance criteria should cover steady state, not just shutdown.** The
   field symptom was a core pegged at ~100% *during* a 30 h run — every event
   scans the whole handler list. "Registered handler count stays constant over an
   N-minute run" covers both the CPU burn and the shutdown time.
4. **Consequences**: the README "Design" paragraph documents the TimerAction poll
   loop; it should state that the loop now terminates itself via `close_requested`
   rather than being cancelled by launch. Same PR.
5. **Test gates**: the package's suite already runs `ament_flake8` / `ament_pep257`
   (`test/test_flake8.py`, `test/test_pep257.py`), so the new comment/test must
   pass both. `test/test_tui_interface.py` shows the mock-based headless pattern.
6. **Merge verification**: this repo has no `.github/` workflows at all — there is
   no hosted CI mirror. Per ADR-0018 the merge gate is a full-scope
   `ci_local.sh` attestation.
7. **Governance gap (out of scope, follow-up candidate)**: no root `AGENTS.md`
   (ADR-0017), no `.agents/README.md`, no `.pre-commit-config.yaml`. Noted, not
   fanned out into an issue.

### Principle Alignment

| Principle | Status | Notes |
|---|---|---|
| A change includes its consequences | Action needed | README Design paragraph + regression test land in the same PR |
| Test what breaks | Action needed | Assert handler count constant and that shutdown terminates within a bound; prefer counts over wall-clock timings for CI stability |
| Capture decisions, not just implementations | Watch | The "why `cancel_on_shutdown=False` is safe here" rationale must live at the call site, not only in the issue |
| Only what's needed | OK | One-line fix; architecture unchanged |
| Improve incrementally | OK | Single reviewable PR |
| Human control and transparency | OK | No operator-visible behavior change beyond faster shutdown |
| Workspace vs. project separation | OK | Fix belongs in this project repo; upstream report is separate |

### ADR Applicability

| ADR | Triggered | Notes |
|---|---|---|
| 0008 — ROS 2 conventions | Yes | New test must satisfy the existing ament flake8/pep257 gates |
| 0013 — progress.md vocabulary | Yes | This entry |
| 0017 — AGENTS.md in project repos | Yes (gap) | Repo has no root `AGENTS.md`; follow-up, not this PR |
| 0018 — Local-first CI | Yes (at merge) | No hosted CI in this repo — full-scope `ci_local.sh` attestation is the gate |
| 0002 — Worktree isolation | Satisfied | Work in `issue-ros2launch_gui-30` |

### Related issues

- #22 (architecture alignment with launch internals) — natural home for the
  20 Hz rate question.
- #23 (test coverage for core logic) — the regression test partially advances it.

### Open questions for the operator

- [ ] Q1 — Fold the secondary items (20 Hz → 10 Hz; `OnQueryUserInterface`'s
      default `period=0.2` disagreeing with the `1/20` `UserInterface` passes)
      into this PR, or route to #22? Recommendation: correct the misleading
      default here (same file, no in-repo caller relies on it); defer the rate
      change to #22 where it can be judged against UI responsiveness.
- [ ] Q2 — File the upstream `ros2/launch` bug as its own tracked item, plus a
      local issue holding the link so the workaround comment can be retired when
      upstream fixes it?
- [ ] Q3 — Regression-test form: a ~2-3 s `LaunchService` headless integration
      test, a fast unit test on `OnQueryUserInterface.handle()` (asserts
      `cancel_on_shutdown=False` and `None` when `close_requested`), or both?
- [ ] Q4 — Finding 2 (make `_close_requested` survive a raising subclass
      teardown) in this PR or a separate one?

### Actions
- [ ] Add the call-site comment explaining why `cancel_on_shutdown=False` is safe and that `close_requested` is what stops the loop
- [ ] Add a regression test asserting the registered handler count stays constant across polls and that shutdown terminates within a bound
- [ ] Update the README "Design" paragraph: the poll loop now self-terminates via `close_requested`
- [ ] Decide Q1 (rate / default-period mismatch: this PR or #22)
- [ ] Decide Q2 (upstream `ros2/launch` report as a separate tracked item)
- [ ] Decide Q3 (regression-test form)
- [ ] Decide Q4 (harden `_close_requested` against a raising subclass teardown)
- [ ] Merge gate: full-scope `ci_local.sh` attestation (no hosted CI in this repo)
- [ ] Follow-up candidate (not this PR): repo lacks root `AGENTS.md` / `.agents/README.md` / pre-commit config

## Plan Authored
**Status**: complete
**When**: 2026-08-23 22:49 -04:00
**By**: Claude Code Agent (Claude Opus)

**Plan**: `.agent/work-plans/issue-30/plan.md` at `ca22995`
**Branch**: feature/issue-30 at `ca22995`
**Phases**: single

Core fix: pass `cancel_on_shutdown=False` at `on_query_user_interface.py:26` —
the only `TimerAction` in the repo — with a call-site comment recording the
upstream unguarded-Shutdown-handler cause (Q2: local note only, no upstream
item) and the resulting one-poll-period shutdown-latency floor. Operator-scoped
extras in the same PR: poll rate aligned at 10 Hz in both places (handler default
0.2 → 0.1; `UserInterface` non-debug 20.0 → 10.0, debug 5.0 left alone), and
`_close_requested` made fail-safe by setting it in `_on_shutdown` before
`close()` and guarding a raising backend teardown. Tests: a fast unit test on
`handle()` plus a headless `LaunchService` test asserting the registered
handler count stays constant across many polls (steady-state symptom) and that
shutdown completes even when teardown raises. README "Design" paragraph updated.
Architecture (launch-driven poll loop) unchanged. Merge gate is a full-scope
`ci_local.sh` attestation — this repo has no hosted CI.

### Open questions
- [ ] No open questions — Q1-Q4 were decided by the operator; plan is review-plan-ready.

### Actions
- [ ] Implement steps 1-7 of the plan (fix, rate alignment, `_on_shutdown` hardening, two tests, README)
- [ ] Run `/review-code` pre-push before opening the PR
- [ ] Merge gate: full-scope `ci_local.sh` attestation (no hosted CI in this repo)
- [ ] Follow-up candidate (not this PR): repo lacks root `AGENTS.md` / `.agents/README.md` / pre-commit config

## Plan Review
**Status**: complete
**When**: 2026-08-23 22:56 -04:00
**By**: Claude Code Agent (Claude Opus)

**Plan**: `.agent/work-plans/issue-30/plan.md` at `ca22995`
**PR**: PR-less (`--issue` mode)
**Branch**: `feature/issue-30`
**Verdict**: changes-requested

Two must-fix items, both discovered by running things rather than reading them:
the package's lint gates are already red on the branch base, which makes the
plan's own stated merge gate unreachable; and the raising-teardown regression
test, as specified, hangs forever instead of failing. Everything else is sound —
the core fix, the `_close_requested` hardening, and the handler-count invariant
all check out, the last one empirically.

### Verification performed

- **Upstream cause re-confirmed** at `launch/actions/timer_action.py:203-217`:
  the `TimerEvent` handler is sentinel-guarded
  (`_TimerAction__event_handler_has_been_installed`), the `Shutdown`-matching
  cancel handler is not. `launch_service.py:322` copies the whole handler deque
  (`tuple(self.__context._event_handlers)`) per event — that copy is the
  quadratic term.
- **Handler-count invariant measured** with
  `.agent/scratchpad/ros2launch_gui_timer_leak_test.py`: with
  `cancel_on_shutdown=False` the count is flat at 5 for both a 6 s and a 12 s run
  (60 and 120 polls); with the default it is polls+5 (124 → 241). Step 5's
  assertion would fail against today's code and passes with the fix.
- **Shutdown-latency floor measured**: 0.038 s and 0.077 s at 10 Hz — uniformly
  distributed inside the 100 ms period, consistent with the launch service
  waiting on the timer's `_completed_future` via `_entity_future_pairs`.
- **Every path to `_close_requested` traced** — see finding 7. No gap found.
- **Baseline test run**: `pytest test/` on the branch → 2 failed, 17 passed,
  1 skipped. `test_flake8` reports 156 errors, `test_pep257` 10, across ~12
  files. `test_copyright` is `@pytest.mark.skip`.

### Findings

- [ ] (must-fix) Merge gate is unreachable as stated: `ament_flake8` (156) and `ament_pep257` (10) already fail on the branch base — `ci_local.sh` runs `colcon test --return-code-on-test-failure`, so no full-scope attestation can pass. Needs an operator decision (fix in-PR / separate cleanup issue + accepted exception) recorded as an open question — `plan.md` step 7 + ADR-0008/0018 rows
- [ ] (must-fix) Step 5's raising-teardown case hangs CI rather than failing it: `launch_service.py:350-360` catches a handler exception, sets `return_code=1` and **continues**, so pre-hardening the flag is never set, the poll chain reschedules forever and `run()` never returns. Add a watchdog that fails the test after a few seconds, and assert `run()` returns **0**, not merely that it returned — `plan.md` step 5
- [ ] (suggestion) There is a public-behaviour alternative to `_TimerAction__cancel_on_shutdown`, verified working: `execute()` the returned TimerAction against a bare `LaunchContext` with a fresh asyncio loop, then assert `sum(1 for h in ctx._event_handlers if h.matches(Shutdown()))` is 0 (it is 1 with the default). Uses only `BaseEventHandler.matches()` plus the same `_event_handlers` step 5 already reads; drain with `action.cancel()` + `loop.run_until_complete(action.get_asyncio_future())` before `loop.close()` to avoid a pending-task warning — `plan.md` step 4
- [ ] (suggestion) The shutdown-latency floor must be stated at `api/user_interface.py:49` too, not only at the handler call site — line 49 (`update_rate = 5.0 if debug else 20.0`) is where a future rate-changer actually edits — `plan.md` step 1
- [ ] (suggestion) `UserInterface.__init__` has no poll-period knob (it derives the period from `update_rate` internally), so step 5's "fast poll period" has no mechanism; say the test uses the real 10 Hz rate (~25 polls in 2.5 s, versus a measured 1 leaked handler per poll = unambiguous) rather than letting the implementer add a parameter to make the test convenient — `plan.md` step 5
- [ ] (suggestion) Note in the step 3 comment that the debug-mode re-raise is safe *only because* the flag is set before `close()`: the run loop swallows the exception and keeps going, so termination rests entirely on `_close_requested` already being True. The ordering is the load-bearing part, not the try/except — `plan.md` step 3
- [ ] (suggestion) `handle()`'s early return skips `get_pending_actions()`, so any action a UI callback queues in the same poll as the shutdown event is silently dropped. Harmless today (`on_close()` is flag-guarded), but `_on_shutdown` now sets the flag earlier — one line in the plan saying this is acceptable and why is enough; no code change — `plan.md` step 3
- [ ] (suggestion) Extend the README edit to name the poll rate (10 Hz; 5 Hz debug) and the fact that the period bounds shutdown latency, not just that the loop self-terminates — `plan.md` step 6
- [ ] (confirmed, no action) Step 3's path analysis is complete: launch-initiated shutdown, user-closed window (`on_close` → pending `Shutdown()`), the `_safe_callback` debug re-raise (a subclass `close()` raising before `super().close()` propagates, which makes launch emit `Shutdown` and set the flag), and `spin_once()` raising inside `handle()` (unwrapped; propagates, launch shuts down, no new timer scheduled) all end with the flag set. Qt ordering is preserved because `qt/main.py:71` already calls `super().close()` first, so `closeEvent → on_close` still sees the flag and does not re-emit `Shutdown`

### Evaluation

| Dimension | Verdict | Notes |
|---|---|---|
| Scope | Good | 5 files, one PR; architecture untouched as required |
| Issue alignment | Good | All seven `## Issue Review` actions covered; Q1-Q4 executed as the operator decided |
| File targeting | Needs work | Correct set, but the latency note also belongs at `api/user_interface.py:49` (finding 4) |
| Consequences | Needs work | Table omits the pre-existing red lint baseline and its effect on the merge gate (finding 1) |
| Documentation & instruction impact | Good | Section present, non-silent, candidates framed as proposals |
| Principle alignment | Good | "Test what breaks" is served by the steady-state invariant; "only what's needed" holds |
| ADR compliance | Needs work | 0008 and 0018 rows assert gates that are red today (finding 1); 0002/0013/0017 fine |
| ROS conventions | Good | Plain-pytest headless test matches `test/test_tui_interface.py`; no new package.xml deps needed (`launch` is already an `exec_depend`) |

### Actions
- [ ] Resolve the lint-baseline / merge-gate question with the operator and record it in the plan before implementing
- [ ] Bound the raising-teardown test with a watchdog and assert return code 0
- [ ] Decide private-attribute read vs. the verified public-behaviour assertion (step 4)
- [ ] Fold findings 4-8 into the plan inline per plan-task's "During implementation" rules

## Implementation
**Status**: complete
**When**: 2026-08-23 23:51 -04:00
**By**: Claude Code Agent (Claude Opus)

**Plan**: `.agent/work-plans/issue-30/plan.md` (synced at `9453bac`)
**Branch**: `feature/issue-30` at `9453bac` (rebased onto `origin/jazzy` `047f59d`)
**PR**: not opened — host publishes after the operator checkpoint. Not pushed.

All seven plan steps landed, with both plan-review must-fixes and all six
suggestions folded in. Architecture untouched: the launch-driven poll loop and
its `[TimerAction(...)] + get_pending_actions()` return contract are unchanged.

### Commits (atomic, oldest first)

| SHA | Change |
|---|---|
| `d7dc954` | Poll rate aligned at 10 Hz: `OnQueryUserInterface` default `period` 0.2 → 0.1, `UserInterface` non-debug `update_rate` 20.0 → 10.0 (debug stays 5.0) |
| `0947c9c` | Core fix: `cancel_on_shutdown=False` on the rescheduled `TimerAction`, with the upstream-cause comment at the call site and the latency-floor note repeated at `api/user_interface.py` |
| `24400a1` | `_on_shutdown` sets `_close_requested` before `close()` and guards a raising teardown (re-raise under `_debug`, else `LogInfo`) |
| `5bd8996` | Two regression tests |
| `0fc4e9b` | README Design paragraph |
| `9453bac` | plan.md synced |

### Must-fix 1 — raising-teardown test fails, does not hang

Both headless cases run under a watchdog thread: if `run()` has not returned
`RUN_SECONDS + 5 s` after start, the watchdog sets `ui._close_requested`
directly to break the poll chain, records `timed_out`, and calls
`shutdown()`. The test asserts `not timed_out` **and** `run() == 0` — the
second assertion is what stops the swallowed-exception path
(`launch_service.py:350-360` sets `return_code=1` and continues) from passing
for the wrong reason. Verified by reverting the `_on_shutdown` hardening: the
case fails in ~8 s with "shutdown hung after a raising backend teardown"
rather than hanging.

### Must-fix 2 — public assertion, not the private attribute

`_count_shutdown_handlers()` executes the returned `TimerAction` against a
bare `LaunchContext` with a fresh asyncio loop and counts
`h.matches(Shutdown())` over `ctx._event_handlers`, draining with
`action.cancel()` + `run_until_complete(get_asyncio_future())` before
`loop.close()` (no pending-task warning). Measured directly: 1 with the
default, 0 with `cancel_on_shutdown=False`. No
`_TimerAction__cancel_on_shutdown` read anywhere.

Other plan-review items: the latency-floor comment is at
`api/user_interface.py` on the `update_rate` line; the headless test uses the
real 10 Hz via `DisplayUserInterface`'s `ui_launcher` hook and adds no
poll-period knob; the `_on_shutdown` comment states that the debug re-raise is
safe *only because* the flag is set first; the dropped-`get_pending_actions`
case is recorded as accepted in plan step 3; the README names the rates and the
latency floor.

### Verification

`./underlay_ws/build.sh ros2launch_gui` clean. `./underlay_ws/test.sh
ros2launch_gui` → **27 tests, 0 errors, 0 failures, 1 skipped** (baseline 20;
+7 new). `ament_flake8` and `ament_pep257` both pass — the base was clean
after the rebase and stayed clean.

Negative controls (each fix reverted in turn, then restored):

- Without `cancel_on_shutdown=False`: `test_rescheduled_timer_registers_no_shutdown_handler` fails (`assert 1 == 0`) and `test_handler_count_is_constant_while_polling` fails.
- Without the `_on_shutdown` hardening: `test_shutdown_completes_when_backend_teardown_raises` fails in ~8 s via the watchdog.

Repro harness (`.agent/scratchpad/ros2launch_gui_timer_leak_test.py`) at 10 Hz,
two durations:

| Run | `cancel_on_shutdown` | Polls | Registered handlers | Shutdown |
|---|---|---|---|---|
| 15 s | True (before) | 148 | 153 | 0.045 s |
| 15 s | False (after) | 149 | **5** | 0.021 s |
| 60 s | True (before) | 579 | 584 | 0.412 s |
| 60 s | False (after) | 596 | **5** | 0.008 s |

Handler count is flat at 5 regardless of run length; shutdown no longer scales
with session length (4x the duration was 9.2x the shutdown time before, and is
unrelated to duration after).

### Actions
- [ ] Run `/review-code` pre-push before opening the PR
- [ ] Push and open the PR (host publishes after the operator checkpoint) — PR body should note the halved UI refresh rate (20 Hz → 10 Hz)
- [ ] Merge gate: full-scope `ci_local.sh` attestation (no hosted CI in this repo)
- [ ] Follow-up candidate (not this PR): repo lacks root `AGENTS.md` / `.agents/README.md` / pre-commit config

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-08-24 00:12 -04:00
**By**: Claude Code Agent (Claude Opus)
**Verdict**: changes-requested

**Branch**: feature/issue-30 at `654a928`
**Mode**: pre-push
**Depth**: Deep (reason: shutdown/lifecycle correctness — the change removes launch's own timer-cancel stop path)
**Must-fix**: 3 | **Suggestions**: 8
**Round**: 1 | **Ship**: continue — a reproduced shutdown hang on a path the hardening does not cover

**Specialists**: Static Analysis (ament_flake8 + ament_pep257, clean) · Governance · Plan Drift · Claude Adversarial x2 (Lens A + Lens B) · Local Adversarial skipped (qwen3.5:35b request timed out at the 900 s limit; Ollama contended with a concurrent session)

### Verification performed

- `ament_flake8` / `ament_pep257` clean on all four changed Python files; base lint baseline (`047f59d`) preserved.
- Reverted each fix in turn and re-ran the new tests: reverting `cancel_on_shutdown=False` fails both leak tests (handler count climbs 12→36 across 25 samples, 1 per poll); reverting the `_on_shutdown` hardening fails the raising-teardown test on `timed_out` in ~7.5 s with `return_code=1`. Both fail — neither hangs, neither passes vacuously.
- `_count_shutdown_handlers()` discriminates correctly through the public route: 1 handler with `cancel_on_shutdown=True`, 0 with `False`. No `_TimerAction__cancel_on_shutdown` coupling remains.
- Upstream claims re-verified against `/opt/ros/jazzy/.../launch/`: `TimerAction.execute()` sentinel-guards the `TimerEvent` handler but registers the `Shutdown` cancel handler unguarded; `LaunchService.__process_event` copies the whole deque per event; the in-flight timer's `_completed_future` keeps `_is_idle()` false, so the one-period latency floor is correct.

### Findings

- [x] (must-fix) Stop condition does not cover every path: a sibling `OnShutdown` handler that raises aborts dispatch before `UserInterface._on_shutdown` runs, so `_close_requested` is never set and the poll chain reschedules forever — reproduced: hung, 75 spins, `run()` never returned. Reachable from any `OnShutdown` in the user launch description this tool exists to display, and from `ExecuteLocal`'s per-process handler. One-line belt `or context.is_shutdown` verified to close it (1.5 s, 15 spins, clean return) — `ros2launch_gui/event_handlers/on_query_user_interface.py:22`
- [x] (must-fix) Comment is factually wrong — launch does not "swallow the exception and keep running": `LaunchService.__process_event` has no per-handler try, so re-raising aborts the remaining Shutdown handlers including `LaunchService.__on_shutdown` (registered first ⇒ last in the deque), skips the matching `_pop_locals()`, and sets `return_code=1`. Cross-pass confirmed. Fix the comment or drop the debug re-raise — `ros2launch_gui/api/user_interface.py:168-171`
- [x] (must-fix) Comment claims "LaunchService exposes no public accessor for its context" — `LaunchService.context` is a public property (`launch_service.py:436`). Use it and delete the false justification for the name-mangled access — `test/test_poll_loop_handler_leak.py:82-83`
- [x] (suggestion) `_on_shutdown` is not idempotent, so `close()` runs twice in debug mode (`_safe_callback` closes and re-raises, launch re-emits Shutdown); `tk`'s unguarded `root.destroy()` raises `TclError` on the second call. Add the `if self._close_requested: return None` re-entry guard `_safe_callback` already has — `ros2launch_gui/api/user_interface.py:153`
- [x] (suggestion) `test_default_period_is_10_hz` does not test its stated coupling — it pins a constructor default production never uses (`UserInterface.__init__` always passes `period=` explicitly), so reverting `update_rate` to 20.0 leaves it green. Assert the `OnQueryUserInterface` that `UserInterface.__init__` actually builds. Cross-pass confirmed — `test/test_on_query_user_interface.py:63-66`
- [x] (suggestion) Headless-test sampling is load-sensitive with a misleading failure message: the sample count is wall-clock-derived (`len(steady) >= 10` can fail under load), and `launch_service.shutdown()` is a no-op while `__loop_from_run_thread is None`, so a slow main thread silently drops the shutdown request and the watchdog blames the code under test. Use a fixed sample count and gate the sampler on the loop being live. Cross-pass confirmed — `test/test_poll_loop_handler_leak.py:87-92`
- [x] (suggestion) The watchdog's own `launch_service.shutdown()` routes to `emit_event` → `future.result()` with no timeout, which blocks forever in exactly the wedged-loop case the watchdog exists to break. It works only because `ui._close_requested = True` is set on the preceding line — document that ordering or drop the call — `test/test_poll_loop_handler_leak.py:99-102`
- [x] (suggestion) No test covers the path users actually take: GUI window close / TUI `q` → `on_close()` → `Shutdown` *action*, the only path that bypasses `LaunchService._shutdown()` and leaves `LaunchService.__on_shutdown` as the sole setter of `__shutting_down` — `test/test_poll_loop_handler_leak.py`
- [x] (suggestion) Qt comment overstates the change: `qt/main.py:76` already calls `super().close()` before `main_window.close()`, so the flag was set before `closeEvent` even pre-change — `ros2launch_gui/api/user_interface.py:161-163`
- [x] (suggestion) A failed UI teardown surfaces as `LogInfo` plus exit code 0 — consistent with `_safe_callback` by design, but a genuine teardown failure (window left up, terminal left in raw mode) warrants error-level logging — `ros2launch_gui/api/user_interface.py:174-177`
- [x] (suggestion) The README's new termination story does not cover SIGTERM/SIGQUIT (the run task is cancelled, no Shutdown is emitted, `close()` never runs, TUI leaves the terminal in raw mode) or launch-idle (never fires while the poll chain holds a pending timer future). Both pre-existing — scope the claim or file a follow-up — `README.md:39`

### Governance

- Principles: "A change includes its consequences" — **Concern**: the latency-floor and self-termination consequences are documented at all three sites (call site, `update_rate` line, README), but the stop path itself is incomplete (must-fix 1). "Test what breaks" — **Pass**: both tests are non-vacuous and fail correctly against reverted code. "Never document from assumptions" — **Concern**: two comments assert upstream/API behaviour that source contradicts (must-fix 2 and 3).
- ADR-0008 (ROS 2 conventions): compliant — ament linters clean. ADR-0013 (progress.md vocabulary): compliant. ADR-0002 (worktree isolation): compliant. ADR-0018 (local-first CI): merge gate remains a full-scope `ci_local.sh` attestation; the lint baseline is green so it is reachable.
- Commit hygiene: 7 atomic commits under `Claude Code Agent <roland+claude-code@ccom.unh.edu>`, no issue-closing keywords in bodies ("Part of #30").
- Consequence check: no ROS parameters, topics, or services changed; README updated; no stale rate references remain anywhere in the repo (grep-verified).
- Pre-existing gap, not this PR: repo has no root `AGENTS.md` / `.agents/README.md` / pre-commit config (already tracked as a follow-up in this timeline).

### Plan Adherence

No drift. All seven plan steps landed as written, and both plan-review must-fixes plus all six suggestions are visible in the implementation (watchdog + `return 0` assertion, public `matches()` route, latency note at the `update_rate` line, real 10 Hz in the headless test, ordering note on the debug re-raise, accepted `get_pending_actions` drop, README rate detail).

### Next actions

- [x] Address must-fix 1: add the `context.is_shutdown` belt to `OnQueryUserInterface.handle` and cover it with the reproduced sibling-raise scenario as a test
- [x] Address must-fix 2 and 3: correct both inaccurate comments (or drop the debug re-raise)
- [ ] Re-run `/review-code` pre-push after addressing; do not push until the pre-push review is approved
- [ ] Merge gate: full-scope `ci_local.sh` attestation (no hosted CI in this repo)

## Implementation
**Status**: complete
**When**: 2026-08-24 00:26 -04:00
**By**: Claude Code Agent (Claude Opus)

**Branch**: feature/issue-30 at `7e47460`
**Addressed**: `## Local Review (Pre-Push)` (2026-08-24 00:12 -04:00, branch at `654a928`) — verdict changes-requested, round 1
**Commits**: 9b943ae, 7e4847b, ea2f49c, 22581fd, 2b275c0, 7e47460

### Actions
- [x] (must-fix) Second termination path: `handle()` now returns `None` on `self._ui.close_requested or context.is_shutdown`, with a comment stating why neither condition subsumes the other. New regression test drives a launch description carrying its own raising `OnShutdown` handler — `ros2launch_gui/event_handlers/on_query_user_interface.py:42`, `test/test_poll_loop_handler_leak.py:228`
- [x] (must-fix) Debug re-raise comment rewritten to describe what launch actually does: `__process_event` has no per-handler `try`, so the raise aborts the remaining `Shutdown` handlers (incl. `LaunchService.__on_shutdown`), skips `_pop_locals()`, and leaves `run()` returning 1 — `ros2launch_gui/api/user_interface.py:180`
- [x] (must-fix) Test uses the public `LaunchService.context` property; the false "no public accessor" comment is gone — `test/test_poll_loop_handler_leak.py:128`
- [x] (suggestion) `_on_shutdown` re-entry guard added, matching `_safe_callback`'s. Covered by `test_close_is_not_called_twice_on_shutdown` (debug + raising teardown via the `Shutdown`-action path, which is the only shape that actually re-emits) — `ros2launch_gui/api/user_interface.py:161`
- [x] (suggestion) Poll-rate tests now assert on the `OnQueryUserInterface` `UserInterface.__init__` actually builds, in both the 10 Hz and 5 Hz debug paths — `test/test_on_query_user_interface.py:80`
- [x] (suggestion) Headless sampling is a fixed sample count gated on the run loop being live (`spin_count > 0`), not a wall-clock deadline; the short-run failure message now blames the early run, not the code under test — `test/test_poll_loop_handler_leak.py:143`
- [x] (suggestion) Watchdog ordering documented: `ui._close_requested = True` must precede `launch_service.shutdown()` because that call routes to `emit_event` → `future.result()` with no timeout. Kept the call (the suggestion offered document-or-drop) — `test/test_poll_loop_handler_leak.py:161`
- [x] (suggestion) New `test_shutdown_completes_via_ui_close_action` covers the path users take: `on_close()` queues a `Shutdown` *action*, bypassing `LaunchService._shutdown()` — `test/test_poll_loop_handler_leak.py:249`
- [x] (suggestion) Qt note corrected: `qt/main.py`'s `close()` calls `super().close()` before `main_window.close()`, so that path never depended on `_on_shutdown`'s ordering — `ros2launch_gui/api/user_interface.py:172`
- [x] (suggestion) A failed teardown is now logged at error level via `launch.logging` instead of returning a `LogInfo` action into a UI being torn down — `ros2launch_gui/api/user_interface.py:190`
- [x] (suggestion) README scopes the termination claim: names both stop conditions, and states what is *not* covered — SIGTERM/SIGQUIT (run task cancelled, no `Shutdown` emitted, TUI left in raw mode) and shutdown-when-idle (never fires while the poll chain holds a pending timer future). Both pre-existing — `README.md:39`

### Verification

- `./underlay_ws/build.sh ros2launch_gui` + `./underlay_ws/test.sh ros2launch_gui`: **32 tests, 0 errors, 0 failures, 1 skipped** (was 27). `ament_flake8` / `ament_pep257` clean.
- Negative controls, each reverted then restored:
  - Remove `or context.is_shutdown`: `test_shutdown_completes_when_sibling_shutdown_handler_raises` **fails** on `timed_out` in ~7.5 s (watchdog), not by hanging. Other four tests still pass, confirming the new test is the only thing that covers this path.
  - Remove the `_on_shutdown` re-entry guard: `test_close_is_not_called_twice_on_shutdown` **fails** with `close_count == 2` in 1.3 s.
  - Revert `update_rate` to 20.0: `test_production_poll_rate_is_10_hz` **fails** (`0.05 != 0.1`) — the test it replaces stayed green under the same revert.
- Watchdog budget no longer includes startup: it waits for the loop to go live (bounded by `STARTUP_TIMEOUT`) before starting the shutdown budget, so a loaded machine costs startup time rather than producing a false timeout, and a real hang still fails inside the budget.

### Notes

- `return_code` is asserted as **1** in the sibling-raise test, not 0: launch marks the aborted handler dispatch as an error. The invariant under test is that `run()` returns at all. This is stated in the test.
- Nothing deferred; every finding was actioned.
- Commits are grouped by logical change rather than one-per-finding where findings shared a file region (the three `user_interface.py` comment/behaviour fixes land together in `7e4847b`, with the Qt-note correction split out in `2b275c0`). Every commit leaves the suite green.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-08-24 00:39 -04:00
**By**: Claude Code Agent (Claude Opus)
**Verdict**: changes-requested

**Branch**: feature/issue-30 at `a719ae1`
**Mode**: pre-push
**Depth**: Deep (reason: shutdown/lifecycle correctness — verification round on a removed termination path)
**Must-fix**: 1 | **Suggestions**: 9
**Round**: 2 | **Ship**: recommended — round-1 must-fixes all verified genuinely fixed; the one remaining item is a precise, mechanical fix, and must-fix count fell 3 → 1

**Specialists**: Static Analysis (ament_flake8 + ament_pep257, clean) · Governance · Plan Drift · Claude Adversarial x2 (Lens A + Lens B) · Local Adversarial off (--no-local; round-2 verification pass)

### Verification performed (round-1 must-fixes)

- **Must-fix 1 — CLOSED, independently reproduced.** Ran a standalone probe building the same launch description the new test uses and dumped the Shutdown-matching handler deque in dispatch order: `[0] raising sibling OnShutdown`, `[1] UserInterface._on_shutdown`, `[2] LaunchService.__on_shutdown`. The run ended with `return_code=1`, `spins=3`, **`close_requested=False`** — so `context.is_shutdown` is provably the only condition that stopped the loop. The belt holds and the new test covers the reported path, not a look-alike.
- **The belt's guarantee checked against installed launch source**, not taken on trust: `LaunchService._shutdown()` sets `self.__context._set_is_shutdown(True)` at `launch_service.py:413`, *outside* the `if not self.__shutting_down` block, so it is unconditional; `run_async`'s `except Exception` at `launch_service.py:351-358` calls `_shutdown()` for exactly the raising-handler case. Full route enumeration found no path where the poll chain outlives the run: SIGINT / `shutdown()` / idle / catch-all all set `is_shutdown`; the `Shutdown` *action* route sets it via `LaunchService.__on_shutdown`, and if a sibling raise aborts that dispatch the catch-all sets it one iteration later; SIGTERM/SIGQUIT cancel the run task outright (`launch_service.py:211`, `347-350`) so the loop cannot outlive it.
- **Must-fix 2 — CLOSED.** The `api/user_interface.py` re-raise comment now describes what launch actually does (no per-handler `try`; dispatch aborts; `_pop_locals()` skipped; `run()` returns 1). Matches source.
- **Must-fix 3 — CLOSED.** Public `LaunchService.context` property in use; the false "no public accessor" comment is gone; `grep` confirms no `_LaunchService__` or `_TimerAction__` coupling anywhere in `test/` or `ros2launch_gui/`.
- `ament_flake8` and `ament_pep257` re-run on the package: **No problems found**.
- Lens B ran the leak suite 5x (~9.4 s each, identical) and once pinned to a single contended core (12.6 s) — no flakiness; measured `spin_count=25` against the test's `>= 10` threshold, and confirmed `_event_handlers` flat at 11 with exactly 1 live `TimerAction` across 105 polls.

### Findings

- [ ] (must-fix) The `context.is_shutdown` route terminates the poll loop but never tears the UI down — instrumented on the PR's own scenario: `close_count=0, close_requested=False, rc=1`. `close()` is the only thing that calls `urwid`'s `loop.stop()` / tk's `root.destroy()`, so the operator gets a shell left in raw mode, exit code 1, no message. Not a regression (the same case previously hung, which is worse), but this PR adds the code, the test and the prose for this path, and the README presents `is_shutdown` as a clean equivalent of `close_requested` while conceding lost cleanup only for SIGTERM/SIGQUIT. Cross-pass confirmed (Lens A + Lens B, independently). Preferred fix: run the same guarded teardown `_on_shutdown` does on the `is_shutdown and not close_requested` branch before returning `None` — the handler is guaranteed exactly one post-shutdown dispatch, and `close()` setting `_close_requested` makes the existing re-entry guard cover double teardown; wrap it so a raising backend cannot escape into `handle()`. Add `assert run.ui.close_count == 1`. Minimum acceptable alternative: correct README + the handler comment to state that this route exits without UI cleanup — `ros2launch_gui/event_handlers/on_query_user_interface.py:42`, `README.md:39`
- [ ] (suggestion) Comment says `LaunchService.__on_shutdown` is "registered first and therefore last in the deque" — verified wrong: `launch_service.py:78` registers `OnIncludeLaunchDescription()` first, `:79` registers `OnShutdown(__on_shutdown)` second, so it is last only among *Shutdown-matching* handlers. Conclusion holds; the stated reason does not — `ros2launch_gui/api/user_interface.py:183-184`
- [ ] (suggestion) The `is_shutdown`-provenance comment lists SIGINT / `shutdown()` / idle / catch-all and concludes it "does not depend on any event handler completing" — incomplete on the most common route: a `Shutdown` *action* never calls `_shutdown()`, and `is_shutdown` is then set only by `LaunchService.__on_shutdown`, which *is* an event handler. The guarantee survives (a raising sibling routes to the catch-all) but by a different mechanism than the comment gives — `ros2launch_gui/event_handlers/on_query_user_interface.py:37-41`
- [ ] (suggestion) The re-entry-guard comment overstates when double delivery happens: `_shutdown()` sets `__shutting_down = True` unconditionally *before* the event is dispatched, so SIGINT / `shutdown()` / idle / catch-all never re-emit. Double delivery is specific to the `launch.actions.Shutdown` route. The guard is load-bearing; narrow the claim — `ros2launch_gui/api/user_interface.py:155-161`
- [ ] (suggestion) `test_shutdown_completes_when_backend_teardown_raises` passes for a different reason than its comment states. Mutation-verified: moving the flag assignment after `self.close()` leaves this test green, because the sampler drives shutdown via `launch_service.shutdown()`, which sets `is_shutdown` directly. The ordering *is* pinned — by `test_close_is_not_called_twice_on_shutdown`, which fails under the same mutation. Point the comment at the test that actually covers it — `test/test_poll_loop_handler_leak.py:216-224`
- [ ] (suggestion) The sibling-raise test never asserts which stop condition fired, so it would silently degrade into a duplicate of the ordinary-shutdown test if handler ordering ever flipped. Non-vacuous today (verified), but lock it in: `assert run.ui.close_count == 0` and `assert not run.ui.close_requested` — `test/test_poll_loop_handler_leak.py:226-241`
- [ ] (suggestion) The watchdog comment's rationale is wrong — a wedged poll chain does not wedge the asyncio loop, so `emit_event` → `future.result()` would still resolve. Separately there is a real (narrow) hazard: `LaunchService.shutdown()` from a non-main thread holds `__loop_from_run_thread_lock` while blocking in `future.result()` with no timeout, and `_prepare_run_loop`'s `finally` takes the same lock from the loop thread — if the watchdog races a real shutdown, both deadlock permanently, which is the exact outcome the watchdog exists to prevent. Consider a bounded `run_coroutine_threadsafe(...).result(timeout=…)` instead — `test/test_poll_loop_handler_leak.py:158-176`
- [ ] (suggestion) `live` is set only on the success path of `_wait_for_live_loop`, so a run that finishes before the first poll leaves the watchdog blocked in `live.wait(STARTUP_TIMEOUT)` past `run()`'s 5 s join, as a stray daemon thread. Harmless, easy to tidy — `test/test_poll_loop_handler_leak.py:133-143`
- [ ] (suggestion) In `_count_shutdown_handlers` the drain (`action.cancel()` + `run_until_complete`) sits in the `try` ahead of `loop.close()` in `finally`, so a raise from `execute()` or the count closes the loop with a pending task and emits "Task was destroyed but it is pending!", masking the real failure. Nested `try/finally` — `test/test_on_query_user_interface.py:56-69`
- [ ] (suggestion) The new error-level teardown log is unreachable for the failure it cites: the TUI's `close()` wraps `self.loop.stop()` in a bare `except Exception: pass`, swallowing the raw-mode failure one level below. Either let it propagate into the new reporting path or stop citing that case — `ros2launch_gui/tui/user_interface.py:76-81` vs `ros2launch_gui/api/user_interface.py:191-195`

### Judged explicitly

- **`return_code == 1` in the sibling-raise test is correct, not a weakening.** My own probe on that path produced `rc=1`, so asserting `0` would assert something launch cannot produce: the aborted dispatch propagates to `run_async`'s catch-all, which sets `return_code = 1` before recovering. `== 1` is an exact equality — strictly stronger than "returned at all" — and the anti-hang invariant is carried by the separate `not timed_out` assertion. Round 1's insistence on `== 0` applied to the *raising-teardown* test, where the non-debug path genuinely does exit 0; different test, different ground truth. Both are defensible. The real soft spot in this test is not the number but that nothing pins *which* stop condition fired (suggestion above).
- **Grouping commits by file region is acceptable here.** `7e4847b` bundles the re-entry guard, the flag-before-teardown ordering, and the two comments that exist to explain them — that is one logical change to one method, and splitting it would produce commits that do not stand alone. Revert granularity is preserved where it matters: the behavioral change is isolated in `9b943ae`, tests in `ea2f49c` / `22581fd`, and the genuinely independent Qt-note correction *was* split out into `2b275c0`. The workspace rule is one logical change per commit, not one commit per review finding. No action.

### Governance

- Principles: "A change includes its consequences" — **Concern**: the termination consequence is now complete and correct, but the *cleanup* consequence of the new stop path is neither covered by a test nor stated in the README (the must-fix). "Test what breaks" — **Pass**: every new test was mutation-checked by an independent reviewer; two were shown to be pinned by a different test than their comment claims, which is a comment defect, not a coverage hole. "Never document from assumptions" — **Concern**: five comments added on this branch state supporting details the installed launch source contradicts. Each conclusion is correct, so none rise to must-fix, but this is the same failure class round 1 raised — verify comment claims against source before the next push.
- ADR-0008 (ROS 2 conventions): compliant — ament linters clean. ADR-0013 (progress.md vocabulary): compliant. ADR-0002 (worktree isolation): compliant. ADR-0018 (local-first CI): merge gate remains a full-scope `ci_local.sh` attestation; lint baseline green so it is reachable.
- Commit hygiene: 19 commits, all authored `Claude Code Agent <roland+claude-code@ccom.unh.edu>`, no issue-closing keywords anywhere in the commit bodies (grep-verified).
- Consequence check: no ROS parameters, topics, or services changed; README updated; plan synced with a "Review round 1 follow-through" section.
- Pre-existing gap, not this PR: repo has no root `AGENTS.md` / `.agents/README.md` / pre-commit config.

### Plan Adherence

No drift. Plan step 8 records the round-1 follow-through and matches what landed. One stale phrase survives at `plan.md:59` ("otherwise return a `LogInfo`"), superseded within the same document by step 8's "error level instead of a `LogInfo` action" — cosmetic, below the suggestion threshold.

### Next actions

- [ ] Address the single must-fix (guarded teardown on the `is_shutdown` branch + test assertion, or the README/comment correction as the minimum), then push — a third full review round is not warranted
- [ ] Optional, cheap, and worth batching into the same commit: the five comment-accuracy corrections and the two test-hardening assertions
- [ ] Merge gate: full-scope `ci_local.sh` attestation (no hosted CI in this repo)
