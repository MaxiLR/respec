# Ticket 006 implementation run 1

- Branch: `codex/respec-v1-t006` (base `a2f222e`)
- Head: `2974fb0` Add respec add, remove, enable and disable for local items
- Status: DONE

## Changes

| File                     | Change                                                                                                                                                                                                                                                            |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/items.py`    | New core module. `add_local(respec_home, profile, source, enabled=True)` copies a folder in and writes `profile.yaml` with no target refresh (reusable by 004 adopt). `add`, `remove`, `set_enabled` wrap it and refresh the active profile. `ItemChange` result. |
| `src/respec/profiles.py` | `save_profile(profile)`: the single, atomic (temp + `os.replace`) `profile.yaml` writer. `create_profile` now uses it.                                                                                                                                            |
| `src/respec/switch.py`   | `SwitchBlocked(RespecError)` raised by the preflight (nothing on disk changed). No other change to the engine.                                                                                                                                                    |
| `src/respec/cli.py`      | `respec add <path>`, `remove <item>`, `enable <item>`, `disable <item>`, each with `-p/--profile` and `--json`.                                                                                                                                                   |
| `tests/test_items.py`    | 17 CLI tests against the autouse temp homes.                                                                                                                                                                                                                      |
| `README.md`              | Usage for the four commands.                                                                                                                                                                                                                                      |

How the refresh works: when the changed profile is the one in `state.json`'s `active_profile`, `items` calls `switch.use(active)` again. The engine removes recorded paths and installs enabled items, saving state after each step. `linked` and `unlinked` in the JSON output are the difference between the paths installed and the paths removed. If the preflight raises `SwitchBlocked`, the `profile.yaml` change is undone; for `add`, the copied folder is deleted too, and for `remove`, the folder is kept. If the switch fails partway (an OSError), the engine's existing behavior applies: state.json lists every created path and no profile is active. The profile change stays, and `remove` still deletes the item folder because the leftover recorded links are cleaned up by the next `use`.

## Acceptance criteria -> evidence

| Criterion                                                                                         | Tests (tests/test_items.py)                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `add <local-path> [-p]` copies a skill folder (needs SKILL.md); default profile is the active one | `test_add_copies_folder_into_named_profile_and_enables_it`, `test_add_defaults_to_active_profile_and_links_immediately`, `test_add_without_profile_and_without_active_profile_fails`, `test_add_rejects_folder_without_skill_md`, `test_add_refuses_existing_item_and_leaves_it_untouched`           |
| remove/enable/disable update profile.yaml; an active profile is refreshed immediately             | `test_disable_unlinks_from_active_targets_but_keeps_files_and_metadata`, `test_enable_links_into_active_targets`, `test_remove_deletes_item_and_unlinks_it_from_active_targets`, `test_enable_and_disable_of_inactive_profile_leave_targets_alone`, `test_unknown_item_fails_and_changes_nothing[*]` |
| Disabled items keep files and metadata                                                            | `test_disable_unlinks_from_active_targets_but_keeps_files_and_metadata` (the `source` record and the folder survive)                                                                                                                                                                                 |
| All commands support `--json`                                                                     | `test_commands_support_json`, `test_json_reports_no_link_changes_for_inactive_profile`                                                                                                                                                                                                               |
| (consistency) a blocked refresh rolls back                                                        | `test_add_rolls_back_when_active_install_is_blocked`, `test_enable_rolls_back_when_active_install_is_blocked`, `test_remove_keeps_item_when_active_refresh_is_blocked`                                                                                                                               |

TDD: all 15 initial tests failed first with exit code 2 (no such command), then passed. Mutation check: making `_refresh` re-raise a plain `RespecError` instead of `SwitchBlocked` makes `test_remove_keeps_item_when_active_refresh_is_blocked` fail, as intended.

## Verification

- `uv run pytest -q`: 73 passed (56 before, plus 17 new)
- `uv run black --check .`: 16 files would be left unchanged
- `npx prettier@3 --check README.md`: clean
- Real entry point (`.venv/bin/respec` with scratch HOME, RESPEC_HOME and RESPEC_USER_HOME): profile new, use, add (link created), disable --json (unlinked), enable (linked), remove (unlinked, folder deleted, `skills: {}`), `remove nope` exits 1 with a clear error. No `.profile.yaml.tmp` is left behind.

## Concerns

- Refreshing re-runs a full `use` of the active profile, so every link in that profile is removed and recreated, not only the changed item. This is correct and keeps state.json consistent, but other links disappear briefly.
- `save_profile` rewrites `profile.yaml` from the parsed model, so hand-written comments and formatting are lost on the first change.
- The item name comes from the source folder's basename. There is no `--name` option, because the ticket does not ask for one.
- `add` copies with symlinks followed (`shutil.copytree` defaults) so the profile stays self-contained.
- `--home` and `RESPEC_USER_HOME` semantics and `TOP_LEVEL_KEYS` are unchanged.
