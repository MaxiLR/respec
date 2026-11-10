# t003 implementation 1: interruption-safe switching journal

- Status: DONE
- Branch: `codex/respec-v1-t003` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`)
- Base: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127`
- Head: `a763a63` (one commit)
- Files: 15 (src/respec: new `journal.py`; changed `switch`, `restore`, `adopt`, `layers`, `items`, `sources`, `state`, `sync`, `cli`, `tui`; shipped `respec/SKILL.md`; README; tests: new `test_journal.py`, `test_sources.py` additions)

## Changes

- `respec/journal.py` (new): `state.json` gains an optional `journal`, left out when idle. It holds `operation`, `started_at`, `profile`, `previous`, `action`, `backup`, `skills` and `phase`, plus `pending` for the one step in flight. A nested switch adds a `switch` record.
  - API: `ready()` (recover or refuse before a change), `begin()` (context manager; nesting aware), `mark()` (step in flight), `set_phase()`, `checkpoint()` (failure-injection seam `_fault`), `recover()`, `pending()`.
  - Policy: the CLI auto-recovers. The TUI and the plain API refuse with `journal.Pending`. `use` re-raises it as `SwitchBlocked`, so `items._refresh` undoes the profile edit.
  - When the journal stays: a change that fails with an `Exception` before any step is in flight and before a late phase drops the journal (for example a prompt abort or a preflight refusal). So does any `SwitchBlocked`. Kills, Ctrl-C and crashes after mutation keep it.
  - No state file is left behind when there was none before.
- Recovery settles `pending` first.
  - `backup`: an unreferenced partial takeover run is deleted. It only holds copies of folders that were not changed.
  - `remove`: a missing path drops its record. A half-removed copy is set aside.
  - `install`: an exact link or copy is recorded. Anything else is set aside.
  - `put-back`: a partial copy is set aside.
  - `adopt`: a `copy` stage that was cut short drops the partial copy. The original is still whole. A `delete` stage finishes deleting the original, whose copy is complete. Overwrite staging goes through fix-6's `adopt._clean_leftovers`, and kept leftovers are reported.
  - "Set aside" means moved to a fresh backup run under `<target>/<name>`. Nothing is deleted.
- Recovery then handles each operation:
  - `use` in the `prepare` phase is rolled back: nothing of the active set changed. In the `apply` phase it is finished. If the new profile cannot be activated, it falls back to the previous profile, then to no profile with respec's skills removed. `--rollback` reverses the order.
  - `restore` is finished with `overwrite=True` (entries in the way are backed up first). It can be rolled back only in `prepare`.
  - `adopt` and `links`: leftovers are cleaned, then `switch.align_links`.
  - `update` and `add` are rolled back in `copy` and finished in `refresh`.
  - `install` is kept if `profile.yaml` loads, otherwise removed (fetched content only).
- `switch`:
  - `use` is split into a preflight and a journaled `_switch`.
  - New helpers `remove_step` and `_install_step`.
  - `_take_over` marks the backup run.
  - `link_skills` and `relink_lasting` are journaled.
  - New `align_links`.
  - The error after an `OSError` now says that the next changing command finishes the switch.
- `restore._apply` is journaled, with put-back steps. `layers._repair_links` is journaled. `sources.update`, `add` and `install_profile` are journaled. `_replace` restores `.old` when the live folder is missing instead of deleting it (a data-loss hazard on interruption). `items.commit`, `add`, `remove` and `layers.set_active` call `ready()` first.
- CLI:
  - Every command attaches `interrupted-operation` warnings in JSON and prints them on stderr. The fields are `operation`, `outcome` (`finished`, `rolled-back` or `pending`), `message`, `set_aside` and `profile`.
  - `status` prints an "Interrupted: ..." line.
  - New `respec recover [--rollback] [--json]`, whose JSON gives `active_profile`, `recovered` and `warnings`.
  - Running `restore` again finishes an interrupted restore.
  - `_SwitchRun.finish` now reports the real `active_profile` when a switch is refused.
- TUI and Sync:
  - `SyncReport.interrupted` is new. While a change waits, Sync shows only that change, with Finish and Roll back.
  - The main screen shows a feedback notice.
  - Every core change refuses through `ready()`.
- Docs: the README has an "Interrupted changes" section, the new warning type and `recover`. The shipped `respec/SKILL.md` has the same.

## Acceptance criteria → evidence

