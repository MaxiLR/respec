# fix-6 impl 3: rebase onto 493d8e8 (after fix-5) and integration fixes

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Branch: `codex/respec-v1-fix-6`
- New base: `493d8e8528670240bf66fedbded67b89741baf43`
- Head: `43d49d2`, a single commit. Before the rebase I squashed the earlier commits `56ed201` and `dcdf333` into one so the conflicts only had to be resolved once. The old SHAs remain in the reflog.
- Status: DONE. Not pushed or merged.

## Conflict resolutions

| File        | Resolution                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `switch.py` | `use()` keeps fix-5's `refuse_layer_conflicts(profile, action)` as its first check and runs it again after `on_unknown` reloads the profile. It also gains `action="switch to"`, which builds the shared lead `cannot <action> profile '<name>'` used by `_check_sources`, `UnknownEntries` and the layer-conflict refusal. fix-6's `conflicts()` narrowing and `link_skills()` stay. `_forget_replaced` stays removed.                                                                                                                                                                                                                                                                                                                                                 |
| `adopt.py`  | Kept from fix-5: `_put_back`, `_undo_adds`, `Resolution.link`, the up-front question to every entry before any change, and `switch.refuse_layer_conflicts(before, "adopt into")` when any choice is add. Changed on top: choices are only add and remove; add always goes to the active profile, and with no active profile it is refused up front before any change. Linking after an add uses `link_skills` instead of a full `switch.use`. On any `RespecError` from resolving or linking, the adds of that run go through `_undo_adds`. They are dropped from `done`, and the error says that they were taken back out, adding fix-5's notes for any copy that stays in the profile. Removals already done stay in `done`, so they are reported with their backups. |
| `cli.py`    | Uses `items.SkillChange` (fix-5's rename). Adds warnings parameters. `_print_json` now merges the two warning sources into one list (see below). `layer repair` reports unknown-entry warnings too.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

## How fix-5's invariants were preserved

- **Early guard.** The guard runs before any change, and with the fix-5 wording "cannot adopt into profile". `adopt()` collects every choice first. If any choice is add, it loads the active profile and calls `refuse_layer_conflicts(before, "adopt into")` before `resolve()` touches anything. fix-5's `test_adopt_add_into_conflicted_active_profile_refuses_and_changes_nothing` checks the profile.yaml and state.json bytes, and `test_adopt_refusal_says_cannot_adopt` checks the message. Both pass unchanged.
- **Never delete the only copy.** `_put_back` and `_undo_adds` are unchanged apart from one addition. For an add that overwrote the profile's own copy (criterion 5), the profile's previous copy is now backed up before the overwrite (this also resolves review N4). After a verified put-back, `_undo_adds` restores that previous copy from the backup into the profile. When the put-back cannot be verified, the edited content stays in the profile and the note names both locations. fix-5's rollback tests all pass:
  - `test_adopt_rolls_back_an_add_when_the_relink_is_refused`
  - `test_adopt_relink_failing_partway_never_loses_the_content`
  - `test_adopt_relink_failing_in_copy_mode_keeps_the_original_unmanaged`
  - `test_adopt_keeps_the_copy_when_the_original_path_holds_something_else`
  - `test_adopt_failure_reports_backups_made_earlier`

  The two tests that monkeypatched `switch.use` to simulate a refused relink now patch `switch.link_skills`, because that function is now the relink step. Their assertions are unchanged. The failure test uses `--remove` instead of `--backup`.

- **Byte-exact rollback.** `items.commit` and the undo paths still call `profiles.restore_profile(before)`. `test_refused_change_restores_legacy_file_bytes` still passes. It now blocks the refresh with an entry in the way (a link replaced by a folder) rather than an unrelated stray entry, because unrelated entries no longer block.

## Integration fixes (int-493d8e8 findings)

- **(3) `layer repair` is no longer blocked by unrelated unknown entries.** Only an entry at a path the refresh would install to or remove blocks it, because the refresh goes through `switch.use`, which now uses `conflicts()`. fix-5's `test_repair_refused_by_switch_preflight_leaves_profile_unchanged` now uses a replaced link, the case that still blocks.
- **(2) Refused refreshes say what was refused.** `items._refresh` calls `switch.use(..., action="refresh")`. Layer-conflict refusals, missing skill folders and entries in the way all now read `cannot refresh profile 'work'`, followed by "Profile 'work' was left unchanged."
- **(1) `layer off`/`on` relinks.** In `layers.set_active`, when the profile is active and the changed profile has no exclusivity conflicts left, it is re-applied through `items.refresh_active`, with `restore_profile(before)` as the undo. A still-conflicted profile is not refreshed, so turning a layer off is still always allowed.
- **(4)** "kept" entries at first takeover keep blocking: this was resolved in impl-1/2. The keep choice is gone and only entries in the way block.

## JSON warnings merge (one format, documented in the README)

`_print_json` builds `warnings` as the layer-conflict list followed by the list the command passes in. Neither list overwrites the other. Every warning is an object with `type` and `message`:

- `{"type": "layer-conflict", profile, layer, skills, message, fix}` comes from `profiles.peek_warnings()`, which describes the state after the command.
- `{"type": "unknown-entry", name, path, kind, targets, replaced, message}` comes from `_warn_unresolved`.

The discriminator is `type` rather than `kind`, because `kind` already means folder, file or symlink on unknown entries. Both types are printed on stderr: layer conflicts through fix-5's `call_on_close`, unknown entries inline. fix-5's structured-warnings test now expects `"type": "layer-conflict"`.

## click dependency

`cli.py` catches click's `Abort` alongside typer's, so `click>=8.1` is now declared in `pyproject.toml`. `UV_OFFLINE=1 uv lock` changed `uv.lock` by two lines, which only add the declaration. click stays at 8.5.1, and `uv lock --check` passes.

## Tests (red first)

New tests, all red against `493d8e8`'s `src` (I ran them from a `git archive` copy via `PYTHONPATH`), green at head:

- `test_layer_repair.py`:
  - `test_unrelated_unknown_entry_does_not_block_layer_repair`
  - `test_refused_refresh_says_refresh_not_switch`
  - `test_refresh_blocked_by_an_entry_in_the_way_says_refresh`
  - `test_layer_off_that_resolves_a_conflict_links_the_enabled_skills`
  - `test_json_warnings_hold_layer_conflicts_and_unknown_entries_together`
- `test_adopt.py`:
  - `test_overwriting_add_backs_up_the_profile_previous_copy`
  - `test_failed_link_after_an_overwriting_add_puts_both_copies_back`

  I wrote these two after the merged `adopt.py` existed, so their red evidence is only against the base.

## Verification (fresh, at `43d49d2`)

- `uv sync --frozen`: ok
- `uv lock --check`: Resolved 28 packages
- `uv run pytest -q`: 327 passed
- `uv run black --check .`: 29 files would be left unchanged
- `npx prettier@3 --check README.md`: All matched files use Prettier code style
- `uvx ruff check src --select F`: All checks passed

## Concerns

- History was squashed into one commit, so the impl-1 and impl-2 SHAs (`56ed201`, `dcdf333`) are no longer on the branch.
- A failure inside the `use` paths (a conflict handler during a switch, or the takeover prompt) does not undo adds. Those adds are complete and are reported, as in B2. Only `respec adopt` and the TUI's `a` path roll back adds when linking fails.
- `link_skills` links only into folders respec owns. A target added to the active profile but never taken over gets linked at the next `use`.
- Still open from review 1: N2 (skip at the takeover prompt), N5 (one-time effect of the digest change) and N6 (no up-front check on `restore --unknown add` without a profile). fix-5's dead `exclusivity_problems()` and its "item" internal names are left as they are.
