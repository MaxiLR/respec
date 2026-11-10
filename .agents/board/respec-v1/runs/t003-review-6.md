# t003 review 6 (fresh, independent)

- Range: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..4e0ea6fce26eccaa570dd9f1e05256d030c3a1e7`. Focus: round 5, `5532d01..4e0ea6f`.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`, clean, HEAD `4e0ea6f`.
- Method: real CLI (`.venv/bin/respec`) in temp homes under the scratchpad (`HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` all set). Real SIGKILL harnesses. Code reading.
- No guard denials.

## Verdicts

- spec-compliance: FAIL (1 blocking)
- code-quality: PASS
- tests-rerun: PASS. `uv run pytest -q`: 519 passed in 174s. `black --check src tests`: 40 unchanged. `prettier --check README.md "src/respec/**/*.md"`: clean.

## Focus checks

### (a) B1: rebuild, then a bare restore

| Scenario (real CLI)                                                                                                                                                                                       | Result                                                                                                                                                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Setup: `~/.claude/skills/mine` (mode 640), a dangling symlink, an empty user `~/.agents/skills`. Then `use a`, takeover records stripped (older-run case), empty `state.json`, `recover`, bare `restore`. | Exit 1. The message names `respec restore <backup>` and `--list`. `$HOME` is unchanged (tree fingerprint). `$RESPEC_HOME` is unchanged. No "from nothing". All three folders are `takeover_unknown: true`.                                                                                     |
| The same state, then `restore <run>`                                                                                                                                                                      | User content is byte-, mode- and symlink-identical to the original, including the empty `~/.agents/skills`. The empty `~/.omp/agent/skills` chain stays, which is the documented conservative case.                                                                                            |
| With records (the new default): `use a`, `use b`, empty `state.json`, `recover`, bare `restore`                                                                                                           | The rebuild re-derives every takeover from `manifest.json`. `--list` shows "takeover of agents, claude-code". The bare restore is identical to the original: nested binary file, mode 600, relative symlink, `.hidden`. The created `.omp` chain is removed. No `manifest.json` under `$HOME`. |

### (b) manifest.json is never restored

- `restore._plan` and `_restore_folder` read only `run/<target>/` subfolders. `manifest.json` sits at the run root, so it is never a candidate.
- No `manifest.json` or other respec metadata turned up under `$HOME` in any scenario.
- Test change in `tests/test_use_status.py`: `backed_up()` drops only the run-root key `manifest.json`. Every user entry is still compared exactly (`claude-code/loose.txt`, `first.txt`, `second.txt`). No byte-identical check of user content was weakened.
- `test_journal.py` was only extended.

### (c) N23 to N26

- **N23:** `created` comes back from the record. `.omp` was removed in the records case. Without a record the folders stay, as documented.
- **N24:** `--list` marks takeover runs from the records. The run that holds only the damaged `state.json` is hidden.
- **N25:** passes in the suite (both parametrisations). The journaled `.dropping` path is still settled by recovery (`journal.py:1047-1059`).
- **N26:** `state.json` at version 2, with an extra key. Commands run: `status`, `status --json`, `recover`, `recover --rollback`, `recover --json`, `use b`, `use b --json`, `restore`, `restore --list`, `update`, `adopt`.
  - Each exits 1 with "written by a newer respec … nothing was changed".
  - `recover --json` emits the JSON error vocabulary.
  - `$HOME` and every file under `$RESPEC_HOME` are unchanged (sha1). No backup run was created.
  - `status --json` writes no JSON on stdout. That matches the existing `StateInvalid` path, so it is not a regression.

### (d) SIGKILL and timing

- **`use`:** 3 targets, 21 skills per profile. `use b` was killed at 17 delays (0.02 to 0.34 s), then `recover`. Never a mix of a and b. `mine` was intact every time. `status` and `use a` succeeded afterwards. 0 bad.
- **`restore`:** the same setup, killed at 17 delays, then `recover` and `restore`. The final `$HOME` was identical to the original every time. 0 bad.
- **`update`:** a git source with 31 files, v1 to v2, killed at 15 delays, then `recover`. Always exactly v1 or v2 across all files, never mixed. No dot leftovers. The next update reached v2. 0 bad.
- **`use` timing:** 20 skills, 3 targets, links mode. 0.19 s for the first use. 0.25 s for each later switch (6 runs).

## Findings

### B2 (blocking): permanent restore dead end when no takeover made a backup run

