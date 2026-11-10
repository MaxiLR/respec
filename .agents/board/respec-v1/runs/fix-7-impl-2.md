# fix-7 implementation 2: review 1 fixes

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-7`
- Branch: `codex/respec-v1-fix-7`
- Head: `b28c295`. The new commit sits on top of `04ee6d9` (no rebase).
- Not pushed. No PR. Board, ledger, spec and tickets were not edited. No
  guard denials.

## B1: null-only fields

- Rule: a field that does not apply is left out. It is enforced in one
  place, `cli._print_json` → `_without_nulls`, so every command follows it.
- Only these may be null, each meaning "none":
  - `active_profile` and `previous_profile`;
  - `same_as`;
  - a value under `restored` (a folder that did not exist at takeover).
- This removes the nulls from:
  - `resolved[]`: `profile`, `backup` and `replaced_copy`;
  - layer changes: `skill`;
  - `profile show`: `source`;
  - `update` rows: `error`, `latest` and similar;
  - the restore `backup` key.
- README and the shipped SKILL.md now state exactly this rule and the
  nullable list.
- Tests:
  - `tests/conftest.py` gains `null_fields` and an `assert_no_nulls` fixture.
    Its nullable list matches the README.
  - `test_json_contract.py::test_no_undocumented_nulls_in_any_local_command`
    covers 23 commands: profile new/list/show, status,
    add/disable/enable/remove, every layer command, adopt (list, add,
    remove), use, update, `update --check` and `restore --list`.
  - `::test_no_undocumented_nulls_in_failures_or_restore` covers the failures
    of use, adopt and restore, and a successful restore.
  - `test_sources.py::test_git_commands_print_no_undocumented_nulls` covers
    git add, `update --check`, update and `update --check` again.
- Red evidence:
  - the two local tests failed on `$.skills[0].source` and
    `$.resolved[0].profile` and others;
  - the git test failed on `$.skills[0].error` when the filter was
    disabled.
- One exact-shape test, `test_profile_list_show.py`, dropped
  `"source": None` from the expected output.

## B2: edited copy of a member of the conflicted layer

- Rule (minimal and safe): `layers.repair` falls back to `_repair_links`
  whenever the active profile's refresh is refused by `UnknownEntries`, with
  no exemption for names.
  - This is safe because `_repair_links` never touches an unknown entry.
    `switch.remove_installed` removes only paths that still hold what respec
    placed. `switch.link_skills` links only into free paths; a path held by
    an unmanaged entry is reported as `blocked` and left alone.
  - So the edited copy stays exactly where it is, with its state record, as
    an `unresolved` (replaced) entry for `adopt`. Add keeps the edit in the
    profile (for a disabled skill too), and remove backs it up.
  - Every other refusal (`SwitchBlocked` from a missing folder or a bad
    `config.yaml`) still changes nothing: `_apply` undoes `profile.yaml`
    before the error reaches `repair`.
  - Why this rule rather than relaxing adopt: it keeps fix-5's "adopt refuses
    a conflicted profile up front" rule and its three tests, and the change
    stays in one function.
- Tests:
  - `--keep b` (the edited member):
    `test_layer_repair.py::test_repair_keeping_the_edited_member_goes_ahead_and_the_copy_can_be_added`.
    The repair succeeds, `a` is unlinked and the edited copy is untouched.
    Then `adopt --add b` puts the edit into the profile and links it, and
    `use work` succeeds.
  - `--keep a`:
    `::test_repair_disabling_the_edited_member_leaves_the_copy_waiting`.
    JSON shows `disabled [b]`, `unlinked []` and `unresolved [b]`. The edited
    copy is untouched. `adopt --add b` keeps the edit in the profile copy
    (with `b` disabled, so not linked), and `use work` succeeds.
  - Both failed first (`fix7-red-b2.txt` in the scratchpad).
- Retargeted tests: these two encoded the refusal that B2 removes. Each now
  checks another preflight refusal and keeps its "nothing changed"
  assertions.
  - `test_repair_refused_by_switch_preflight_leaves_profile_unchanged` now
    uses a missing folder for the enabled skill `c`. It checks that
    `profile.yaml` and the links are unchanged.
  - `test_repair_that_would_unlink_an_edited_copy_still_changes_nothing` is
    now `test_repair_refused_for_another_reason_beside_an_edited_copy_changes_nothing`.
    It uses an invalid `config.yaml` while an edited copy is present. It
    checks that `profile.yaml` and `state.json` are byte-identical and that
    the copy is intact.
- README and SKILL.md describe the rule.

## N items

- N1 (change commands print no JSON on failure): not changed. It is
  documented, and the reviewer suggested a later ticket.
- N2: `global_skills.origin(respec_home, path, name)` is now shared by
  `status` and Sync. A link is judged by the folder it points into; a copy is
  judged by its name. Test:
  `test_global_skills.py::test_status_judges_a_link_by_what_it_points_into_not_its_name`.
  It was red with the old `switch.status`.
- N3: the two long `update` lines are split. The lines over 88 columns that
  remain in `cli.py` were already there at base.
- N4 (pre-existing, safe): not changed. Deleting a staged `.respec-new`
  automatically is a data-deleting rule change, outside this fix round.
- N5: `_repair_links` now wraps `OSError` and `RespecError`, including
  `LinkFailed` from `link_skills`, in "repair … did not complete … Profile
  keeps the repair". Test: `::test_repair_link_failure_says_the_repair_was_kept`.
- N6: the keep-name branch is now covered by the B2 tests, and the
  `LinkFailed` path by the N5 test. The inactive-profile branch of the
  fallback cannot be reached: `items._refresh` returns before switching when
  the profile is not active.

## Verification (fresh, at b28c295)

| Gate                                                                        | Result                            |
| --------------------------------------------------------------------------- | --------------------------------- |
| `UV_OFFLINE=1 uv sync --frozen`                                             | PASS (Audited 27 packages)        |
| `UV_OFFLINE=1 uv lock --check`                                              | PASS, rc 0 (Resolved 28 packages) |
| `uv run --frozen pytest -q -rs`                                             | PASS, 462 passed in 105.98s       |
| `uv run --frozen black --check .`                                           | PASS, 38 files unchanged          |
| `npx --no-install prettier --check README.md src/respec/shipped/*/SKILL.md` | PASS                              |
| `uvx --offline ruff check src tests --select F`                             | PASS                              |
| `git status --short`                                                        | clean                             |

## Concerns

- Nulls are filtered at the output layer, not in each `to_dict`. The library
  dicts (`Resolution.to_dict` and others) still hold `None`, which the TUI
  and tests can read. The CLI JSON is what the contract covers.
- After a repair that disabled an edited member, `adopt --add` puts the edit
  into the profile's disabled skill and removes the original from the target
  folder (it stays in the profile). This matches adopt's existing overwrite
  rule.
