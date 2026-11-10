# fix-5 implementation 4: review round 3 fixes

- Status: DONE
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Branch: `codex/respec-v1-fix-5` (no rebase)
- Head: `c044824d1e01a1b699b39e57988fff725725317c` (on top of `f38b0d6`, not
  pushed)
- Input: `runs/fix-5-review-3.md`. This round runs past the two-round cap,
  under the engineer's standing preference recorded by the orchestrator.

## Changes

### B1: `adopt --add` into the conflicted active profile

All edits are in `src/respec/adopt.py` and are kept small for the fix-6
rebase.

- **Early guard.** This applies when an add can go to the active profile,
  that is when `profile_name` is unset or equals the active profile.
  - `adopt()` now asks `decide` about every entry before it applies any
    choice. It then replays the answers to `resolve`.
  - Interactive prompts come in the same order as before. All answers are
    collected before anything is applied.
  - If any answer is `add`, `adopt()` loads the active profile and calls
    `switch.refuse_layer_conflicts`. That is the same check `use` runs,
    renamed from `_refuse_layer_conflicts` to make it public. It raises
    `SwitchBlocked` with the same message and repair hint.
  - The refusal happens before anything is copied, deleted or written.
  - When there are no adds, the active profile is not loaded at all, so
    backup and keep behave exactly as before.
- **Defense in depth.** If `switch.use` still refuses after adds,
  `_undo_adds` runs and the error is re-raised. `_undo_adds` does four
  things:
  - It copies each added folder back from its profile copy, or recreates a
    symlink entry from its recorded `os.readlink` target. The target is
    stored in a new `Resolution.link` field, which is not in `to_dict`, so
    the JSON is unchanged.
  - It deletes the profile copy.
  - It restores `profile.yaml` byte for byte with `restore_profile(before)`.
  - It re-adds any `state.json` `installed` records of those entries that
    `_settle` dropped. This matters for entries that replaced a skill respec
    had installed.

### B2: `layer on` and `layer off`

These changes are in `layers.set_active`.

- Turning a layer off is always allowed.
- Turning a layer on is refused only when that layer itself has a conflict:
  `cannot turn layer 'X' on: <that layer's conflict message>`.
- Other layers' conflicts remain warnings.
- An on/off change never changes which skills are enabled, so it now saves
  the profile directly and skips the switch refresh. The refresh would
  otherwise be refused because of an unrelated conflict on an active
  profile. `LayerChange.active` is still reported.

## Regression tests (red first, `tests/test_layer_repair.py`)

All of these failed before the fix. The adopt tests failed because the
original folder had been deleted. The layer tests failed with the error
"cannot turn layer 'output-style' on: layer 'design-principles' ...".

| Test                                                                              | Covers                                                                                                                                                                                      |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_adopt_add_into_conflicted_active_profile_refuses_and_changes_nothing`       | Refusal with the repair hint. The original folder, the absent profile copy, and the `profile.yaml` and `state.json` bytes are all unchanged.                                                |
| `test_adopt_rolls_back_an_add_when_the_relink_is_refused`                         | `switch.use` is monkeypatched to refuse. A folder entry is copied back and a symlink entry is recreated with the same target. The profile copies are gone and the yaml bytes are unchanged. |
| `test_layer_off_of_another_layer_is_allowed_on_a_conflicted_profile[(), -p work]` | `layer off output-style` succeeds and warns about design-principles.                                                                                                                        |
| `test_two_conflicted_layers_can_each_be_turned_off_on_inactive_profile`           | On an inactive profile with two conflicted exclusive layers, both can be turned off.                                                                                                        |
| `test_layer_on_is_refused_only_for_its_own_conflict`                              | Turning an unrelated layer on and off works. `layer on design-principles` is refused with its own `(a, b)` message.                                                                         |

## Verification (fresh, head c044824)

| Gate                               | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `276 passed in 49.93s`                       |
| `uv run black --check src tests`   | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

## Concerns

- `adopt.py` now differs from base in `adopt()`, `_add` (it takes the
  `Resolution`), `_undo_adds` and `Resolution.link`. fix-6 rewrites
  `adopt.py`, so its rebase must keep three things:
  - the early call to `switch.refuse_layer_conflicts` when an entry is added
    to the active profile;
  - the rollback on a refused relink;
  - the rename of `switch._refuse_layer_conflicts` to
    `refuse_layer_conflicts`.
- The guard is not in `adopt.resolve`, which `use` and `restore` also call
  through their unknown-entry handlers:
  - `use` refuses a conflict before its handler runs.
  - `restore` releases ownership and does not relink, so it was left as is.
