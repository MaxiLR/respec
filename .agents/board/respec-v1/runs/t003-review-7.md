# t003 review 7 (fresh, independent)

- **Range:** `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..2f55a08a5be82c4e4c607ae9b00ce1a884d8d3db`.
  - Focus: round 6, `4e0ea6f..2f55a08`.
- **Worktree:** `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`, clean, HEAD `2f55a08`.
- **Method:**
  - The real CLI (`.venv/bin/respec`) in temp homes under the scratchpad, with `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` all set.
  - Real SIGKILL harnesses.
  - Code reading.
- No guard denials.

## Verdicts

- spec-compliance: PASS (0 blocking)
- code-quality: PASS
- tests-rerun: PASS.
  - **Full suite, rerun at HEAD after the final string fix:** `uv run pytest -q` gave 523 passed in 179s.
  - `uv run black --check src tests`: 41 files unchanged.
  - `prettier --check README.md "src/respec/**/*.md"`: clean.

## Focus checks (real CLI)

### (a) B2: folders that did not exist at takeover

| Scenario                                                                                                                                                      | Result                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Empty home; `use a`; empty `state.json`; `recover`; bare `restore`                                                                                            | Rebuild finds every record in `takeovers.json`. Restore exits 0: "Removed 15", each target "from nothing". `$HOME` fingerprint identical to before (empty). All 3 log records `released: true`; `owned` is `{}`. |
| Mixed case: `~/.claude/skills` with `mine` (mode 640), a relative symlink and a dangling symlink; `~/.agents` missing; `~/.omp/agent` present but no `skills` | `use a`, `use b`, empty state, `recover`, bare `restore` give a tree and fingerprint (modes, link targets) identical to before. Only `.omp/agent/skills` was removed; `.omp/agent/k.txt` stayed.                 |
| Existing folder, backed up: `use a`, wipe, `recover`, `restore`                                                                                               | Identical to before.                                                                                                                                                                                             |
| N28 path: `use`, `restore`, `rm -rf ~/.claude`, `use`, wipe, `recover`, `restore`                                                                             | `~/.claude` is gone, as before the second takeover. `mine` is not resurrected.                                                                                                                                   |

B2 is fixed.

### (b) `restore --release-only`

| Scenario                                                                                                                         | Result                                                                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Log deleted, state wiped, so every target is `takeover_unknown`. The user retargets one respec link (`sa1`) to their own folder. | Bare `restore` refuses and names `--release-only`. Release-only removes 14 links. It lists `sa1` under `kept` and leaves it. `mine` and the user's `~/.agents/skills` are untouched. `restored` is `{}`. The backup runs are byte-identical; `owned` is `{}`. The respec-created `.omp` chain stays, because creation is unknown without the log (conservative). |
| Normal state, log intact. Two installs turned into digest-recorded copies; one copy edited.                                      | The unedited copy and the links are removed. The edited copy is kept and reported. The created `.agents` and `.omp` chains are removed (from the log). The existing `.claude/skills/mine` stays.                                                                                                                                                                 |
| Second release-only; release-only with a named run                                                                               | Both exit 1, with "owns no folders" and "puts no backup back; name none".                                                                                                                                                                                                                                                                                        |
| After release-only, named `restore <run>`                                                                                        | Still works and puts the backup back.                                                                                                                                                                                                                                                                                                                            |

### (c) The takeover log (`src/respec/takeovers.py`)

- **Writes:** a temp file, then `write_durably` (`F_FULLFSYNC`), `os.replace` and `sync_folder`. They are atomic and flushed.
- **Release marking:** `restore._apply` and `release_only` mark every unreleased record of the released targets before `state.json` is cleared. `current()` drops a target on a released record.
- **N28:** fixed (see (a)).
- **Corruption:**
  - **Garbage log:** treated as no records, so `takeover_unknown`. The refusal is truthful and names both ways out.
  - **Bad field types:** for example `target` as a list, or `backup: 5`. Neither crashes rebuild, `--list` or restore.
  - **Newer `version`:** see N31.

### (d) N27: unreadable manifest

- **Truncated `{"version":1,"inst` manifest, bare restore:** exit 0. The tree is identical to before. A stderr warning names the path.
- **Empty manifest plus a rebuilt state, `restore --json`:** exit 0. `restored` names the run. `warnings` holds `{"type": "unreadable-manifest", "path", "message"}`.
- **Manifest writes:** they now use temp, fsync, replace and folder sync.

### (e) SIGKILL and timing

