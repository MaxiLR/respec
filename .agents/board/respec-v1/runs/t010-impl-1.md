# t010 implementation run 1

- Branch: `codex/respec-v1-t010` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t010`)
- Base: `60224c7af58897549aac1253b7a49996833c1733`
- Head: `6583406`
- Status: DONE

## Changes

| File                        | Change                                                                                                                                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/tui.py`         | New. `RespecApp` (profile list, Activate button, status panel per owned target folder, feedback line, footer bindings), `ProfileList` (click/arrows select, Enter activates), `AdoptDialog` modal (add / backup / keep per entry). |
| `src/respec/cli.py`         | Minimal: callback gets `invoke_without_command=True` and opens the TUI when no subcommand; new `tui` command; `no_args_is_help` dropped; app help text mentions the TUI. `--home` semantics untouched.                             |
| `pyproject.toml`, `uv.lock` | Adds `textual>=8.2` (locked 8.2.8).                                                                                                                                                                                                |
| `tests/test_tui.py`         | New: 14 Pilot/CLI tests, headless, against the autouse temp homes.                                                                                                                                                                 |
| `README.md`                 | Usage line and a short TUI section.                                                                                                                                                                                                |

Core reuse (no duplicated logic): profiles via `profiles.list_profile_names` and
`profiles.load_profile`; status via `switch.status`; activation via `switch.use`;
an `UnknownEntries` refusal opens the dialog, then the switch is retried with an
`on_unknown` handler that calls `adopt.resolve` (same shape as the CLI `use`);
the `a` key uses `adopt.find` and `adopt.adopt`. Homes come from the CLI
callback (`ctx.obj`); nothing is computed at import time.

## Acceptance criteria and evidence

| Criterion                                                                                | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `respec` with no args (or `respec tui`) opens the TUI                                    | `test_respec_without_command_or_tui_opens_the_tui[[] / [tui]]` (CLI run, `RespecApp.run` recorded); `test_help_still_lists_commands`.                                                                                                                                                                                                                                                                                                                                           |
| Profile list with active marker; keyboard and mouse activation; status per target folder | `test_profile_list_marks_the_active_profile`, `test_keyboard_activation_switches_profile` (down+enter; asserts `status --json` and links on disk), `test_mouse_click_selects_then_activate_button_switches` (click selects only, click Activate switches), `test_activate_button_is_disabled_for_the_active_profile`, `test_status_panel_shows_each_target_folder_and_its_items`, `test_empty_home_shows_how_to_start`, `test_failed_switch_reports_error_and_changes_nothing`. |
| Unknown-entry prompt (adopt / back up and remove / keep) as a dialog                     | `test_unknown_entry_opens_dialog_and_backup_choice_switches` (Apply disabled until chosen; backup on disk), `test_cancelling_the_unknown_dialog_leaves_everything` (Escape), `test_add_choice_adds_entry_to_the_profile_being_activated`, `test_status_panel_flags_unknown_and_adopt_key_keeps_it`.                                                                                                                                                                             |
| Uses the same core functions as the CLI; no logic duplicated                             | Code review of `tui.py`: only calls `switch.use/status`, `adopt.resolve/find/adopt`, `profiles.*`, `load_state`. Tests assert outcomes through `respec status --json` and the filesystem. Mutation check: disabling the TUI's call into the switch/resolve path made 3 tests fail.                                                                                                                                                                                              |
| Follows default-design (Bencho) adapted to the terminal                                  | Semantic colour tokens from the design reference defined once (`COLORS`, used as TCSS variables and in styled text); neutral surface layers, rounded borders, accent only for primary action/focus, status always labelled (`active`, `unknown folder`, `kept unmanaged`) besides colour; explicit success/error feedback line; disabled state distinct. Rendered headless screenshots (main, dialog, after switch) inspected at 110x32.                                        |

5/5 criteria met.

## Verification

- `uv run pytest -q` -> `124 passed in 7.56s`
- `uv run black --check .` -> `23 files would be left unchanged.`
- `npx prettier --check README.md` -> `All matched files use Prettier code style!`
- Red first: `tests/test_tui.py` failed 14/14 before implementation (`ModuleNotFoundError: respec.tui`; help lacked `tui`).

## Concerns

- `cli.py` callback and Typer app constructor are touched (small); ticket 007 also edits `cli.py`, so expect a trivial merge near the top of the file.
- No-args now opens the TUI instead of printing help; scripts relying on bare `respec` printing help would change (`respec --help` still works).
- Long absolute target paths wrap in the status panel; no `~` shortening was added to keep display consistent with the CLI.
- Switch and adopt run synchronously on the UI thread (fast filesystem operations); a git-source update in later tickets might need a worker.
