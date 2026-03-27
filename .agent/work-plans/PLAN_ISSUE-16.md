# Plan: feat: add terminal UI (TUI) backend using urwid

## Issue

https://github.com/rolker/ros2launch_gui/issues/16

## Context

The existing `--gui` (`GuiOption`) and `--tk` backends require a display server. This
plan adds a `--tui` flag that launches a urwid-based terminal UI for headless/SSH
environments. The base class API (`UserInterface`), the `OptionExtension` entry-point
pattern, the `DisplayUserInterface` action with its `ui_launcher` parameter, and the
`OnQueryUserInterface` timer-driven `spin_once()` loop are all already in place — this
backend slots in with no base-class changes.

`rosdep resolve python3-urwid` → `#apt python3-urwid` (confirmed on Noble/Jazzy).

## Approach

### v1a — Core infrastructure (this PR)

1. **`ros2launch_gui/tui/__init__.py`** — Lazy import (PEP 562), matching `tk/__init__.py`.

2. **`ros2launch_gui/tui/user_interface.py`** — `UserInterface` subclass.
   - `__init__`: create `urwid.MainLoop(top_widget)`, call `self.loop.screen.start()`.
   - `spin_once()`: call `self.loop.screen.get_input_nonblocking()`, pass keys to
     `self.loop.process_input()`, then `self.loop.draw_screen()`. Check `close_requested`
     first. Called at 20 Hz by the existing `OnQueryUserInterface` timer — no async
     coroutine or event-loop takeover needed.
   - `close()`: call `super().close()` then `self.loop.screen.stop()`.
   - `on_close()`: call `super().on_close()` (triggers `Shutdown()`).
   - Implement all `on_process_*` / `on_state_transition()` callbacks to update widgets.

3. **`ros2launch_gui/tui/process_list.py`** — urwid `ListBox` showing processes with
   status indicators (RUNNING ●, EXITED ○, CRASHED ✗). Each row has a letter shortcut
   (`[a]`, `[b]`, …). Arrow keys move selection; ENTER selects for single-output view.

4. **`ros2launch_gui/tui/output_view.py`** — urwid `ListBox` for log output.
   - All-processes mode (default): interleaved output with `[name]` prefix.
   - Single-select mode: output from selected process only.
   - Scrollback cap: 10,000 lines/process, 50,000 lines total (constants, easy to
     change). Oldest lines discarded at limit — critical for long sessions.

5. **`ros2launch_gui/tui/status_bar.py`** — `urwid.Text` row with keybinding hints.
   Shows `[k]ill  [m]ute  [q]uit  [SPACE] toggle output  Lifecycle: [C]onfigure [A]ctivate [D]eactivate [S]hutdown`.

6. **`ros2launch_gui/option/tui.py`** — `TuiOption(OptionExtension)`.
   - `add_arguments`: adds `-t` / `--tui` flag.
   - `prelaunch`: if `args.tui`, returns
     `LaunchDescription([DisplayUserInterface(launch_description=ld, ui_launcher=_tui_launcher, debug=args.debug)])`.
   - `_tui_launcher(ld, ctx, debug)` is a module-level factory — lazy-imports
     `ros2launch_gui.tui.UserInterface` to avoid urwid import at flag registration time.
   - If both `--gui` and `--tui` are passed: since each `OptionExtension.prelaunch` runs
     independently and returns its own launch description, both would attempt to start.
     Add a guard in `TuiOption.prelaunch` that checks `hasattr(args, 'gui') and args.gui`
     and raises `ValueError('--tui and --gui are mutually exclusive')`.

7. **`setup.py`** — add `'tui = ros2launch_gui.option.tui:TuiOption'` to
   `ros2launch.option` entry points.

8. **`package.xml`** — add `<depend>python3-urwid</depend>` (runtime dep, not test-only).

### v1b — Interactive controls (follow-up PR, separate issue)

- Lifecycle node state display (`[unconfigured]`, `[inactive]`, `[active]`) and keyboard
  transitions via `EmitEvent(ChangeState(...))` through `add_pending_action()`.
- Collapsible launch description tree using urwid `TreeWidget` / `ParentNode`.
- Per-process muting (`[m]` key).
- Kill process (`[k]` key via `ShutdownProcess` / `EmitEvent`).

Splitting v1b into a follow-up PR keeps v1a reviewable and ships the core use case
(headless monitoring) without blocking on the more complex keyboard interaction work.

## Files to Change

| File | Change |
|------|--------|
| `ros2launch_gui/tui/__init__.py` | New — lazy import |
| `ros2launch_gui/tui/user_interface.py` | New — urwid `UserInterface` subclass |
| `ros2launch_gui/tui/process_list.py` | New — process list widget |
| `ros2launch_gui/tui/output_view.py` | New — output view with scrollback cap |
| `ros2launch_gui/tui/status_bar.py` | New — keybinding hint bar |
| `ros2launch_gui/option/tui.py` | New — `TuiOption` entry point |
| `setup.py` | Add `tui` to `ros2launch.option` entry points |
| `package.xml` | Add `<depend>python3-urwid</depend>` |
| `test/test_tui_interface.py` | New — smoke test: `UserInterface.__init__` with mock screen |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| Human control and transparency | `--tui` is explicit opt-in; scrollback configurable; `[q]` quit always visible |
| Only what's needed | v1a delivers the core use case; lifecycle/composition deferred to v1b |
| Improve incrementally | v1a → v1b → v2 staged; no big-bang delivery |
| A change includes its consequences | Smoke test included; `package.xml` dep added; `--gui`/`--tui` conflict handled |
| Capture decisions | ADR for library choice recommended (see Open Questions) |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| ADR-0001 | Yes | urwid library selection and event-loop integration are worth an ADR |
| ADR-0002 | Yes | Worktree on `feature/issue-16` (already created) |
| ADR-0008 | Yes | `python3-urwid` rosdep key verified (`#apt python3-urwid`) |
| ADR-0009 | Yes | Runtime dep uses apt/rosdep, not `.venv` |

## Consequences

| If we change… | Also update… | Included? |
|---|---|---|
| Add `tui` entry point | `setup.py` + `package.xml` | Yes |
| Both `--gui` and `--tui` flags exist | Document mutual exclusion | Yes (guard in `TuiOption`) |
| New TUI files | `ament_flake8` / `ament_pep257` will lint them automatically | Yes (same test suite) |
| No `.agents/README.md` exists | Should be created — but that's a separate task | No — follow-up |

## Open Questions

- Should the urwid library selection be captured as an ADR in this repo's `docs/decisions/`?
  The rationale in the issue (urwid vs textual vs rich) is thorough. Recommend yes, but
  can be deferred to v1b.

## Estimated Scope

Two PRs: v1a (this plan, core infrastructure) is a single focused PR. v1b (interactive
controls) will be a follow-up issue.