| Criterion                                                                                                   | Independent test / evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Switch journaled in `state.json` before mutating (plan, progress)                                           | `test_interrupted_switch_is_journaled_and_reported_by_status` reads `state.json` after a crash: `operation`, `profile` and `previous` are present. The journal is written by `begin` before `refresh_shipped` and takeover. Each step is recorded in `pending` before it runs.                                                                                                                                                                                                                                                                                                               |
| Interrupted switch → next command resumes or rolls back to a consistent state (exactly one profile's items) | `test_switch_interrupted_at_every_step_recovers_consistently[None,a]` crashes at every boundary of a first and a later switch, then runs `recover --json`. Each case checks for no journal, exactly the active profile's skills plus the user entry, all records managed, and the user entry kept. Also `test_any_changing_command_recovers_first_and_reports_it`, `test_recover_rollback_activates_the_previous_profile`, `test_a_partial_copy_left_by_an_install_is_set_aside_not_deleted` and the real-kill `test_killed_switch_is_finished_by_the_next_command` (`shipped`, `os._exit`). |
| `status` reports an incomplete switch clearly                                                               | Same first test: JSON `interrupted-operation` warning with `outcome: pending`; the text has "Interrupted: The switch to profile 'b' ... was interrupted". status leaves the journal in place.                                                                                                                                                                                                                                                                                                                                                                                                |
| Extra: every switching mutation covered (restore, repair_links, adopt, links, update, add, install)         | `test_restore_interrupted_at_every_step_is_finished`, `test_restore_command_finishes_an_interrupted_restore`, `test_a_restore_that_removed_skills_cannot_be_rolled_back`, `test_layer_repair_links_interrupted_at_every_step`, `test_adopt_interrupted_at_every_step_loses_nothing`, `test_relink_of_lasting_skills_interrupted_is_finished`, and in `test_sources.py` `test_update_interrupted_at_every_step_rolls_back_or_finishes` (both outcomes seen), `test_add_from_git_interrupted_at_every_step_...` and `test_profile_install_interrupted_at_every_step`.                          |
| Extra: TUI and Sync report and block                                                                        | `test_tui_refuses_to_switch_while_a_change_waits` (the state file is byte-identical afterwards) and `test_tui_sync_reports_and_resolves_an_interrupted_switch[finish, rollback]`.                                                                                                                                                                                                                                                                                                                                                                                                            |
| Extra: JSON vocabulary and no nulls                                                                         | `test_interrupted_warnings_have_no_undocumented_nulls`; `tests/test_json_contract.py` green.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Extra: refused `use --json` reports the real active profile                                                 | `test_refused_use_reports_the_profile_still_active`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Extra: edits are recovered first                                                                            | `test_editing_the_profile_being_switched_to_finishes_the_switch_first`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

TDD: the first journal tests were red before the integration (no checkpoints: `StopIteration` while looking for `install:start`). A mutation check disabled `_settle_pending`, and 4 tests went red (both use matrices, the partial-copy test and relink), so the matrices detect a missing settlement. Two tests were written after their code: the TUI test and the edit-recovery test.

## Verification (fresh, at head)

- `uv sync --frozen`: ok. `uv lock --check`: "Resolved 28 packages".
- `uv run pytest -q`: **485 passed** in 123.6s. The base had 462. Existing tests are unchanged except `test_sources.py`, which only gained additions.
- `uv run black --check src tests`: 40 files unchanged.
- `npx prettier --check README.md "src/respec/**/*.md"`: clean. This report is Prettier-formatted.
- Manual smoke against real defaults (shipped skills): a real `os._exit` during `use b`. `status` shows the Interrupted line, `recover` says "Finished the switch to profile 'b'.", and `status` then shows b fully linked in all folders.

## Concerns

- Recovery is automatic only in commands that change skills. Commands that only edit `profile.yaml` (`profile new`, `layer add`/`rm`/`add-skill` on an inactive profile) warn that the change is pending but do not recover it.
- `adopt` and `links` cannot be rolled back: choices already made stay, and `--rollback` reports "finished". A restore can be rolled back only before it removes skills.
- `items.remove` deletes the skill folder after the refresh, outside any journal. A crash there leaves an orphan profile folder; no data is lost.
- A `sources.add` interrupted in `copy` rolls back by dropping the journaled skill names from `profile.yaml`. These names were checked not to exist in the profile before the add.
- The concurrent-process lock is excluded by the ticket. The journal assumes one respec process at a time.
- Partial takeover backup runs are deleted on recovery, never kept. They only copy folders that were not yet changed.
