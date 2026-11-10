# t002 implementation run 2 (fix round 1)

- Ticket: 002 "Profile switching: use and status"
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t002`
- Branch: `codex/respec-v1-t002`, previous head `134a0e6`, new head `1d2f486`
- Input: `runs/t002-review-1.md` (B1 blocking; N1, N2 non-blocking)
- Status: DONE

## Changes (`src/respec/switch.py`, `tests/test_use_status.py`)

- B1, state truthfulness: `use()` saves `state.json` after every removal and
  after every install, so each path respec creates is recorded before the next
  step can fail. Any `OSError` during removal or install is saved and then
  raised as a `RespecError`, which the CLI prints as `error: ...` with exit 1
  and no traceback. The message says no profile is active and that the next
  `respec use` removes the recorded items.
- B1, `_install()`: `FileExistsError` is re-raised and never falls back to a
  copy. If the copy fallback fails, the partial copy is removed before the
  error is raised.
- B1, aliased targets: preflight resolves each target folder. Targets whose
  folders resolve to the same real directory (for example `~/.claude/skills`
  symlinked to `~/.agents/skills`) get each skill once, under the first such
  target in profile order. The recorded-path conflict check now compares
  real paths (parent symlinks resolved), so an item recorded through one alias
  is recognised through the other.
- N2: if a takeover backup fails, the partial backup run folder is deleted,
  nothing is recorded, and a `RespecError` ("could not back up ...; nothing
  was changed") is raised before any target is touched.
- N1 is not fixed. Detecting edits in copy-mode items needs content hashes in
  state plus a backup or adopt decision, which belongs with tickets 004 and 005.

## Regression tests (each failed on `134a0e6`, passes now)

| Test                                                                                                                     | Failure on old head                             |
| ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- |
| `test_targets_sharing_one_real_folder_are_installed_once_and_tracked`                                                    | `use a` exit 1 with raw `FileExistsError`       |
| `test_failed_install_is_reported_and_earlier_installs_stay_tracked` (read-only `agents` folder: link and copy both fail) | raw `PermissionError`, first install unrecorded |
| `test_failed_backup_leaves_no_partial_backup_and_no_changes` (unreadable file in a folder being taken over)              | raw `shutil.Error`, no `back up` message        |

The second test also checks that a following `use b` empties both former
folders, which covers the reviewer's "later switch removes everything" point.

## Verification

- `uv run pytest -q`: 56 passed.
- `uv run black --check .`: 14 files unchanged.
- `npx prettier --check README.md`: clean.
- Reviewer scenario through the real CLI in scratch homes, with
  `~/.claude/skills` linked to `~/.agents/skills`: `respec use a` exited 0
  and installed one item. `respec use b` removed it, leaving
  `~/.agents/skills` empty.

## Concerns

- In the aliased setup, `status` lists the shared item under the first target
  only, and both folders are backed up on takeover (duplicate content, harmless).
- If the alias symlink itself is later removed by the user, the recorded path
  disappears and the item in the real folder becomes unknown (ticket 004).
- If `save_state` itself fails inside the error handler, that `OSError` still
  surfaces raw. Journaling and recovery are ticket 003.
