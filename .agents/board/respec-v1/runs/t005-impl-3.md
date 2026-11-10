# t005 impl 3: fix round 1 (review t005-review-1)

- Status: DONE
- Branch: `codex/respec-v1-t005` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t005`)
- Base: `eeca3cb13e94608ea86451782c87a96f32810adb`. Not rebased.
- Previous head: `02458e6`
- New head: `b0fd1fe`

## Findings and fixes

| Finding                                                                                | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Evidence                                                                                                                                                                      |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1: a named pre-respec run from an earlier ownership cycle dropped the user's original | Removed the position-based `pre_respec` logic, `_oldest_run_holding` and profile-name matching. `switch._take_over` now writes `<run>/manifest.json` with the items respec had installed in the folder when it was copied. The manifest is written only when there were such items, which is the case for an alias of an already-owned folder. Restore skips only symlinks into `profiles/` and copies whose digest matches that manifest. A run without a manifest has no skipped copies. Skipped entries are reported (`skipped` in JSON, `Skipped <path>` in human output). | `test_named_pre_respec_run_from_an_earlier_ownership_cycle_restores_exactly` reproduces the review's steps. It failed first with `assert {} == {'mine': ...}` and passes now. |
| N4: copy detection depended on current profiles                                        | Fixed by the same change: detection uses only backup-time facts.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | `test_restoring_a_backup_holding_respec_copies_does_not_recreate_them`, `test_after_release_a_later_backup_still_leaves_respec_copies_out`                                    |
| N1: permission-only changes counted as identical                                       | `_same` compares the content digest and the permission bits of every entry (lstat, links not followed).                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | `test_kept_entry_with_changed_permissions_is_not_identical`                                                                                                                   |
| N2: leftovers were not reported                                                        | Kept and hidden entries that the backup lacks are listed in `left` (JSON) and as `Left <path> in place: ...` (human output).                                                                                                                                                                                                                                                                                                                                                                                                                                                   | `test_kept_and_hidden_leftovers_are_reported`, `test_kept_leftover_is_named_in_human_output`                                                                                  |
| N5: test patched the private `_put_back`                                               | The test now chmods a backed-up file to 000 so a real copy fails. It asserts state matches disk, then reruns and gets an exact restore.                                                                                                                                                                                                                                                                                                                                                                                                                                        | `test_failed_restore_keeps_state_true_to_disk_and_can_be_rerun`                                                                                                               |
| N6: no coverage for modes, binary content or empty folders                             | `snapshot` now records modes and raw bytes. The fixture adds a 0755 script, a 0600 file, a binary file and an empty folder.                                                                                                                                                                                                                                                                                                                                                                                                                                                    | `test_restore_puts_back_modes_binary_content_and_empty_folders`, plus every exact-snapshot test                                                                               |
| N3: parents left behind                                                                | Accepted by the orchestrator. Unchanged.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | n/a                                                                                                                                                                           |

Mutation checks: I disabled each of these in turn and confirmed the named tests
fail.

- Permission comparison: `test_kept_entry_with_changed_permissions_is_not_identical`.
- Manifest copy skip: both respec-copies tests.

Earlier mutations from impl 1 (link skip, conflict refusal, release) still
apply.

## Files

- `src/respec/switch.py`: `BACKUP_MANIFEST` and `_record_backed_up_items`,
  called inside the takeover copy's `try`.
- `src/respec/restore.py`: planning rewritten around the manifest. Adds
  `_modes`, permission-aware `_same`, and `RestoreResult.skipped` and `.left`.
- `src/respec/cli.py`: restore output lists skipped entries and leftovers, in
  human and JSON form.
- `README.md`: restore paragraph updated.
- `tests/test_restore.py`: 22 tests (5 new; 3 updated).

## Verification

- `uv run pytest -q`: 154 passed
- `uv run black --check src tests`: 25 files would be left unchanged
- `npx prettier@3 --check README.md`: all files use Prettier code style
- `uv lock --check`: Resolved 28 packages

## Concerns

- Backup runs taken before this change have no manifest. Respec copies in such
  runs are restored as user content, so nothing is dropped. Links are still
  skipped.
- In ordinary takeovers the manifest file is absent, so existing backup layouts
  are unchanged. When present, the manifest sits at the run root, next to the
  target folders. It is never restored.
