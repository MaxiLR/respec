# Ticket 007 implementation run 2 (rebase onto 008)

- Branch: `codex/respec-v1-t007`, rebased from base `35cad16` onto new base `5136097` (Merge ticket 008: layers)
- Head: `c2f268d` Add git sources, update and profile install (single commit; replaces `3bb1109`)
- Status: DONE

## Changes

| File                     | Change                                                                                                                                                                                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/sources.py`  | New module. Spec parsing (`owner/repo[#path]` through `RESPEC_GIT_BASE_URL`, read at call time; git URLs incl. scp-like), git fetch into a temp tree (`git init` + `fetch --depth 1 <ref or HEAD>`, full fetch for a 40-hex sha), `ls-remote` resolution, file digest, `add`, `check`, `update`, `install_profile`. |
| `src/respec/profiles.py` | `Source` gains optional `digest`; `SOURCE_KEYS` gains `"digest"` (schema docstring updated). No other change.                                                                                                                                                                                                       |
| `src/respec/items.py`    | `add_local(..., origin: Source \| None = None)` records the origin as the item's `source`; new public `refresh_active(...)` seam wrapping `_refresh`.                                                                                                                                                               |
| `src/respec/cli.py`      | `add` takes a string SOURCE: an existing local path keeps the old path, otherwise a git spec goes to `sources.add`; new `--ref`. New `update [item] [--check] [--yes] [-p] [--json]` and `profile install <repo> [--name] [--ref] [--json]`. Appended at the end of the file to keep rebases mechanical.            |
| `tests/conftest.py`      | `run` fixture accepts `input=` (for the confirmation prompt).                                                                                                                                                                                                                                                       |
| `tests/test_sources.py`  | 27 CLI tests over local bare repos via `file://`, with an autouse fixture setting `GIT_CONFIG_GLOBAL` (temp file), `GIT_CONFIG_NOSYSTEM=1`, author env and `RESPEC_GIT_BASE_URL` (temp `file://` dir). HOME is already temp via conftest.                                                                           |
| `README.md`              | Usage for git sources, update and profile install.                                                                                                                                                                                                                                                                  |

Design notes:

- Fetched content goes through a staging folder named after the item, then `items.add_local(..., origin=Source)`; one `save_profile` writer. Several skills in one repo are added in one go; any name clash is checked first and nothing is added. On failure, the profile and copied folders are rolled back.
- Skill discovery: `#path` (or root) with `SKILL.md` -> one item (named after the path's last part, or the repo name at root); otherwise each child folder with `SKILL.md`, then `skills/*`.
- Local-edit detection: `digest` = sha256 over sorted relative paths, executable bit and content, stored at fetch/update time. A sourced item without a digest (for example from a hand-written or installed profile) counts as possibly edited, so it asks.
- `update` swaps folders via `.<item>.incoming` / `.<item>.old` and keeps the old folder until the active-profile refresh (`items._refresh`, the same `switch.use` path as 006) succeeds. A `SwitchBlocked` restores folders and `profile.yaml`.
- `profile install` copies only `profile.yaml` (re-saved via `save_profile` after `parse_profile` validation) and the listed `skills/<item>` folders. It refuses an existing profile name, an invalid profile, or a listed item without a `SKILL.md` folder, and leaves nothing behind. No record of the modpack origin is kept (it is owned locally).

## Rebase onto 5136097 and conflict resolution

`git rebase 5136097` conflicted in two files. Both were resolved by keeping both sides:

| File                     | Conflict                                                                                                                           | Resolution                                                                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/profiles.py` | Schema docstring: 008 added the `layers:` block, 007 added `digest:` under `source:`.                                              | Kept both. `digest:` sits under `source:` and the `layers:` block follows it.                                                                                                                       |
| `src/respec/profiles.py` | Constants: 008 added `LAYER_KEYS`, `BUILTIN_LAYER_KEYS`, `OUTPUT_STYLE*`, `BUILTIN_LAYERS`; 007 added `"digest"` to `SOURCE_KEYS`. | Kept all of 008's constants and set `SOURCE_KEYS = ("repo", "path", "ref", "commit", "digest")`. 008's `"layers"` in `TOP_LEVEL_KEYS` and the `Source.digest` field (auto-merged) are both present. |
| `src/respec/cli.py`      | Import line: 008 imports `layers`, 007 imports `sources`.                                                                          | `from respec import items, layers, paths, profiles, sources, switch, targets`.                                                                                                                      |
| `src/respec/cli.py`      | End of file: 008 appended the `layer` sub-app and commands; 007 appended `update` and `profile install`.                           | Kept 008's block first, then 007's commands. `add` (str SOURCE, `--ref`) auto-merged and is independent of the `layer add` / `layer add-item` subcommands.                                          |

`items.py` auto-merged: 008's `items.commit` and docstring changes, plus 007's `add_local(..., origin=...)`. Every `profile.yaml` write still goes through `profiles.save_profile`. That covers `add_local`, `sources._forget` / `_restore` / `update`, `install_profile`, and 008's `items.commit`.

Public seam: `sources` no longer calls the private `items._refresh`. A small public `items.refresh_active(respec_home, user_home, change, undo)` wraps it. 008's `items.commit` was not reused, because its undo only restores `profile.yaml`, while sources must also delete fetched folders (add) or restore the replaced item folders (update) when the refresh is refused.

Post-rebase check through the real entry point, with scratch homes, isolated git config and `RESPEC_GIT_BASE_URL=file://`:

1. `respec --help` lists `add`, `update` and `layer`.
2. `add acme/skills --ref beta` added `a` and `b` and linked both.
3. `layer use design-principles a` and `layer add-item design-principles b` disabled and unlinked `b`.
4. After an upstream push, `update --yes` updated both items.
5. `profile.yaml` kept `layers.design-principles.items: [a, b]`, `b: enabled: false` and `ref: beta`, and recorded the new commit and digest. Only `a` stays linked.

## Acceptance criteria -> evidence

| Criterion                                                                                                    | Tests (tests/test_sources.py)                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `add <owner/repo>[#path]` / git URL fetches skill(s) into the profile, records repo, path, ref and commit    | `test_add_shorthand_with_path_records_source`, `test_add_git_url_of_single_skill_repo_names_item_after_repo`, `test_add_repo_with_several_skills_adds_each_with_its_own_path`, `test_add_with_ref_records_ref_and_fetches_that_branch`, `test_add_into_active_profile_links_item`, `test_add_missing_repo_fails_cleanly`, `test_add_path_without_skill_fails_and_adds_nothing`, `test_add_of_existing_item_name_adds_none_of_the_skills` |
| `update --check` reports items with newer upstream commits                                                   | `test_check_reports_up_to_date_items`, `test_check_reports_newer_upstream_commit_without_changing_anything`, `test_check_human_output_names_items_with_updates`                                                                                                                                                                                                                                                                          |
| `update [item]` applies, refreshing links if active                                                          | `test_update_item_applies_and_records_new_commit`, `test_update_removes_files_deleted_upstream`, `test_update_all_changes_sourced_items_but_never_local_ones`, `test_update_refreshes_links_of_active_profile`, `test_update_of_up_to_date_item_reports_nothing_to_do`                                                                                                                                                                   |
| Items without a source never change                                                                          | `test_update_all_changes_sourced_items_but_never_local_ones`, `test_update_of_item_without_source_is_refused`                                                                                                                                                                                                                                                                                                                            |
| Local edits detected; confirmation required before overwrite                                                 | `test_check_reports_local_edits`, `test_update_over_local_edits_asks_and_keeps_them_when_declined`, `test_update_over_local_edits_overwrites_when_confirmed`, `test_update_with_yes_overwrites_local_edits_without_asking`, `test_update_json_skips_locally_edited_items_without_yes`                                                                                                                                                    |
| `profile install <repo>` copies a whole profile once; owned locally afterwards; items keep their own sources | `test_profile_install_copies_whole_profile`, `test_profile_install_with_name_and_then_owned_locally`, `test_profile_install_refuses_existing_profile`, `test_profile_install_of_invalid_profile_leaves_nothing`, `test_profile_install_rejects_listed_item_without_folder`                                                                                                                                                               |

TDD: the new tests first failed with exit code 2 (no such command / `--ref` / `install`) or missing `source` records. Two error-path tests passed early by the local-path error and were rechecked after implementation. Mutation check: making `_modified` always return `False` fails 3 local-edit tests, as intended.

## Verification

- `uv run pytest -q` (after the rebase): 113 passed (86 on base 5136097, plus 27 new)
- `uv run black --check .`: 20 files would be left unchanged
- `npx prettier@3 --check README.md`: clean
- Real entry point (`.venv/bin/respec`, scratch HOME/RESPEC_HOME/RESPEC_USER_HOME, `GIT_CONFIG_GLOBAL` temp, `GIT_CONFIG_NOSYSTEM=1`, `RESPEC_GIT_BASE_URL=file://...`): `profile new`, `use`, `add 'acme/skills#tdd'` (linked), upstream push, `update --check` shows `update available`, local edit + `echo n | update tdd` shows `skipped: local edits kept`, `update --yes` updates and the linked `~/.claude/skills/tdd/SKILL.md` reads `v2`, `add acme/nope` exits 1 with the git error. `profile.yaml` holds repo/path/commit/digest. No `.tdd.old`/`.tdd.incoming` leftovers.

## Concerns

- Shared-file touch points for the remaining rebase with 004 (008 is now resolved): `SOURCE_KEYS` and `Source` (one field), `add_local` signature (new keyword `origin`), `add` command in `cli.py` (argument type changed from `Path` to `str`, plus `--ref`), new commands appended at the end of `cli.py`, and `run` fixture `input=` in `conftest.py`.
- `items.refresh_active` takes a duck-typed change (`SourceChange`, `UpdateResult`) with `profile`/`active`/`linked`/`unlinked`, matching how 008 already uses `_refresh` for layer changes.
- `update` also refreshes disabled sourced items, including disabled members of an exclusive layer. Their files change, but they stay unlinked.
- The schema gains `source.digest` (a design addition for local-edit detection; the ticket did not name the mechanism). Sources without a digest are treated as possibly edited and ask before overwrite.
- An `owner/repo` that also exists as a local relative folder is treated as the local folder.
- `ref` is recorded only when given; without it `update` tracks the remote's HEAD. A full 40-hex commit as `--ref` is pinned (never reports updates) and needs a full fetch.
- `update` exits 1 if any item's remote cannot be read, after reporting the others.
- `--home` / `RESPEC_USER_HOME` semantics unchanged.