- **Location:** `src/respec/switch.py` `_take_over`. `_record_takeovers` is called only `if run_dir is not None` (around lines 371-373). Also `src/respec/restore.py` `_plan`, the `takeover_unknown` refusal (around lines 231-242), and the README "After a power loss" section.
- **Failing scenario (real CLI):**
  1. Fresh user: `~/.claude/skills`, `~/.agents/skills` and `~/.omp` do not exist.
  2. `respec use a` creates no backup run, so no takeover record is written anywhere.
  3. A power loss leaves `state.json` empty. `respec recover` rebuilds it and marks all three folders `takeover_unknown`.
  4. `respec restore` refuses: "Name the backup run … ('respec restore --list' shows them)". `respec restore --list` prints "No backups.".
  5. No run exists to name, and `respec use` never takes over again. respec has no way to release the folders. The user must hand-edit `state.json`.
- **A related case:** a later takeover of a new target whose folder was missing also leaves that target `takeover_unknown` with no record.
- **Impact:**
  - `respec restore` is unreachable for good, which breaks spec user story line 42 ("I can try respec and undo it").
  - The recovery guidance is false: it points to a list that is empty. This misses the "recover consistently and truthfully" requirement.
  - It is a regression for exactly this case. Round 5's bare restore ("from nothing", remove empty created folders) was correct here, because nothing existed.
- **Suggested fix:** also persist the takeover record when no folder was copied. For example, create the run with only `manifest.json`; `list_backups` already hides runs that hold no target, and `_takeovers_on_disk` reads all runs. Alternatively, keep a separate takeover log.

### N27 (non-blocking, data-safety adjacent): an unflushed manifest rewrite can disable restore of that run

- **Location:** `src/respec/switch.py` `_record_takeovers`, `manifest.write_text(...)`.
  - The write is not atomic and has no fsync.
  - It now runs on every takeover, after the backup checkpoint, rewriting the manifest that `_record_backed_up_items` may already have written.
  - It runs before the durable `journal.mark(None)`.
- **Failing scenario:** the manifest ends up empty or truncated. This happens through a power loss after `use` (only `state.json` is flushed), or a kill between truncate and write. Simulated by emptying the file:
  - `respec restore` and `respec restore <run>` both fail: "invalid backup manifest … Expecting value".
  - `_recorded_at_backup` raises on it.
  - `_takeovers_on_disk` silently skips it.
- **Impact:** the takeover backup is still on disk, but respec cannot restore it until the user deletes or repairs the manifest. Before round 5, a manifest existed only in the rare shared-folder case. Now every takeover run has one.
- **Suggested fix:** write it through the existing temp, fsync and rename helper used for `state.json`. Optionally treat an unreadable manifest as "no takeover record" with a clear hint.
- **Related, pre-existing:** the backup copies themselves are not fsynced either.

### N28 (non-blocking, truthfulness): a stale takeover record is used after a later run-less takeover

- **Location:** `src/respec/journal.py` `_takeovers_on_disk` ("later runs replace earlier ones"). `restore` never marks a run's records as released.
- **Failing scenario (real CLI):**
  1. `~/.claude/skills/mine` exists. `use a`, then `restore` (released, `mine` back).
  2. The user deletes `~/.claude` entirely and runs `use a` again. All folders are missing, so there is no new run.
  3. Empty `state.json`, then `recover`. It reports "Each folder's takeover backup was found again".
  4. Bare `restore` "Restored claude-code from …/<run1>/claude-code". The user's deleted `~/.claude/skills/mine` is resurrected, and the respec-created `~/.claude` stays.
- **Impact:** additive, so no loss. But the restore report and the recover note are untrue, and the result does not match the pre-takeover folder.
- **Suggested fix:** the same as B2 (record every takeover), or invalidate a run's records when a restore releases them.

### Notes, not findings

- With `takeover_unknown`, a named restore leaves respec-created empty folders (`~/.omp/agent/skills`). This is documented and conservative.
- `status --json` and `use --json` emit no JSON on a state error. This is pre-existing and the same for `StateInvalid`.

## Scope and quality

- The changes are confined to the B1 and N23-N26 items, plus docs (README, shipped `SKILL.md`). No unrelated churn.
- The tests are behavioural and use independent expectations. No source-text assertions.
- The new code is small and readable. `_takeovers_on_disk` catches broad exceptions per run, which is acceptable for a best-effort rebuild.
