# t009 implementation 1: global section and shipped agent skills

- Branch: `codex/respec-v1-t009` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t009`)
- Base: `b8d1aee`; head: `5dc0cd1`
- Status: DONE. The engineer decisions in the dispatch override the ticket: shipped skills go into all targets, and there is no `system: false` opt-out.

## Changes

- `src/respec/global_skills.py` (new):
  - Reads `<respec home>/config.yaml` in the form `global: {skills: [names]}`. Validation refuses unknown keys, non-lists, invalid or duplicate names, and names of shipped skills.
  - Each global skill's folder is `<respec home>/global/skills/<name>/`.
  - Lists the shipped skills bundled in the package under `respec/shipped/`.
  - Copies them into `<respec home>/shipped/<name>/` before each switch, and rewrites a copy only when its content differs.
  - `source_roots()` names every folder respec links point into: profiles, `global` and `shipped`.
- `src/respec/switch.py`:
  - `_plan_all` plans the profile's skills, then the global skills into the profile's targets, then the shipped skills into every registry target. A folder shared by several targets gets each skill once.
  - `_switch_targets` makes takeover (with backup) and conflict detection cover every target the switch writes into.
  - `_check_global` is a preflight check. It refuses when a global skill has no folder, when `config.yaml` is invalid, or when an enabled profile skill takes the name of a global or shipped skill. It raises `SwitchBlocked`, so `items` refreshes undo the profile change.
  - `_kept` leaves a global or shipped skill symlink in place when it already points at the planned source. Such links are neither removed nor relinked, and do not appear in `removed`/`installed`. Copies are always reinstalled.
  - Copying the shipped skills happens before takeover; a failure there is a `SwitchBlocked`.
- `src/respec/unknown.py`: `is_managed` now treats any link into a source root as managed.
- `src/respec/restore.py`: `_respec_link` treats links into the global and shipped folders as respec's own, so a restore never puts them back.
- `src/respec/switch.py` (`remove_installed`): never deletes anything inside a source root.
- `src/respec/shipped/respec/SKILL.md` covers:
  - ground rules for agents: `--json` and its `warnings`, exit codes, `-p`, global-only scope
  - targets and every CLI command
  - layers, including `repair --keep`
  - git sources: `add --ref`, the multi-skill path rule, `update [--check]`, `profile install`
  - the adopt flow (add or remove; unrelated entries only warn) and `use --unknown`
  - `restore --list`, `--unknown`, `--overwrite`
  - the `profile.yaml` schema with `skills:`, global and shipped skills, and `config.yaml`
  - the hook-scope rule for the next phase, and the env vars `RESPEC_HOME`, `RESPEC_USER_HOME` and `RESPEC_GIT_BASE_URL` (marked advanced/testing)
- `src/respec/shipped/profile-maker/SKILL.md`:
  - A one-question-at-a-time interview covering purpose and name, targets, skills and their sources, layers, which skills start disabled, and a confirmation.
  - It explicitly rejects project-scoped content: component libraries, tokens and themes, repository conventions, `CLAUDE.md`/`AGENTS.md`, and anything tied to one codebase.
  - It applies the result through `respec` commands only and verifies with `profile show --json`.
- `README.md`: new paragraph on shipped and global skills.
- `tests/conftest.py` and `pyproject.toml`:
  - New autouse fixture `shipped_skills` leaves the shipped skills out unless a test is marked `@pytest.mark.shipped`. The marker is registered in `pyproject.toml`. This seam is test-only; users have no opt-out.
- No changes to `tui.py` or to `cli.py`.

## Acceptance criteria -> evidence (all in `tests/test_global_skills.py` unless noted; the whole module runs with real shipped skills)

| Criterion (as amended)                                                                               | Independent test / evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Global items in `config.yaml` survive every switch, only in the active targets                    | `test_global_skills_follow_the_active_targets_and_shipped_go_everywhere` (A[claude-code, agents] -> B[oh-my-pi]); `test_global_skill_link_is_not_removed_by_a_switch` (same inode, not in removed/installed); `test_global_skill_dropped_from_config_is_removed_on_next_switch`; `test_global_skill_without_a_folder_is_refused`; `test_invalid_config_is_refused_without_changes` (8 cases); `test_invalid_config_refuses_a_refresh_and_leaves_the_profile_unchanged`; `test_profile_skill_named_like_a_global_skill_is_refused`                                                                                                                                                                                                                             |
| 2. Ship `respec` (CLI, schema, layers, sources, adopt, hook rule) and `profile-maker`                | `tests/test_shipped_skill_docs.py`: every `respec ...` invocation in both skills resolves to a real command, each written option is accepted by it and shown in its `--help`, and `--help` exits 0; the `respec` skill names every leaf command (coverage both ways); the "--json everywhere but tui" claim is checked; a misspelled command is caught. Mutation checks: `--keep` changed to `--kept` failed the test, and the doc's former `respec hook add` mention was caught (then reworded, since hooks are not built). `test_shipped_skills_are_real_skills_with_matching_names` (frontmatter `name`/`description`)                                                                                                                                     |
| 3. (Engineer decision 1) Shipped skills in ALL targets whenever a profile is active, with no opt-out | `test_global_skills_follow_..._shipped_go_everywhere`; `test_status_lists_shipped_skills_in_folders_outside_the_profile`; `test_takeover_of_a_folder_outside_the_profile_backs_it_up` (backup written, user entry stays and only warns); `test_unknown_entry_where_a_shipped_skill_goes_is_resolved_first` (blocks, then `--unknown remove`); `test_shipped_skills_install_once_into_folders_shared_by_two_targets`; `test_switch_api_reports_shipped_installs_on_first_use`; `test_stale_shipped_copy_is_refreshed_on_switch`; `test_profile_skill_named_like_a_shipped_skill_is_refused`; `test_restore_removes_shipped_and_global_skills` (release leaves only pre-respec content, status has no folders); `test_enabling_a_skill_reports_only_that_skill` |

Red evidence:

- With the `switch`/`unknown`/`restore` changes stashed, 22 of 23 new tests failed. The one that passed was the restore test, which passes vacuously on the base.
- Forcing `_kept` to return an empty set failed only `test_global_skill_link_is_not_removed_by_a_switch`.
- Before the fix, the refresh-rollback test failed: `assert False is True`, meaning the profile was changed despite an invalid config.

## Verification (fresh, at head 5dc0cd1)

- `uv sync --frozen`: `Audited 27 packages`
- `uv lock --check`: `Resolved 28 packages`
- `uv run pytest -q`: `373 passed` (base had 344; 29 new)
- `uv run black --check .`: `32 files would be left unchanged.`
- `npx prettier@3 --check README.md src/respec/shipped/respec/SKILL.md src/respec/shipped/profile-maker/SKILL.md`: `All matched files use Prettier code style!`
- `uv build --wheel`: the wheel contains `respec/shipped/respec/SKILL.md` and `respec/shipped/profile-maker/SKILL.md`.
- CLI smoke in a scratch home:
  - Setup: profile `pi` targeting oh-my-pi, with `~/.claude/skills/mine` already present.
  - `use pi` backed up claude-code and installed 6 skills (2 shipped x 3 targets). `mine` stayed and produced a warning.
  - `status` listed the shipped skills in all three folders.
  - `restore` removed the 6 skills and left only `mine`.

## Concerns

1. Test seam:
   - Shipped skills are off by default in the existing suite through the autouse `shipped_skills` fixture, because 56 existing tests assert exact folder contents.
   - With shipped skills forced on, I triaged all those failures. They are extra entries, or scenario shifts because every folder is now taken over at the first `use` (later "first takeover" and shared-folder backup scenarios can no longer arise). No interaction bug was found.
   - The interactions are covered by the `shipped`-marked module.
2. Global section has no CLI: no command edits `config.yaml`. The `respec` skill says so and calls it the one hand-edited file. A `respec global add/remove` command would be a new design decision.
3. Interactive first `use` asks about entries in folders outside the profile: because every folder is now taken over, a first `use` on a terminal asks add/remove for pre-existing entries in all three folders. "Add" goes to the profile being activated, even when it does not target that folder. This follows the normal takeover handling.
4. Name clashes block switching: a profile skill named `respec`, `profile-maker` or after a global skill refuses the switch. This includes an unknown `~/.claude/skills/respec` that the user adopts with "add"; "remove" resolves it.
5. `respec restore` leaves empty parent folders behind, such as `~/.omp/agent` and `~/.agents`. This is pre-existing behavior, but now visible for targets the user never chose.
6. For fix-7: status JSON does not mark which skills are global or shipped. No JSON keys changed.
