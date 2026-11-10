# fix-5 implementation 3: review round 2 fixes

- Status: DONE
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Branch: `codex/respec-v1-fix-5` (no rebase)
- Head: `f38b0d6e30e86de191255a7d81e4d1b7c30ba675` (on top of `a50e03d`, not
  pushed)
- Input: `runs/fix-5-review-2.md`

## Changes

- **B1 (profile install warns)**
  - Warnings no longer depend on `load_profile` alone.
    `profiles._touched` records every profile folder that a command reads or
    writes:
    - `load_profile` (it records before parsing)
    - `save_profile`
    - `restore_profile`
  - Both writers now go through one atomic `_write` helper, which records the
    folder. Any path that creates or changes a profile is therefore covered,
    including `create_profile`, `sources.install_profile` (built with
    `parse_profile` and then saved), add, update and the rollbacks.
  - `peek_warnings` and `take_warnings` reread each touched folder from disk
    with `_read_folder` and report its conflicts as the command left it.
  - Folders that no longer parse are skipped.
  - Scanning every profile on disk would also warn about profiles the command
    never touched, so I did not do it. Tracking reads and writes at the
    single reader and the single writer means no code path can bypass the
    check.
- **N1 (`disabled` for every layer change)**
  - `layers._apply` fills `change.disabled` with every skill that was enabled
    before the change and is disabled after it. `repair` keeps its explicit
    list.
  - `layer use --json` now reports `disabled: ["a"]`, and the text output
    prints `disabled 'a'`.
  - The README says that every `respec layer` change lists what it disabled.
- **N2 (`loaded_text` hazard)**
  - `Profile.loaded_text` is now `field(init=False, ...)`, so
    `dataclasses.replace` never copies it. `_read_folder` sets it on the
    loaded instance only, through `object.__setattr__` on the frozen
    dataclass.
  - An edited copy has `loaded_text=None`, so `restore_profile(copy)` writes
    the copy's own data. The docstring states this rule.
- **N3**: `save_profile` and `restore_profile` share the `_write` helper.

## Regression tests (red first)

All three failed before the fix, for these reasons:

- `tests/test_sources.py::test_profile_install_of_conflicted_profile_warns`
  installs a conflicted modpack from a `file://` bare repo. It checks for a
  stderr repair hint, and it checks that JSON `warnings` is
  `[("imp2", "design-principles", ["a", "b"])]`. Red: stderr was `''`.
- `tests/test_layer_repair.py::test_layer_use_json_lists_the_skill_it_disabled`.
  Red: `disabled` was `[]`.
- `tests/test_layer_repair.py::test_restoring_an_edited_copy_writes_the_copy_not_the_loaded_bytes`.
  Red: the copy rolled back to the loaded bytes.

All earlier tests still pass.

## Verification (fresh, head f38b0d6)

| Gate                               | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `270 passed in 46.95s`                       |
| `uv run black --check src tests`   | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

## Concerns

- Now that a layer change lists every skill it disabled, `layer disable` on a
  group prints one `disabled '<skill>'` line per skill. That output is
  accurate but longer than before.
- The round-1 judgments still stand: unrelated `enable` and `disable` are
  refused while the active profile has a conflict, and the TUI does not show
  warnings. `switch.py` still has the 11-line overlap with fix-6.
