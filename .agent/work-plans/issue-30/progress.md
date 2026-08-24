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
