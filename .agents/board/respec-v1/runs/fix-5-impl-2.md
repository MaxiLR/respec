# fix-5 implementation 2: review round 1 fixes

- Status: DONE
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Branch: `codex/respec-v1-fix-5` (no rebase)
- Head: `a50e03df41977ff35ec130bc88234430d4878c70` (on top of `da670cb`, not pushed)
- Input: `runs/fix-5-review-1.md`

## Changes

- **B1**
  - `layers.repair` now works on any exclusive layer, whether it is on or
    off. It uses `profiles.enabled_members`, disables the skills it does not
    keep with `with_enabled(..., False)`, and commits through the same
    `_apply` / `items.commit` path as before.
  - An additive layer returns the action `additive` ("Nothing to repair in
    ...: it is additive"). An exclusive layer with at most one enabled skill
    returns `nothing`, which now prints accurate text.
  - The `layer on` error still names `respec layer repair`, which now works.
    I dropped the redundant "(disable the others first)" suffix.
- **B2**
  - The sticky collector of conflicts is gone. `load_profile` now records
    only which profiles were read, as `(respec_home, name)` pairs.
  - `peek_warnings()` and `take_warnings()` reread those profiles through the
    internal `_read_profile` and compute the conflicts in their current
    state. Profiles that no longer load are skipped.
  - Stderr warnings and the JSON `warnings` field therefore describe the
    state the command left behind. `discard_warning` is removed.
  - CLI deduplication against an error message now uses the text of the
    printed error. `_fail` records it, and `_print_warnings` skips any
    conflict that error already explains.
- **Rollback bytes**
  - `Profile` gains `loaded_text` (`compare=False`, `repr=False`). It is set
    by `load_profile`.
  - New `profiles.restore_profile(profile)` writes those exact bytes back
    atomically. When `loaded_text` is unset, it falls back to
    `save_profile`.
  - Every rollback now uses it: `items.commit`, `items.add` undo,
    `items.remove`, `sources._forget` and `sources._restore`.
- **Documentation (N3)**
  - The README says that every object `--json` output has a `warnings` list,
    empty when nothing conflicts. It also describes the shape of each entry.
  - It says that `restore --list --json` is a bare list because that command
    reads no profile.
  - It documents that `repair` works on a layer that is turned off and that
    `--json` reports the disabled skills under `disabled`.
  - The `_print_json` docstring describes the same `warnings` behavior.

## Regression tests (red first, `tests/test_layer_repair.py`)

All six cases below failed before the fix (`6 failed, 24 passed`) and pass
after it:

- `test_repair_fixes_an_inactive_exclusive_layer_that_layer_on_refuses` (B1).
  It failed because repair printed "Nothing to repair" and changed nothing.
- `test_repair_of_additive_layer_says_nothing_to_repair_accurately` (B1
  wording).
- `test_resolving_the_conflict_another_way_leaves_no_stale_warning` (B2),
  run for `disable a`, `layer off design-principles` and
  `layer use design-principles b`. It checks that JSON `warnings` is `[]` and
  that stderr has no warning.
- `test_refused_change_restores_legacy_file_bytes` (rollback). A legacy
  `items:` file plus an unknown entry blocks the refresh. Both
  `layer add-skill` and `disable` are refused, and the file stays
  byte-identical afterwards. Before the fix, the rollback rewrote it.

All 23 tests from round 1 still pass.

## Smoke (scratch temp homes)

- `use work` with a conflict prints one error and no duplicate warning.
- `layer off design-principles --json` returns `"warnings": []`.
- After that, `layer on` is refused and names the repair command.
- `layer repair design-principles` keeps `a`, disables `b` and unlinks `b`.
- `layer on` then succeeds.

## Verification (fresh, head a50e03d)

| Gate                               | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `267 passed in 51.97s`                       |
| `uv run black --check src tests`   | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

## Concerns

- Each command that prints warnings rereads the profiles it loaded once more.
  The cost is small, since profile files are tiny.
- `sources.py` now gets the byte-exact rollback as well. It is outside the
  original file list, but the review asked for rollback of refused commands,
  and sources uses the same undo path. fix-6 does not touch `sources.py`.
- The non-blocking review findings N1, N4, N5 and N6 are unchanged and remain
  as judged in the review. N5 now matches on the printed error text instead
  of discarding entries from the collector.
