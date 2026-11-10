# t002 implementation run 1

- Ticket: 002 "Profile switching: use and status"
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t002`
- Branch: `codex/respec-v1-t002`, base `a8ec9de`, head `134a0e6`
- Status: DONE

## Changes

- `src/respec/state.py` (new): `state.json` model (version 1) with
  `active_profile`, `owned` (per target: `skills_dir`, `backup` or null,
  `taken_over_at`) and `installed` (per path: `target`, `name`, `path`,
  `mode` = `symlink` or `copy`). Atomic save (temp file plus `os.replace`).
  Malformed state gives a `RespecError`.
- `src/respec/switch.py` (new): `use()` runs preflight (profile load, every
  enabled skill folder exists, no unrecorded entry occupies an install path),
  then first-takeover backups, removal of every recorded path, then install.
  Symlink with copy fallback on `OSError`. Clock is injectable (`now=`).
  Backup run folders are created with exclusive `mkdir`, and a `-2`, `-3`, ...
  suffix is added when that second is already taken, so names never collide.
  `status()` builds the report.
- `src/respec/cli.py`: `respec use <profile> [--json]`,
  `respec status [--json]`.
- `tests/test_use_status.py` (new): 16 tests.
- `README.md`: short usage section (Prettier-clean).

## Acceptance criteria and evidence

| Criterion                                                                                                                | Evidence (tests in `tests/test_use_status.py`)                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `use` symlinks every enabled skill into each target, copy fallback, records paths in `state.json`                        | `test_use_symlinks_enabled_skills_into_every_target_and_records_them`, `test_copy_fallback_when_symlinking_fails`                                                                                              |
| First takeover backs up full folder contents to `backups/<timestamp>/<target>/`; installing respec alone changes nothing | `test_first_takeover_backs_up_full_folder_contents`, `test_folder_is_backed_up_only_on_first_takeover`, `test_backups_taken_in_the_same_second_do_not_collide`, `test_installing_respec_alone_changes_nothing` |
| Switch removes every recorded path in every folder, installs new profile into its own targets only                       | `test_switch_scenario_a_to_b_leaves_former_folders_free_of_a`, `test_switch_removes_copied_items_too`                                                                                                          |
| Scenario A(claude-code, agents) to B(oh-my-pi)                                                                           | `test_switch_scenario_a_to_b_leaves_former_folders_free_of_a`                                                                                                                                                  |
| Disabled skills never linked                                                                                             | `test_disabled_skills_are_never_linked`                                                                                                                                                                        |
| Removal touches only recorded paths; profile folders never deleted                                                       | `test_switch_only_removes_recorded_paths_and_keeps_profile_folders`, `test_use_refuses_to_overwrite_unrecorded_entry`                                                                                          |
| `status` and `--json` show active profile, targets, items per folder                                                     | `test_status_json_before_any_switch`, `test_status_json_shows_profile_targets_and_items_per_folder`, `test_status_human_lists_active_profile_and_items`, `test_status_human_without_active_profile`            |

Criteria met: 7/7.

TDD: all 16 tests failed against a stub (missing commands or
`NotImplementedError`) before implementation. Mutation checks: making the
backup `mkdir` non-exclusive fails the same-second collision test, and
dropping the `enabled` filter fails the disabled-skill test.

## Verification

- `uv run pytest -q`: 53 passed. All tests use the autouse temp-home fixture.
- `uv run black --check .`: 14 files unchanged.
- `npx prettier --check README.md`: clean.
- Real entry point smoke in scratch homes: `respec use a` (claude-code and
  agents, with an existing `old` entry), then `respec use b` (oh-my-pi), then
  `respec status`. Backup held `claude-code/old`, both former folders had no
  managed items, and `old` remained.

## Design notes and concerns

- Install mode is recorded per installed path in state. No per-target mode was
  added to the target registry, so ticket 012 can add one there.
- The `use` preflight refuses when an install path is taken by an unrecorded
  entry, and changes nothing in that case. The adopt prompt belongs to 004.
- A recorded symlink that was later replaced by a real folder is left in place
  rather than deleted. It will appear as an unknown entry for 004.
- When the target folder does not exist at takeover, `owned.<target>.backup`
  is null and no backup folder is created. Ticket 005 (restore) should treat
  that target as "did not exist".
- The switch saves state between steps but has no journal. That is ticket 003.
- `--home` vs `RESPEC_USER_HOME` was not touched. State stores absolute paths,
  so removal works even if the home override changes between runs.
