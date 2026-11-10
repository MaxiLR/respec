# Ticket 007 implementation run 4 (rebase onto 004 + fix round 2)

- Branch: `codex/respec-v1-t007`, rebased onto new base `60224c7` (Merge ticket 004: unknown-entry detection and adopt)
- Head: `979625a`. The branch has three commits on the base: `3b78094` Add git sources, update and profile install (was `c2f268d`), `2ebea13` Harden git sources against option injection and path escapes (was `98ac129`), and `979625a` Refuse fetched symlinks that point outside the repository (new).
- Status: DONE

## Rebase conflict resolution

The first commit conflicted in four files; the second applied cleanly.

| File                  | Conflict                                                                                                          | Resolution                                                                                                                                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/items.py` | `add_local` signature/docstring: 004 added `name: str \| None = None`, 007 added `origin: Source \| None = None`. | Both kept, in the order `enabled, name, origin`. Callers pass keywords: 004's adopt uses `name=`, sources uses `origin=`. The docstring describes both. `SkillEntry(enabled=enabled, source=origin)` unchanged. |
| `src/respec/cli.py`   | Imports: 004 added `adopt as adopt_entries`, `unknown`, `load_state`; 007 added `sources`.                        | Union: `from respec import adopt as adopt_entries` + `from respec import items, layers, paths, profiles, sources, switch, targets, unknown`.                                                                    |
| `src/respec/cli.py`   | End of file: 004's `adopt` command and helpers vs 007's `update` / `profile install`.                             | Kept 004's block, then 007's commands. `add` (SOURCE string, `--ref`) auto-merged.                                                                                                                              |
| `README.md`           | Usage block: 004's `respec adopt ...` line vs 007's four git-source lines.                                        | Kept both (adopt line first).                                                                                                                                                                                   |
| `tests/conftest.py`   | Both added `input=` to the `run` fixture (different formatting).                                                  | Took 004's version; 007's change to conftest is now empty.                                                                                                                                                      |

004 integration: 004 raises `switch.UnknownEntries`, a `SwitchBlocked` subclass, from `switch.use`. `items._refresh` catches `SwitchBlocked`, runs the caller's undo and re-raises. All sourced changes go through `items.refresh_active` (the public wrapper of `_refresh`). So `add` (with or without `--ref`) and `update` on an active profile are blocked by unknown entries and roll back: `profile.yaml` is restored via `save_profile`, fetched folders are deleted, and replaced folders are moved back. `profile install` creates a new profile and never touches targets, so it has no refresh. All `profile.yaml` writes still go through `profiles.save_profile`.

## Symlink exfiltration fix

`sources.copy_fetched(tree, source, destination)` replaces the bare `shutil.copytree` in `add`, `_replace` (update) and `install_profile`. Before copying, it walks the source without following links and refuses:

- any symlink, including the source folder itself and `profile.yaml`, that resolves outside the fetched tree;
- a symlink that points at a folder holding it (a loop).

Links inside the tree are still copied as their contents, so the profile stays self-contained. `install_profile` now also deletes the destination when a `RespecError` occurs mid-copy.

While writing the tests I found a latent bug from round 1. `inside()` returned a resolved path while the temp tree was unresolved (macOS `/var` vs `/private/var`), so `add owner/repo#folder-of-skills` crashed with `ValueError`. Fixes: `inside()` returns `tree / path` after the check, and `checkout` resolves the temp root.

## Evidence

| Item                                          | Red before fix                                                  | Tests (tests/test_sources.py)                                                                                                                                                                                                                                                                                                         |
| --------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Symlink out of the repo: add, update, install | exit 0; the `PRIVATE KEY` file was copied into the profile      | `test_add_refuses_symlinks_pointing_outside_the_repository` (file and folder links), `test_update_refuses_symlinks_pointing_outside_the_repository` (old content and folder set kept), `test_profile_install_refuses_symlinks_pointing_outside_the_repository`, `test_profile_install_refuses_symlinked_profile_file_and_item_folder` |
| In-repo symlinks still work                   | n/a (guards against over-blocking)                              | `test_add_keeps_symlinks_inside_the_skill`                                                                                                                                                                                                                                                                                            |
| `#path` to a folder of skills                 | `ValueError ... is not in the subpath of` (exit 1)              | `test_add_path_to_folder_of_skills_adds_each`                                                                                                                                                                                                                                                                                         |
| 004 blocking/rollback for git `add`           | n/a (integration evidence; passes through the shared mechanism) | `test_add_from_git_into_active_profile_is_blocked_by_unknown_entries`: names the unknown entry, `skills: {}`, no fetched folder, no link, stranger untouched                                                                                                                                                                          |
| 004 blocking/rollback for `update`            | n/a (integration evidence)                                      | `test_update_of_active_profile_is_blocked_by_unknown_entries`: old content and commit restored, no `.old`, link still shows v1                                                                                                                                                                                                        |

Mutation check: turning the `_within` guard into a no-op fails the 4 outside-symlink tests.

## Verification

- `uv run pytest -q`: 158 passed (150 after the rebase, plus 8 new)
- `uv run black --check .`: 23 files would be left unchanged
- `npx prettier@3 --check README.md`: clean (one sentence added on the symlink rule)

## Concerns

- The `add`/`update` unknown-entry tests did not need code changes. They record that 004's mechanism covers sourced items; they were not red first.
- A fetched skill may still contain symlinks to other places inside the same repository. Those are copied as content, which is public repository data.
- `items._refresh` re-raises `UnknownEntries` as a plain `SwitchBlocked` (004's existing behavior), so sources' JSON callers see the message but not the structured entry list.
