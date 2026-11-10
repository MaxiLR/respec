# fix-5 implementation 5: review round 4 fixes (B3, adopt rollback data loss)

- Status: DONE
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Branch: `codex/respec-v1-fix-5` (no rebase)
- Head: `46aea65bc11a273a22f07a4f02472386d193a857` (on top of `c044824`, not
  pushed)
- Input: `runs/fix-5-review-4.md`, round 4 under the engineer's standing
  preference.

## Changes (`src/respec/adopt.py`, plus a one-parameter change in `switch.py`)

### B3

`_undo_adds` has been rewritten around a new `_put_back(resolution, copy)`.
`_put_back` returns True only when the original is verifiably back:

- **The original path holds respec's symlink to the profile copy.** The link
  is removed. For a folder entry, the copy is moved back with `shutil.move`.
  For a symlink entry, the symlink is recreated from the recorded
  `readlink`. It is then verified as a real folder (with the copy gone) or
  as the same symlink.
- **The original path holds a real folder with the same `unknown.digest` as
  the copy.** This happens when respec copied it in copy mode. For a folder
  entry, that folder counts as the restored original. For a symlink entry,
  respec's copy is replaced with the recreated link. The content is still in
  the profile copy at that point.
- **The original path is empty.** The copy is moved back, or the link is
  recreated.
- **The original path holds anything else.** Nothing is touched, and the
  result is False.

The caller deletes the profile copy only after `_put_back` returns True, and
only if the copy still exists after the move. Any exception, or a result of
False, keeps the copy. The other records are then handled as follows:

- **`profile.yaml`.** If every entry was restored, the exact loaded bytes are
  written back with `restore_profile(before)`. Otherwise `before` is saved
  with the kept skills still listed as `{enabled: true}`.
- **`state.json`.** Records for the restored paths are dropped, and so is
  respec's link or copy record. The records those paths had before the adopt
  are put back. Kept entries keep their records, which stay consistent
  because the profile still lists them.
- **Error message.** It gains notes. For each kept copy:
  `could not put <original> back; its content is kept in profile '<p>' at <copy>`.
  For each backup made earlier in the same run:
  `<path> was backed up to <backup> and removed earlier in this run`.
  Backups are reported, not undone. The user chose them, and a backup is a
  complete copy.

### "cannot adopt"

`switch.refuse_layer_conflicts(profile, action="switch to")` now takes an
`action` argument, and adopt passes `"adopt into"`. The message reads
`cannot adopt into profile 'work': ...`.

The module docstring of `adopt.py` states the rollback invariant.

## Regression tests (`tests/test_layer_repair.py`)

The fixture `two_targets` is an active profile on claude-code and agents.
The agents folder is empty and set to `chmod 555`, so the relink fails after
claude-code is linked. The permissions are restored at teardown.

Red first (all 3 failed before the fix):

| Test                                                        | Red reason                                                           |
| ----------------------------------------------------------- | -------------------------------------------------------------------- |
| `test_adopt_relink_failing_partway_never_loses_the_content` | It reproduces the reviewer's scenario: `precious` was found nowhere. |
| `test_adopt_refusal_says_cannot_adopt`                      | The message said "cannot switch".                                    |
| `test_adopt_failure_reports_backups_made_earlier`           | The backup was not mentioned.                                        |

After the fix, the partway test checks that:

- the original is a real folder with its content;
- no state record remains;
- `profile.yaml` does not list it.

These tests were added after the fix as extra coverage, so they were green
when first run:

- `test_adopt_relink_failing_in_copy_mode_keeps_the_original_unmanaged`. With
  `os.symlink` refused, respec's copy at the original path is accepted as the
  original by digest. Its state record is dropped, so the next `use` will not
  delete it. The profile copy and entry are removed.
- `test_adopt_keeps_the_copy_when_the_original_path_holds_something_else`.
  The original path is taken by unrelated content. The profile copy is kept
  and listed as enabled, the error names its path, and the foreign content
  is untouched.

The round-3 test `test_adopt_rolls_back_an_add_when_the_relink_is_refused`,
which covers folder and symlink entries, still passes.

## Verification (fresh, head 46aea65)

| Gate                               | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `281 passed in 47.16s`                       |
| `uv run black --check src tests`   | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

## Concerns

- After a partial switch failure, `switch.use` itself leaves no active
  profile, and records the links it made for other skills. This was already
  true before this change. The rollback only undoes the adopt.
- fix-6's rebase of `adopt.py` must keep all of the following:
  - `_put_back` and `_undo_adds` with their rule that the copy is deleted
    only after the original is verified;
  - `Resolution.link`;
  - the early guard `refuse_layer_conflicts(before, "adopt into")`;
  - the notes in the error.
