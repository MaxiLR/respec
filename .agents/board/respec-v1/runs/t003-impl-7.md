# t003 implementation 7: fix round 6

- Status: DONE
- Branch: `codex/respec-v1-t003`, not rebased
- Range: `4e0ea6f..2f55a08`, one commit
- Files: 10, one of them new
  - Source: `takeovers` (new), `switch`, `journal`, `restore`, `cli`.
  - Docs: README and the shipped `respec/SKILL.md`.
  - Tests: `test_journal`.

## Fixes

### B2: durable takeover records, structurally

- **Takeover log.** The new `respec/takeovers.py` keeps a takeover log at `<respec home>/takeovers.json`, apart from `state.json`.
  - Contents: `{version, records: [{target, skills_dir, backup|null, taken_over_at, created, released}]}`.
  - Write path: a temp file, then `fsync`, `os.replace` and a folder `fsync`.
  - `switch._take_over` appends one record per new target whenever it takes over. This includes targets whose folder did not exist, where no backup run is made.
- **Rebuild.** `journal.rebuild_state` takes ownership, `backup` and `created` from the latest unreleased record per target (`takeovers.current`). Only a target with no such record is marked `takeover_unknown`. That happens with an older respec, or when the log itself is lost.
- **Manifests.** They no longer carry `takeover` records; the round-5 `_record_takeovers` was removed.
- **`restore --list`.** It marks takeover runs from the log (`takeovers.backup_targets`) plus `state.json`.
- **Test** (red before the fix): `test_folders_that_did_not_exist_are_released_after_a_rebuild`. Nothing existed, so `use a` made no run. After a rebuild, a bare `restore` exits 0, removes `~/.claude` and `~/.agents`, and leaves `owned` empty.

### Explicit way out: `respec restore --release-only`

- **Behaviour.** `restore.release_only` is journaled as `restore` with `release_only`; recovery finishes it. It does the following:
  - It removes only recorded items that `unknown.is_managed` verifies as respec's: a link into respec's folders, or a copy with the recorded digest.
  - It lists unverifiable records under `kept` and leaves them in place.
  - It restores nothing.
  - It removes only folders that were recorded as created, and only once empty.
  - It marks the log records released, clears `state.json` and keeps every backup run.
- **CLI.** The JSON payload is the restore payload plus `kept`. The text output says what was removed, what was kept, and that nothing was put back.
- **Refusal.** The `takeover_unknown` refusal now names both `restore --list` and `--release-only`. So does the rebuild note.
- **Test** (red): `test_release_only_removes_only_what_respec_can_verify`. The log is deleted first, so the state is `takeover_unknown`. The test checks that:
  - the bare restore refuses and names `--release-only`;
  - release-only removes the 4 respec links, keeps `mine` and the not-recorded-as-created `agents` folder, reports `restored` as `{}`, empties `owned`, and leaves the backup run in place.

### N27

- **Manifest writes.** `_record_backed_up_items` writes the manifest atomically with `fsync`.
- **Unreadable manifest.** An unreadable manifest no longer raises. The run's entries are put back as the user's, so nothing is left out.
- **Reporting.**
  - The CLI adds a typed warning `unreadable-manifest` with `path` and `message` to the JSON `warnings`, and prints it on stderr.
  - The list resets per command.
  - The README documents the type.
- **Test** (red): `test_an_empty_manifest_does_not_stop_a_restore`

### N28

- **Release marking.** `restore._apply` and `release_only` mark the records of released targets as `released` before clearing the state. A rebuild never reuses them.
- **Test** (red): `test_a_released_takeover_is_not_reused_by_a_rebuild`
  - It runs `use`, `restore`, the user's `rm -rf ~/.claude`, another `use` (with no run), then a rebuild and a bare `restore`.
  - Now `~/.claude` is removed and `mine` does not come back.

### Other

- The round-5 test helper that stripped manifest takeover records now deletes `takeovers.json` instead.
- One help string was reworded to avoid "keep", because `test_help_offers_only_add_and_remove` forbids that word on `restore --help`. It was the only failure of the first full run; affected suites were rerun afterwards.
- The README "After a power loss" section, the usage line, the warning types and the shipped `SKILL.md` were updated.

## Timing: real `respec use`, 20 skills, 3 targets, links mode

| Run                | Time  |
| ------------------ | ----- |
| first `use a`      | 0.19s |
| `use b` (a active) | 0.25s |
| `use a` (b active) | 0.24s |

## Verification

- `uv sync --frozen`: ok.
- `uv lock --check`: "Resolved 28 packages".
- `uv run pytest -q`: 522 passed, 1 failed in 179s, the SIGKILL matrices included. The one failure was the help wording.
  - After the wording fix, `tests/test_adopt.py`, `test_help.py` and `test_shipped_skill_docs.py` were rerun: 84 passed.
  - The only change after the full run was that help string.
- `uv run black --check src tests`: 41 files unchanged.
- `npx prettier --check README.md "src/respec/**/*.md"`: clean.
- `uvx pyflakes` on the changed files: clean, apart from the `handler` pattern already in `cli`.

## Concerns

- Homes whose takeovers happened before the log existed have no records. After a rebuild those folders are `takeover_unknown`, so the user names a run or uses `--release-only`.
- The log grows by one record per takeover. It is small and never pruned.
- The final full-suite run predates a one-string help change. The affected suites were rerun after it.
