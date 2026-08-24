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
