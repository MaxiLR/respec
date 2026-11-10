# fix-10 implementation 1: `respec profile remove`

- Status: DONE
- Branch: `codex/respec-v1-fix-10`, base `4092c83`, head `b3b1fb3`
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-10`

## Changes

- `src/respec/removal.py` (new): `remove_profile(respec_home, name)` is the
  core function shared by the CLI and the TUI. It validates the name with
  `profiles.validate_name`, then holds `lock.exclusive`. It refuses a pending
  journal by raising `journal.Pending` with `pending_message`, which points to
  `respec recover`. It also refuses an unknown profile and the active profile,
  and points to `respec use <other>` / `respec restore`. Otherwise it creates a
  run folder `<respec home>/removed-profiles/<UTC stamp>[-n]/` and moves the
  profile folder into it with a single `os.rename`. Then it fsyncs both
  parents. Checkpoints `profile-remove:move` and `profile-remove:moved` sit
  around the rename. If the rename fails, it removes the empty run folder and
  changes nothing. It returns `Removed(name, path, backup)`, whose `describe()`
  text includes the way back (move the folder to `profiles/<name>`).
- `src/respec/switch.py`: `new_backup_run` takes an optional `parent`, so the
  timestamped and suffixed run naming is reused.
- `src/respec/cli.py`: `profile remove <name> [--json]`. Success prints
  `{name, path, backup, warnings}`. Every failure, including the lock refusal,
  prints `{name, error, warnings}` on stdout, and the command exits 1.
- `src/respec/tui.py`: a `Remove` button (`#remove`) under Edit/New profile and
  the `d` binding. Both open `RemoveProfileDialog`, which defaults to Cancel and
  closes on Esc. Confirming calls the same core function under `_changing`.
  Refusals appear in the feedback line.
- Docs: README covers the usage line, a paragraph (backup path, how to get the
  profile back, refusals, kill safety), the lock list, the busy JSON shapes, the
  JSON `error` section and the TUI. The shipped `respec` SKILL.md gets a command
  entry and its JSON and busy rules.

Design choice (narrow; the orchestrator can revisit): backups go to
`removed-profiles/` rather than `backups/<run>/`. A profile inside `backups/`
would show up in `respec restore --list` as a run, and `respec restore <run>`
would fail on it with "holds no target folder".

## Criterion -> evidence

| #   | Criterion                                                 | Evidence                                                                                                                                                                                                                                                                                                                      |
| --- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `profile remove <name> [--json]` removes                  | `test_remove_moves_the_profile_folder_to_a_backup`, `test_remove_json_reports_the_backup`, `test_removing_twice_keeps_both_backups`, `test_a_profile_with_an_invalid_profile_yaml_can_still_be_removed`, `test_after_switching_away_the_former_profile_can_be_removed`                                                        |
| 2   | Active refused, points to use/restore, exit 1, JSON error | `test_the_active_profile_is_refused`, `test_the_active_profile_is_refused_with_json`                                                                                                                                                                                                                                          |
| 3   | Never hard-deletes; backup path reported; way back        | Byte snapshot equality of the backup in the tests above; `test_a_removed_profile_comes_back_by_moving_its_folder` (move back, then `use` works); README/SKILL text                                                                                                                                                            |
| 4   | Lock, pending journal refused, crash-safe single rename   | `test_a_running_respec_is_refused` (real holder process; text and JSON), `test_an_interrupted_change_is_refused_not_recovered` (real SIGKILL leaves a journal; the journal stays unchanged), `test_a_kill_around_the_move_loses_nothing[profile-remove:move / :moved]` (real SIGKILL; status clean, recover ok, nothing lost) |
| 5   | Unknown and invalid names refused                         | `test_an_unknown_profile_is_refused`, `test_invalid_names_are_refused_and_nothing_moves` (`../profiles`, `..`, `a/b`, `.hidden`, `x\n`)                                                                                                                                                                                       |
| 6   | TUI delete with confirmation, same core, same refusals    | `tests/test_tui.py`: click and confirm, `d` then Esc cancels, active refused, lock held by another process refused, interrupted change refused (all Pilot)                                                                                                                                                                    |
| 7   | Docs; `--help` test; JSON contract                        | `test_help.py` and `test_shipped_skill_docs.py` pass (the SKILL names the command); `test_profile_remove_success_and_failure_shapes`, the no-nulls list includes `profile remove`, `BUSY_SHAPES` includes `{name, error, warnings}`                                                                                           |
| 8   | Says "skill"                                              | All new user-facing text says "skills"; `test_no_help_page_says_item` passes                                                                                                                                                                                                                                                  |

TDD: the new CLI tests failed first with `No such command 'remove'`. The TUI
tests failed first with `NoMatches` (no `#remove`) before the implementation.

## Verification (head b3b1fb3 content; suite run after the last change)

- `uv sync --frozen`: ok
- `uv lock --check`: `Resolved 28 packages`
- `uv run black --check .`: `45 files would be left unchanged.`
- `npx --yes prettier@3.3.3 --check README.md src/respec/shipped/respec/SKILL.md src/respec/shipped/profile-maker/SKILL.md src/respec/targets.yaml`: all pass
- `uv run pytest -q`: `583 passed in 209.18s` (base 559, plus 24 new)
- Real entry-point smoke (`uv run respec`, scratch homes): active refused
  (exit 1), `--json` success prints the backup path, `../x` prints the JSON
  error, and `--help` renders.

## Concerns

- A kill between the run-folder `mkdir` and the rename leaves an empty
  timestamp folder in `removed-profiles/`. It is harmless and nothing is lost.
- Nothing prunes `removed-profiles/`, and no `restore` command brings a profile
  back automatically: getting one back is a documented manual move.
- `journal.pending_message` says "any respec command that changes skills
  finishes it first", and `profile remove` refuses instead. That matches the
  criterion, but the wording is slightly at odds.
