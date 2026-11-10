# fix-1 implementation run 1

- Branch: `codex/respec-v1-fix-1` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-1`)
- Base: `60224c7af58897549aac1253b7a49996833c1733`
- Head: `ba249cd`
- Status: DONE

## Root cause (systematic-debugging)

I reproduced F1 with the integration check's script
(`.../scratchpad/f1/test_f1_repro.py`) and with new CLI-level tests.

- `unknown.is_managed` returned `os.path.lexists(path)` for `mode == "copy"`.
  A copy that was replaced or edited therefore still counted as managed. It was
  never reported as unknown, and `status` listed it under `items`.
- `switch._remove` deleted any existing copy-mode path (`shutil.rmtree`). It did
  not check that the path still held what respec had copied.

## Option chosen: treat it as unknown (`replaced`), not back it up automatically

An edited or replaced copy now becomes an unknown entry with `replaced: true`,
which is exactly how 004 already handles a replaced symlink. Why:

- It reuses the whole 004 flow unchanged. `status` lists it, a
  non-interactive `use` refuses, a terminal asks per entry,
  `--unknown add|backup|keep` and `respec adopt` resolve it, and
  `_forget_replaced` drops the stale record after the choice.
- Spec decision 5 and the user story ask for the content to be listed and
  offered a choice (adopt, back up, keep), not only backed up. Automatic
  backup would skip the `add` and `keep` choices, and it would also bring
  back a second removal path that 004 had just removed.

## Changes

- `src/respec/state.py`: `Installed` gains an optional `digest`, written to
  state.json only for copies. Records without a digest still load, and the
  schema docstring is updated.
- `src/respec/unknown.py`: new `digest(path)`, a SHA-256 over sorted relative
  names, file bytes and symlink targets, with no symlinks followed.
  `is_managed` for copies now requires a recorded digest that matches the
  current content. Docstring updated.
- `src/respec/switch.py`: `use` records `digest` for each copy-mode install.
  `_remove` now first checks `unknown.is_managed` and leaves any path that no
  longer holds what respec created. This also replaces the dead
  "recorded symlink was replaced" branch (cross-ticket item 5) and makes the
  symlink unlink go through the same check.
- `README.md`: unknown entries now explicitly include a replaced symlink and a
  copy whose content was edited or replaced. The claim "Nothing is removed
  before it is copied into a profile or a backup" is now accurate.
- `tests/test_adopt.py`: four tests in a new section, with the
  `activated_as_copy` fixture (copy installed through `use` with `os.symlink`
  refusing).

The optional pruning of `state.unmanaged` was not done. It is not in this code
path: `folder_report` already filters out missing paths when it reads, and
pruning would make `status` write state.

## Criterion -> evidence

| #   | Criterion                                                          | Evidence                                                                                                                                                                                                                                            |
| --- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Modified copy never deleted silently; goes through the 004 choices | `test_replaced_copy_blocks_switch_and_is_not_deleted` (`use b` exits 1, lists the path, foreign content intact, profile stays `a`); `test_edited_copy_is_backed_up_before_the_switch_removes_it` (edit -> `--unknown backup` -> content in backups) |
| 2   | `status` does not list modified/foreign copy as managed            | `test_replaced_copy_is_reported_as_unknown_not_as_managed` (`items == []`, unknown `tdd` with `replaced: true`)                                                                                                                                     |
| 3   | Unmodified copies still removed/replaced normally                  | `test_unmodified_copy_stays_managed_and_is_replaced_on_switch`; existing `test_switch_removes_copied_items_too` still passes                                                                                                                        |
| 4   | Regression tests fail on 60224c7, pass after fix                   | With `src/` stashed back to 60224c7: 3 failed (items listed as copy; `use b` exit 0; backups `{}`), 1 passed (criterion 3 test, expected). With the fix: all pass                                                                                   |
| 5   | README claim accurate                                              | README updated; removal now only touches paths `is_managed` confirms, and anything else is unknown and goes through add/backup (both copy before removal) or keep                                                                                   |

## Verification

- `uv run pytest -q` -> `114 passed`
- `uv run black --check src tests` -> `21 files would be left unchanged`
- `npx prettier@3 --check README.md` -> `All matched files use Prettier code style!`
- `git diff --check` -> clean
- The integration repro script, run against the worktree:
  `use b exit 1 ... cannot switch to profile 'b' ...`,
  `tdd exists after switch: True`, and status lists `tdd` under `unknown`
  with `items: []`.
- Entry point: the tests drive the real CLI through Typer's `CliRunner`. A live
  shell run of the copy fallback was not done, because forcing symlink failure
  outside the test harness would require monkeypatching.

## Concerns

- Copy records written before this change have no `digest`, so they count as
  unknown (`replaced`) and need a one-time choice. This is the safe default.
  Only pre-release dev states are affected.
- `is_managed` now hashes each copy's contents on every `status` and `use`.
  That is fine for skill-sized folders.
- If ticket 007's `source.digest` lands, its algorithm could be aligned with
  `unknown.digest`. They are independent today.
