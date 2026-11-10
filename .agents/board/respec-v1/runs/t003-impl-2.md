# t003 implementation 2: fix round 1

- Status: DONE
- Branch: `codex/respec-v1-t003`, worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`, not rebased
- Range: `a763a63..c7f460c`, one commit, on base `3e563b6`
- Files: 12. Source: `journal`, `sources`, `items`, `layers`, `cli`, `restore`, `state`, `profiles`. Docs: README. Tests: `conftest`, `test_journal`, `test_sources`.

## Blocking fixes

| Finding                                                                                                                 | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Red-first reproduction, then green                                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1: add rollback deleted a folder the user already had                                                                  | `sources._add` journals each skill under `created` before `add_local` copies it, and only when its folder does not exist yet. `_recover_add` removes only those skills, from `profile.yaml` and from disk.                                                                                                                                                                                                                                                            | `test_interrupted_add_never_deletes_a_folder_it_did_not_create` (injected failure at `phase:copy`); `test_killed_add_never_deletes_a_folder_it_did_not_create` (real SIGKILL). Both were red before the fix with `FileNotFoundError`: the folder had been deleted. |
| B2: update rollback restored a stale `.old` over local edits                                                            | `_replace` journals `swaps` (the skill and the live folder's digest) before anything is made, and `fetched` (the incoming digest). `_recover_update` puts back only journaled swaps whose `.old` still has the recorded digest. A live folder that is not the fetched one is set aside, never deleted. Other `.old` folders are kept and named in the message. `_replace` now refuses a skill that has a foreign `.old` (a row error) instead of deleting the folder. | `test_interrupted_update_never_restores_a_stale_old_copy` (injected) and `test_killed_update_never_restores_a_stale_old_copy` (SIGKILL). Both were red: `'stale' != 'USER-EDIT'`.                                                                                  |
| B3: update killed between `save_profile` and the refresh phase was reported as rolled back while `profile.yaml` kept v2 | The update journal records `profile_digest` (sha256 of `profile.yaml` bytes) at begin. Recovery treats a changed `profile.yaml` as committed and rolls forward: it deletes the journaled `.old`, then refreshes and links. The outcome is `finished` ("profile.yaml already recorded the new commits"). A `profile-saved` checkpoint was added.                                                                                                                       | `test_update_killed_after_saving_profile_yaml_is_finished_consistently` (SIGKILL right after `save_profile`). It was red: the files were back at v1 while the yaml said v2.                                                                                        |

## Non-blocking fixes

- **N1:** while recovering an adopt overwrite cut short in its copy stage, any `.<skill>.respec-new` or `.respec-old` of that skill that fix-6's `_clean_leftovers` keeps is moved to a backup run and listed in `set_aside`. `_overwrite` refuses to start while these exist, so any that exist now are this step's own. A retry is no longer blocked.
  - Test: `test_staging_folders_of_a_cut_overwrite_are_set_aside_not_left_blocking`.
  - Test: the SIGKILL `test_adopt_killed_at_every_step_loses_nothing` retries the remaining choices after each kill.
- **N2:** the outcome wording is now truthful.
  - adopt: the entry in flight is reported `rolled-back` when its copy was cut short, and the message says the entry still waits for a choice.
  - A links change, such as a layer repair or an edit, is reported `rolled-back` when `profile.yaml` is still byte-identical ("had not been changed yet").
  - `--rollback` on a change that cannot be undone says it was "settled instead".
  - Test: `test_a_repair_cut_before_saving_profile_yaml_says_rolled_back`. The repair and adopt matrices now check that the outcome matches the state.
- **N3:** `items.commit` (`enable`, `disable` and layer changes through it) and `layers.set_active` now open a `links` journal before `profile.yaml` is saved, but only when the profile is active. A nested refresh records its `switch`.
  - Test: `test_a_disable_killed_after_saving_profile_yaml_is_put_in_line` (SIGKILL; `status` reports pending, then `recover` finishes and leaves a consistent state).
- **N4:** rolling back a `use` that was cut short in `prepare` now runs `refresh_shipped`.
  - Test: `test_a_switch_cut_while_refreshing_shipped_skills_heals_them`.
- **N5:** `state.save_state` and `profiles._write` now write the temp file, flush and fsync it, rename it, then fsync the folder. This uses the new `state.write_durably` and `state.sync_folder`. There is no test, since power loss cannot be simulated.
- **N6:** while a restore is interrupted, `respec restore <other backup>` is refused. The same restore, or no argument for a takeover restore, finishes it.
  - Test: `test_restore_of_another_backup_waits_for_the_interrupted_one`.
- **N7:** a new shared `killed` fixture in `conftest.py` runs the CLI in a child process that SIGKILLs itself at a named checkpoint, at the Nth checkpoint, or right after the Nth `profile.yaml` write. The child keeps the `shipped` marker semantics.
  - New SIGKILL matrices over every step boundary: `test_update_killed_at_every_step_is_consistent` (both outcomes seen; a later update always reaches v2), `test_add_from_git_killed_at_every_step_keeps_a_hand_placed_folder` and `test_adopt_killed_at_every_step_loses_nothing`. Each covers 6 or more boundaries.
  - These are added to the existing in-process `BaseException` matrices.
- **N8:** for an unknown `operation`, `recover` now explains that `--rollback` discards it, and `recover --rollback` drops the journal and reports `rolled-back`. A malformed journal (`KeyError`, `TypeError` or `ValueError`) gives a clear `RespecError` instead of a traceback.
  - Test: `test_an_unknown_journal_can_be_discarded_with_rollback`.
- **Docs:**
  - The README "Interrupted changes" section is rewritten. It gives the rules for each operation, says a rollback only touches what that run made, and covers the `.old` refusal, the fsync, the restore guard and the unknown-journal discard. It also documents the orphan-folder limit of `respec remove`.
  - The `journal.py` docstring is updated to match.

## Verification (fresh, at c7f460c)

- `uv sync --frozen`: ok. `uv lock --check`: "Resolved 28 packages".
- `uv run pytest -q`: **499 passed** in 137s, against 485 before the round. After the last test-only lint fixes, the edited tests were rerun and are green.
- `uv run black --check src tests`: 40 files unchanged. `npx prettier --check README.md "src/respec/**/*.md"`: clean.
- `uvx pyflakes` on the changed files: clean, apart from the `handler` redefinition pattern that was already in `cli`/`tui`.

## Concerns

- The orphan folder that `respec remove` can leave is documented rather than journaled.
- `update` now refuses a skill that has a foreign `.<skill>.old` until the user moves it away. The old code deleted it silently.
- The fsync adds a small cost to every `state.json` write. Each switch step still does about two writes per item.
- The tests for N1, N3, N4, N6 and N8 were written alongside their fixes, not red-first. Only the B1 to B3 tests were red first.
