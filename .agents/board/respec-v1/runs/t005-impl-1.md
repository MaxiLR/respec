# t005 impl 1: Restore backups and release ownership

- Status: DONE
- Branch: `codex/respec-v1-t005` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t005`)
- Base: `77d592c6537106cac69736e2983f6690e60520a7`
- Head: `139fe85`

## Changes

- `src/respec/restore.py` (new): `list_backups`, `restore`, `RestoreBlocked`.
  - Plan (no changes): without `<backup>`, each owned folder group gets the backup
    of its earliest takeover. If the folder did not exist then, it is removed when
    it ends up empty. With `<backup>`, each target folder in that run is restored.
    Other owned folders only lose respec's items.
  - Backup entries respec created are skipped. Symlinks into `profiles/` are
    always skipped. Copies are skipped when they match a recorded copy digest or
    any profile's same-named item. That copy check only runs for backups taken
    after the folder was already owned: the earliest takeover for owned folders,
    or the oldest run holding the folder once it has been released.
  - Conflicts: an entry respec does not manage that differs from the backup or
    is missing from it. This covers unknown entries, edited or replaced copies,
    and kept entries whose name exists in the backup. Unknown conflicts go to
    `on_unknown`, which reuses `adopt.resolve`. Kept entries missing from the
    backup stay in place. If anything still conflicts, `RestoreBlocked` is
    raised and nothing changes, unless `overwrite`. With `overwrite`, the
    conflicts are backed up through `adopt.resolve(..., "backup")` first.
  - `_apply` is the single place that mutates: set aside, deactivate, remove
    managed items (state saved after each), copy missing entries, clear state.
    On `OSError`, `state.json` stays true to disk with ownership kept, and a
    rerun finishes the restore.
- `src/respec/cli.py`: appended the `restore` command
  (`[<backup>] [--list] [--unknown add|backup|keep] [--overwrite] [-p] [--json]`).
  A terminal asks per unknown entry, then confirms the overwrite. Other edits:
  one import line.
- `src/respec/switch.py`, `src/respec/adopt.py`: renamed `_new_backup_run`,
  `_utc_now`, `_remove` to the public `new_backup_run`, `utc_now`,
  `remove_installed`. This is a rename only. adopt and restore use them.
- `README.md`: usage line and a restore paragraph.
- `tests/test_restore.py` (new): 17 tests.

## Acceptance criteria -> evidence

| Criterion                                                                                                     | Tests                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Lists backups; restores the chosen backup (default: earliest takeover) per target after removing respec links | `test_list_shows_takeover_backup_with_its_targets`, `test_restore_named_backup_restores_the_folders_it_holds`, `test_default_restore_of_shared_folder_uses_its_first_takeover`, `test_unmodified_copy_is_removed_by_restore`                                                                                                                                                                                                            |
| Restored folders match the backup exactly; state cleared, no active profile                                   | `test_restore_returns_every_folder_to_its_takeover_contents_and_releases` (populated claude-code and agents with a file, a folder and a user symlink, A(claude-code, agents) to B(oh-my-pi, claude-code), then restore; non-following tree snapshots equal the originals and the new oh-my-pi folder is gone), `test_original_later_adopted_into_a_profile_comes_back`, `test_failed_restore_keeps_state_true_to_disk_and_can_be_rerun` |
| Refuses to overwrite unknown entries without adopt or explicit confirmation                                   | `test_restore_refuses_to_overwrite_an_unknown_entry_and_changes_nothing`, `test_restore_with_unknown_backup_moves_entry_aside_then_restores_exactly`, `test_kept_entry_that_differs_from_backup_needs_overwrite`, `test_interactive_restore_asks_before_overwriting`, `test_edited_copy_is_never_deleted_silently`                                                                                                                      |

Orchestrator notes, with their tests:

- Shared-folder double backup that contains respec links:
  `test_restoring_a_backup_holding_respec_links_does_not_recreate_them`.
- The same case with copy-mode installs:
  `test_restoring_a_backup_holding_respec_copies_does_not_recreate_them` and
  `test_after_release_a_later_backup_still_leaves_respec_copies_out`.
- No run-name collisions within one second:
  `test_overwrite_backup_run_never_reuses_a_run_from_the_same_second`.
- A fixed clock produces `20261109T120000Z` and `20261109T120000Z-2`.

Mutation checks: I disabled each of these in turn and confirmed the named tests
fail.

- respec-link skip
- conflict refusal
- release
- pre-respec copy rule
- copy fallback for unowned folders

## Verification

- `uv run pytest -q`: 131 passed (114 at base, plus 17 new)
- `uv run black --check src tests`: 23 files would be left unchanged
- `npx prettier@3 --check README.md`: all files use Prettier code style
- Smoke test with temp homes, `respec restore --list`: prints `No backups.`

## Concerns

- Default restore: "earliest takeover" means each folder group's own first
  takeover backup. Targets taken over in different runs each get their own
  pre-respec state. A named run restores only the targets it holds.
- Kept (unmanaged) entries that are missing from the backup stay in place, so a
  folder equals the backup plus those entries. They are never deleted silently.
- Parent folders that respec created for a new target (for example
  `~/.omp/agent`) stay. Only the empty skills folder is removed.
- Hidden entries that are missing from the backup are left alone, consistent
  with unknown detection.
- Renaming the private switch helpers could break a parallel branch that calls
  the old names. At base, adopt.py was the only caller.
- Ticket 003 can wrap `_apply`. The adopt-flow handler runs before it, through
  `adopt.resolve`.