| Harness                                                                                             | Kills                 | Check                                                                                                                   | Bad |
| --------------------------------------------------------------------------------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------- | --- |
| First `use a` (takeover in flight). 3 targets, 20 skills, user content plus a partial `.omp` chain. | 29 delays, 0.01-0.29s | `recover`, then if owned: wipe `state.json`, `recover`, bare `restore`. The fingerprint equals the original every time. | 0   |
| `use b` (a active)                                                                                  | 17 delays             | `recover`: never a mix of a and b, and `mine` intact. Then wipe, `recover`, `restore` gives the original.               | 0   |
| `restore`                                                                                           | 17 delays             | `recover` (plus `restore` if still owned) gives the original fingerprint.                                               | 0   |
| `restore --release-only`                                                                            | 17 delays             | `recover` gives no respec links, user content byte-identical, created folders gone, `owned` `{}`.                       | 0   |
| `update -y`, git source with 31 files, v1 to v2                                                     | 18 delays             | Always all v1 or all v2. No dot leftovers. The next update reaches v2.                                                  | 0   |

`use` timing, links mode, 20 skills, 3 targets:

- First `use a`: 0.19s.
- Later switches: 0.24-0.25s over 6 runs.

## Findings (all non-blocking)

### N29: the rebuild note still says "found again in its run's manifest"

- **Location:** `src/respec/journal.py` `rebuild_state`, the `found_note` else branch, around line 764.
- **Scenario:** the exact B2 case (nothing existed, so there is no run at all). `recover` prints "Each folder's takeover backup was found again in its run's manifest."
- **Impact:** the message is untrue: no run or manifest exists, and the source is now `takeovers.json`. The outcome is correct. Reword it to name the takeover log.

### N30: release-only reports a missing path as "Kept … respec cannot verify it as its own"

- **Location:** `src/respec/restore.py` `release_only`. The `else` branch lists every record that `is_managed` rejects, including paths that no longer exist.
- **Scenario:**
  1. `use a`.
  2. The user deletes `~/.claude/skills/sa1`.
  3. `restore --release-only`.
- **Result:** it prints `Kept …/sa1`, though nothing is there.
- **Impact:** a small truthfulness slip; nothing is lost. Drop records whose path does not exist (`lexists`) silently, or report them as already gone.

### N31: no version check on `takeovers.json`

- **Location:** `src/respec/takeovers.py` `_load` and `_save`.
- **Scenario:** a log with `version: 2` (a newer respec).
- **Result:** it is read as v1, and the next `record`/`release` rewrites it as `version: 1`.
- **Impact:** this is inconsistent with fix-5's refusal of a newer `state.json`. A future schema could be silently downgraded.

### N32: a corrupt log is silently replaced, and the corruption is not reported

- **Location:** `src/respec/takeovers.py` `_load` returns `[]`; then `record()` writes only the new records.
- **Scenario:**
  1. The log is damaged externally.
  2. The next takeover overwrites it, so earlier records are lost without a warning.
  3. A later rebuild marks those targets `takeover_unknown`.
- **Impact:** the result is still truthful (refusal plus `--release-only`), and atomic writes make this rare. But the damaged file is neither kept nor reported. Consider moving it aside, as is done for `state.json`.

### N33: `restore --list --release-only` releases instead of listing

- **Location:** `src/respec/cli.py` `restore`. `release_only` is checked before `list_only`. `--unknown` and `--overwrite` are silently ignored too.
- **Scenario:** `respec restore --list --release-only` exits 0 and lets go of every folder.
- **Impact:** a read-only flag combined with a mutating one performs the mutation. Recoverable: a named `restore <run>` still works afterwards. Reject the conflicting flags.

### N34: release-only recovery does not report kept items

- **Location:** `src/respec/restore.py` `release_only` drops unverified records from `state.installed` as it goes. `journal._recover_restore` reruns `release_only` and returns a fixed message.
- **Scenario:** a kill after some items were kept.
- **Result:** `recover` reports "Finished letting go …" without naming them.
- **Impact:** a minor reporting gap. The items stay on disk untouched.

### N35: a rolled-back first `use` leaves unreleased log records

- **Scenario:** the first `use` is killed between `takeovers.record` and `journal.mark`.
  - The SIGKILL matrix hit this at 0.10s: the log held 3 unreleased records, and `recover` reported "Rolled back … no profile stays active".
  - The backup run may be dropped by `_settle_pending`.
- **Impact:** not reused in practice. Respec links only appear after a later takeover, which appends a newer record that `current()` prefers. `restore --list` may still mark a dropped or rolled-back run as a takeover. Information only.

## Scope and quality

- **Scope:** the changes are confined to B2, N27, N28 and the orchestrator-approved `--release-only` (orchestration.md line 310). Docs were updated: README, the warning vocabulary and the shipped `SKILL.md`. Removing the manifest `takeover` key and `_takeovers_on_disk` simplifies the code.
- **Tests:** the new tests are behavioural and use independent expectations. No existing test was weakened; the `drop_takeover_records` helper now deletes the log.
  - Gap: no test covers release-only of a digest-matched copy, or removal of created folders when the log is intact. I verified both by CLI above.
