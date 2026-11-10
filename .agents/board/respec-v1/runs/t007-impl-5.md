# Ticket 007 implementation run 5 (fix round 3, review 2)

- Branch: `codex/respec-v1-t007`, base `60224c7` (not rebased)
- Head: `f7b24c1` Copy fetched skills without following symlinks (on top of `979625a`)
- Input: `runs/t007-review-2.md` (S1 blocking, N6, N7, N8, digest note)
- Status: DONE

## Changes

| File                     | Change                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/sources.py`  | `copy_fetched` rewritten (S1, N7). `_check_links` (new). `GIT_ALLOW_PROTOCOL` set in `_git` (N6). `add` wraps `OSError`/`shutil.Error` as `RespecError` after rollback (N7). Shorthand/scp patterns and the base URL now come from `profiles`.                                                                                                                          |
| `src/respec/profiles.py` | `source_value_problem("repo", ...)` adds a shape check (N8): `owner/repo`, `user@host:path`, or an `https`/`http`/`ssh`/`git` URL. `file://` is accepted only below a `file://` `RESPEC_GIT_BASE_URL` (test seam), with no `.`/`..` segments and no `%`. `GIT_BASE_URL_ENV`, `git_base_url()` and the repo patterns move here so the loader and the CLI share one rule. |
| `tests/test_sources.py`  | 12 new test cases (below).                                                                                                                                                                                                                                                                                                                                              |
| `README.md`              | Symlink rule, accepted repo forms, and the note that items from `profile install` ask on their first update (no digest), from the review note.                                                                                                                                                                                                                          |

## S1: structural fix and why

Choice: never follow a symlink while copying out of the fetched repository. Links are kept only when they stay inside the skill's own folder, and they are stored dereferenced.

1. `shutil.copytree(source, checked, symlinks=True)` copies into a temporary check folder. No link is followed, so nothing outside the item is read.
2. `_check_links(checked)` walks that copy. Each link must `resolve(strict=True)` (following any chain) to an entry strictly inside the checked folder. It must not resolve to the folder itself or an ancestor of the link. Broken links and loops (`RuntimeError`/`OSError` from `resolve`) are refused.
3. Only then is `shutil.copytree(checked, destination)` run, following links. Every link now resolves inside the checked copy, so the result is self-contained (as `add_local` does for local folders), and the digest matches what later updates compare.

Why "inside the skill folder" rather than "inside the repository": a link that leaves the copied folder but stays in the repo is exactly how S1 escaped (`skill/link -> ../other`). It would also not point anywhere meaningful after copying. Rejecting every symlink would have been simpler, but would break legitimate in-skill links (`guide.md -> docs/guide.md`, still covered by `test_add_keeps_symlinks_inside_the_skill`). The spec says nothing either way.

Entry points: `add` (staging), `_replace` (`update`), and `install_profile` (each listed item) all go through `copy_fetched`. The item folder or `#path` itself being a link is checked by `inside()`/`_within(root, source)`, and `profile.yaml` by `_within`. Every failure removes the partial destination and raises `RespecError`. Callers roll back as before: add forgets added items, update restores folders and `profile.yaml`, install removes the new profile.

## Findings -> regression tests (each failed first)

| Finding                                                                            | Red before the fix                                                                                 | Tests                                                                                                              |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| S1 reviewer's nested repro (`skill/link -> ../other`, `other/evil -> secret`), add | exit 0, `PRIVATE KEY` copied                                                                       | `test_add_refuses_escaping_symlink_behind_in_repo_folder_link[file]`                                               |
| S1 symlink chain behind a folder link                                              | exit 0, secret copied                                                                              | `...behind_in_repo_folder_link[chain]` (`other/c1 -> c2 -> secret/id_rsa`)                                         |
| S1 symlinked directory pointing outside                                            | exit 0, secret copied                                                                              | `...behind_in_repo_folder_link[dir]` (`other/keys -> secret/`)                                                     |
| S1 profile install (reviewer's `skills/a/link -> ../../x`)                         | exit 0, secret copied                                                                              | `test_profile_install_refuses_escaping_symlink_behind_folder_link`                                                 |
| S1 update                                                                          | exit 0, secret copied                                                                              | `test_update_refuses_escaping_symlink_behind_folder_link` (old content and folder set kept)                        |
| N7 symlink loop                                                                    | `shutil.Error` traceback (`result.exception` not `SystemExit`)                                     | `test_symlink_loop_is_a_clean_error_and_adds_nothing`                                                              |
| N6 remote helper transports                                                        | fake `git-remote-evil` on PATH ran (marker created); the `fd::3` profile case hung pytest (killed) | `test_remote_helper_transports_are_refused`, `test_profile_repo_naming_a_local_path_is_rejected[helper]` (`fd::3`) |
| N8 local repo in profile.yaml                                                      | `update --check` exited 0 for an absolute path, a relative path, and an out-of-base `file://` URL  | `test_profile_repo_naming_a_local_path_is_rejected[absolute, relative, file-url]`                                  |
| N8 positive control (test seam)                                                    | n/a                                                                                                | `test_file_url_under_the_configured_base_url_is_allowed`                                                           |

Mutation checks:

- Removing `symlinks=True` from the first copy fails all 5 S1 tests.
- Removing `GIT_ALLOW_PROTOCOL` fails the helper test.

## Verification

- `uv run pytest -q`: 170 passed (158 before, plus 12 new test cases)
- `uv run black --check .`: 23 files would be left unchanged
- `npx prettier@3 --check README.md`: clean
- Real entry point, reviewer's exact layouts (scratch homes, isolated git config, `file://` remotes):
  - `respec add 'acme/nest#skill' -p p`: rc 1, `symlink 'link' is broken, loops or points outside the skill folder; refusing to copy it`
  - `respec profile install acme/pk`: rc 1, same message
  - `grep -r SECRETBYTES $RESPEC_HOME`: nothing found

## Concerns

- Behavior change: links inside a fetched skill that point elsewhere in the same repository (outside the skill folder) are now refused. Previously they were copied as content.
- A cycle made only of sibling folder links (`a -> b`, `b/c -> ../d`, `d/e -> ../b`) passes `_check_links`. The dereferencing copy then fails with a path-length `OSError`, which becomes a clean `RespecError` with rollback, not a hang or traceback.
- `file://` remains in the allowed protocols for the test seam. Profile and CLI repos may use it only below a `file://` base URL.
- CLI `add file:///...` outside the base URL is now refused too, so the recorded profile always stays loadable. Local folders are still added by path.
