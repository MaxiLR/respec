# Ticket 007 implementation run 6 (rebase onto d16724a)

- Branch: `codex/respec-v1-t007`, rebased from `60224c7` onto new base `d16724a` (Merge ticket 005: restore backups and release ownership; it includes fix-1, 010 and fix-2)
- Head: `934b772`
- Status: DONE

Commits on the base:

| New       | Was       | Subject                                                        |
| --------- | --------- | -------------------------------------------------------------- |
| `dc77f56` | `3b78094` | Add git sources, update and profile install                    |
| `c2ea63f` | `2ebea13` | Harden git sources against option injection and path escapes   |
| `94aa79e` | `979625a` | Refuse fetched symlinks that point outside the repository      |
| `2eac847` | `f7b24c1` | Copy fetched skills without following symlinks                 |
| `934b772` | new       | Test sourced update in copy mode against recorded copy digests |

## Conflict resolution

Only the first commit conflicted; the other three applied cleanly.

| File                | Conflict                                                                                 | Resolution                                                                                                                                        |
| ------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/respec/cli.py` | Imports: 005 added `from respec import restore as restore_backups`; 007 added `sources`. | Both: `from respec import items, layers, paths, profiles, sources, switch, targets, unknown` and `from respec import restore as restore_backups`. |
| `src/respec/cli.py` | End of file: 005's `restore` command vs 007's `update` / `profile install`.              | Kept 005's `restore` block, then 007's commands.                                                                                                  |
| `README.md`         | Usage block: 005's `respec restore ...` line vs 007's four git-source lines.             | Kept both (restore line first).                                                                                                                   |

The requested checks after the rebase:

- **No `--home`:** fix-2's callback (`Homes` from `paths.respec_home()` / `paths.user_home()`, env only) is unchanged. 007's commands use `_homes(ctx)`. `grep -- --home src README.md` finds nothing.
- **Renamed helpers:** `sources.py` never used the switch/state private helpers (`new_backup_run`, `utc_now`, `remove_installed`). It changes targets only through `items.refresh_active` -> `switch.use`, and no private-helper references remain.
- **fix-1 copy digests:** sourced items reach target folders only through `switch.use`, which records `Installed.digest` (`unknown.digest`) for copies. New test `test_update_in_copy_mode_refreshes_copies_and_records_their_digest` (symlinks refused via monkeypatch) shows three things. `update` refreshes the copy to the new content. `state.json` records `mode: copy` with `digest == unknown.digest(copy)`. A later `use work` is not blocked, so the copy counts as managed. The test passed on first run; it is integration evidence, not a red-first test.
- **005 manifest:** 007 writes no backups. Takeover backups and their `manifest.json` come only from `switch.use`, which sourced changes go through. `profile install` never touches targets.
- **`uv.lock` consistent:** `pyproject.toml` and `uv.lock` are unchanged from `d16724a`.
- **Round-3 security behavior:** unchanged. The fix commits applied without conflict, and all their tests pass.

## Verification

| Command                                  | Result                                                                                                 |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `uv sync --frozen`                       | Audited 27 packages, rc 0                                                                              |
| `uv lock --check`                        | Resolved 28 packages, rc 0                                                                             |
| `uv run pytest -q`                       | 218 passed                                                                                             |
| `uv run black --check .`                 | 27 files would be left unchanged                                                                       |
| `npx prettier@3 --check README.md`       | clean                                                                                                  |
| `respec --help`, `respec profile --help` | `tui`, `add`, `adopt`, `restore`, `update`, `profile` and `profile install` all listed (scratch homes) |

## Concerns

- None new. The earlier notes still apply (`runs/t007-impl-5.md`): links inside a fetched skill that point elsewhere in the repo are refused, and `file://` repos are accepted only below a `file://` base URL.
