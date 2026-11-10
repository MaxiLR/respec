# Integration check at fc7912b (after merging 007)

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- `git rev-parse HEAD` → `fc7912b588d02cf9f3aa855733d488b92f43f19f` (matches the
  expected head)
- Change range `d16724a..fc7912b`: README.md, src/respec/{cli,items,profiles,sources}.py,
  tests/test_sources.py (6 files, +2030/−10)
- Working tree: only the expected orchestrator files under
  `.agents/board/respec-v1/` (tickets, orchestration.md, runs/); not touched
- AGENTS.md: none in the repository; global CLAUDE.md applies

## Gates

| Command                                                            | Result                                       |
| ------------------------------------------------------------------ | -------------------------------------------- |
| `uv sync --frozen`                                                 | rc 0 (`Audited 27 packages`)                 |
| `uv lock --check`                                                  | rc 0 (`Resolved 28 packages`)                |
| `uv run pytest -q -rs`                                             | rc 0, `218 passed in 44.25s`, 0 skips        |
| `uv run black --check .`                                           | `27 files would be left unchanged.`          |
| `npx prettier@3 --check README.md .agents/board/respec-v1/spec.md` | `All matched files use Prettier code style!` |

Tests use local bare repos through `RESPEC_GIT_BASE_URL` (file://) with an
isolated `GIT_CONFIG_GLOBAL`; no network.

## Cross-ticket checks

- **004 (unknown/adopt blocking, rollback)**: `sources.add` and `sources.update`
  re-apply the active profile through `items.refresh_active` → `switch.use`. On
  `SwitchBlocked`, `add` runs `_forget` (restore profile.yaml, delete added
  folders) and `update` runs `_restore` (restore profile.yaml, move `.<item>.old`
  folders back). Smoke confirmed: with an unknown `stray/`, `update --yes` exited
  1 and left beta's locally edited files and `profile.yaml` unchanged, with no
  `.beta.old`/`.beta.incoming` leftovers. Covered by tests
  `test_add_from_git_into_active_profile_is_blocked_by_unknown_entries` and
  `test_update_of_active_profile_is_blocked_by_unknown_entries`.
- **fix-1 (copy digests) vs `source.digest`**: these stay separate. `state.json`
  `Installed.digest` and the backup manifest use `unknown.digest` (installed copy
  in a target folder). `Source.digest` uses `sources.digest` (the profile's
  `skills/<item>` folder as fetched) and is only read in `sources._modified`.
  Nothing compares one against the other. `test_update_in_copy_mode_refreshes_copies_and_records_their_digest`
  shows that after an update, copy-mode installs are re-recorded with
  `unknown.digest`. See finding 2 about the two algorithms and the shared prefix.
- **005 (restore, manifest)**: the restore manifest only records target-folder
  items (`unknown.digest`). Sources live in the profile, which restore never
  touches. Smoke: restore after add/use/update removed 2 respec items and brought
  back `~/.claude` exactly (snapshot identical).
- **008 (layers)**: `SkillEntry` is only built in `profiles._parse_skill` and
  `items.add_local` (now with `source=origin`). Enable/disable/layer edits use
  `dataclasses.replace`, so they keep `source`. `install_profile` validates
  layers through `parse_profile` against the fetched file.
- **010 (TUI)**: the TUI imports only `adopt, profiles, switch, unknown` and
  does not expose sources. It loads profiles through `profiles.load_profile`,
  which now also rejects unsafe source values. A profile with such a value
  shows up as a profile error, the same way any other validation problem does.
- **fix-2 (no `--home`)**: `update` and `profile install` use `_homes(ctx)`. The
  smoke check `respec update --home /x` gave rc 2 with `No such option: --home`.

## End-to-end smoke (temp homes, file:// base URL)

Script: `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/smoke7.sh`.
Log: `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/smoke7.log`.
The env sets `RESPEC_USER_HOME`, `RESPEC_HOME` and `RESPEC_GIT_BASE_URL=file://…/base`.
`base/acme/kit` is a bare repo with `skills/alpha` and `skills/beta`, and
`~/.claude/skills` starts with `orig-skill/` and `notes.txt`.

1. `profile new work`; `add acme/kit -p work` → added alpha and beta, each with
   repo, path, commit and `sha256:` digest
2. `use work` → takeover backup, both items symlinked
3. Right after the takeover, `update` (with alpha and beta stale) was blocked
   (rc 1) by the pre-existing `notes.txt`/`orig-skill`, which stayed in place
   after the takeover backup, and the profile was rolled back. This is the
   existing 004/005 behavior, not something new in 007. `adopt --all keep` then
   unblocked it.
4. `update --check` → both up to date. After pushing v2: `--json` reports
   `update_available: true, modified: false`
5. `update` → both `updated c7bea1… -> f11b56…`; the live link shows `# alpha v2`;
   the new commit and digest were recorded
6. Local edit to beta, then v3 pushed, `update --json` → alpha `updated`, beta
   `skipped-local-edits` (rc 0)
7. `stray/` added, `update --yes` → rc 1 blocked, beta rolled back (still holds
   the local edit), no leftovers
8. `stray/` removed, `update --yes` → beta `updated`, live link holds `# beta v3`
9. `profile install acme/kit` → rc 1 `acme/kit has no profile.yaml` (expected).
   `profile install acme/prof` (profile.yaml whose gamma source has no
   commit/digest) → installed
10. `update --check -p prof` → **crash** (see finding 1); `update -p prof --yes`
    → **crash after writing** profile.yaml with the new commit and digest
11. `restore` → `Removed 2 respec items`, restored claude-code, `state.json` empty,
    `~/.claude` snapshot **identical** to the original
12. `update --home /x` → rc 2, `No such option: --home`

## Findings

1. **Medium, bug (007, CLI ↔ profile install)**: a sourced item without a
   recorded `commit` makes `respec update --check` and `respec update` crash with
   `TypeError: 'NoneType' object is not subscriptable`. `commit` is optional in
   the schema, and `profile install` keeps whatever the fetched profile.yaml
   holds, so this is easy to reach. The failing lines are `cli._update_check`
   (`row.current[:12]`, cli.py:1056) and `cli._update_line`
   (`row['current'][:12]`). For `update`, the crash happens after
   `sources.update` has already saved profile.yaml and swapped the folders. The
   change is applied, but the user gets a traceback and rc 1. `--json` output
   is not affected. No test covers a source without a commit.
2. **Low, duplicate/vocabulary**: `sources.digest` and `unknown.digest` are two
   folder-hash helpers. They use different algorithms (`sources` hashes
   executable bits and lowercase kind tags; `unknown` hashes lengths and uppercase
   tags), and both emit `sha256:<hex>` under a YAML/JSON key named `digest`. They
   are never compared today, but the shared name and prefix make it easy to mix
   them up later. Suggestion: reuse one helper, or prefix one of them differently.
3. **Low, duplicate**: `sources._label` repeats `entry.parent.resolve() / entry.name`,
   which is `unknown.real`. This adds to the pre-existing `switch._real`
   duplicate. `restore._kind` vs `unknown._kind` (from the last report) is still
   there.
4. **Info**: `sources.BASE_URL_ENV`/`SHORTHAND`/`SCP_LIKE`/`base_url()` are
   aliases of the `profiles` constants, not separate copies, so the patterns
   cannot drift. Vocabulary (`source`, `update --check`, modpack-style
   `profile install`, owned locally) matches spec decision 8.
