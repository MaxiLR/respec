# t003 review 4: interruption-safe switching journal (fix round 3)

- Reviewer: fresh and independent; I did not implement this work.
- Range: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..4cb420b38e395657a7a6b41ffb88003061969a41`. Focus: `0156862..4cb420b`, plus regressions.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`, clean, HEAD `4cb420b`.
- Inputs: ticket 003, the 003 map in `runs/int-3e563b6.md`, `spec.md` as amended by `orchestration.md`, reviews 1 to 3, and `runs/t003-impl-4.md` (treated as unverified claims).
- Only temp homes were used. No guard denied any action. I changed no code, tickets or git state.

## Verdicts

- spec-compliance: **PASS**
- code-quality: **PASS** (non-blocking items below; N18 is recommended before shipping)
- tests-rerun: **PASS**
- blocking: **0**

## Gates rerun (fresh, at `4cb420b`)

| Gate                                                  | Result               |
| ----------------------------------------------------- | -------------------- |
| `uv sync --frozen`, then `uv run pytest -q`           | 509 passed in 178.1s |
| `uv run black --check src tests`                      | 40 files unchanged   |
| `npx prettier --check README.md "src/respec/**/*.md"` | clean                |
| `uvx pyflakes` on the changed source and test files   | clean                |

## (a) P1: fixed

Harness: `scratchpad/r4rv/perf/perf.py`, the same as review 3's (two profiles of 20 skills with 5 files each, 10 shared, 3 targets, links mode, the real CLI, 5 runs each, median).

| Source tree                               | `use a` (first) | `use b` (switch) | `use a` (back) | `status` |
| ----------------------------------------- | --------------- | ---------------- | -------------- | -------- |
| `0156862` (review 3 HEAD)                 | 1.164s          | 2.080s           | 2.081s         | 0.148s   |
| **`4cb420b` (HEAD)**                      | **0.190s**      | **0.264s**       | **0.261s**     | 0.139s   |
| HEAD + plain `os.fsync` on per-item saves | 0.192s          | 0.266s           | 0.261s         | 0.138s   |
| HEAD + `F_BARRIERFSYNC` on per-item saves | 0.232s          | 0.351s           | 0.346s         | 0.137s   |

- A switch is back to about 0.26s, close to the 0.25s target and in line with review 3's `c7f460c` figure (0.258s).
- The flush-count guard test (`tests/test_journal.py::test_a_switch_flushes_to_disk_a_fixed_number_of_times`) is meaningful. It counts real `_flush_to_disk` calls during a real `use b` with 2 and with 20 skills across 3 targets, and asserts they are equal and at most 8. A per-item flush would make the counts differ (the implementer reports 490 vs 58 before the fix). It does not check that the boundaries are flushed: removing every flush (count 0) would still pass. That is minor (N20).
- Every journal boundary is durable: `begin`, `set_phase` and `_clear` (which also covers the failure and discard paths). Each switch's final non-durable save (`switch.py` around line 769) is followed by `_clear`'s durable save. `profile.yaml` writes stay durable.

## (b) Durability trade-off

### Simulation: state.json reverted to its last fully flushed content

Harness: `scratchpad/r4rv/kill4/pdriver.py` and `p1.py` to `p3.py`. A wrapper around `state.sync_folder` copies `state.json` each time a durable save completes. The child is SIGKILLed mid-change. `state.json` is then replaced by the last durable copy and the filesystem is left as it was. This is a power loss in which every per-item record since the last boundary is lost.

| Case                                                       | After the revert                       | `recover`                                                                           | Then `status`                                                                                  | Deleted                                                                                 |
| ---------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| First `use a`, links, killed at the 4th or 9th `installed` | 0 records; 4 or 8 links on disk        | `rolled-back`: "no profile is active", plus "profile 'a' could not be activated: …" | the links are listed as `unknown symlink`, with "Resolve them with 'respec adopt' …"           | nothing                                                                                 |
| The same in copy mode                                      | 0 records; copied folders on disk      | `rolled-back`, the same                                                             | `unknown folder` entries, adopt offered                                                        | nothing                                                                                 |
| Switch a to b, links, killed at the 3rd `installed`        | a's 18 records; some b links on disk   | `finished`                                                                          | b fully active, no unknown entries (links that point at b's own sources are taken as respec's) | nothing                                                                                 |
| Switch a to b, links, killed at the 3rd `removed`          | a's records back; 3 links already gone | `finished`                                                                          | b fully active                                                                                 | a's own `.agents/skills/k0..k2` links, still recorded as respec's: the expected removal |
| Switch a to b, copy mode, killed at the 3rd `installed`    | a's records; b's copies on disk        | `rolled-back`: "no profile is active and respec's skills were removed"              | b's copies listed as `unknown folder`, adopt offered                                           | nothing                                                                                 |

`use a` after the first case refuses with the full list and offers `respec adopt --remove <name>` or `--unknown remove`. With no active profile, add is not offered: "No profile is active, so they can only be removed (each is backed up first)". That is the existing rule. Nothing unrecorded was deleted in any case, so the implementer's claim holds under this model.

### Judgement

The trade-off is acceptable for this ticket. The spec and ticket cover crashes as kills. Kills are fully covered, because each save is still a temporary file plus an atomic rename. The README now says the per-skill records are not flushed. It does not say what a user sees after a power loss (respec's own entries listed as unknown, to be resolved with `adopt`). One sentence would close that (part of N18).

### N18 (non-blocking, recommended): per-item saves drop the data flush before the rename

- **Location:** `src/respec/state.py` `save_state`. With `durable=False`, it calls `temporary.write_text(...)` and then `os.replace` with no `fsync`.
- **Scenario:** a power loss after the rename's metadata reaches the disk but before the temporary file's data does. The file system makes no ordering promise without a flush. `write_durably`'s own docstring names this hazard: it flushes "so a rename of the file that follows never exposes an empty file after a power loss".
- **Result:** an empty or truncated `state.json`, not the earlier version that the implementer's argument and the `save_state` docstring assume ("recovery never needs more than the last of them"). I reproduced the consequence by writing an empty `state.json` after a kill mid-`use`. `status`, `recover`, `recover --rollback` and `use a` all exit 1 with "invalid state file …: Expecting value". The only way out is deleting `state.json` by hand, and that also drops the journal, the records and the active profile.
- **Impact:** low probability, but every command is blocked and there is no recovery path. Under the earlier `c7f460c` design (plain `fsync`), this could not happen.
- **Fix:** keep a plain `os.fsync` on the temporary file for per-item saves, and keep `F_FULLFSYNC` plus the folder flush at the boundaries. I measured this: 0.266s for a switch, against 0.264s now, so it costs nothing measurable. `F_BARRIERFSYNC` (value 85 on macOS) gives true ordering at about 0.35s. Also correct the `save_state` docstring, and add the user-visible power-loss outcome to the README.

## (c) Real-SIGKILL matrix: no regression

I copied review 3's harness to `scratchpad/r4rv/kill4/` and reran `s1`, `s2C`, `s2D`, `s3E`, `s3F`, `s4`, `s5`, `s6`, `s9`, `s10`, `s11`, `s12`, `s13`, `s15` and `s16` at HEAD. Outputs are in `kill4/out/`. I diffed them against `kill3/out/` after normalizing timestamps, commit hashes and the path-length-dependent slice offsets.

These cover `use` (first use, switches, links and copy mode), `restore`, `adopt --add/--remove/overwrite`, `layer repair`, `update`, `add` from git, local `add`, `remove` and `profile install`.

- **Identical:** `s1`, `s2C`, `s2D`, `s3E`, `s3F`, `s4` (B1 to B3), `s6`, `s9`, `s10` (C1, C2 and the N12 Ctrl-C cases), `s11` (B4), `s12` and `s13` (N11 remove). `s12`'s traceback is the same harness error as in review 3.
- **Changed only as intended:**
  - `s5`: the N17 and N10 wording. Malformed journals give "An interrupted 'update' change …" instead of "profile None".
  - `s15` G3 (N14): a missing `up` with `.up.old` is now put back, and the result is `updated`, where it was `skipped-local-edits`.
  - `s15` G6 (N13): the kill mid-drop now recovers cleanly, and the next update gives `updated`, where it was refused.
  - `s16` (N15): for a non-active profile, the message is now "it is not the active profile, so no links changed". A `rolled-back` on a non-active profile no longer claims "the links match it".
- `test_tui_sync_reports_and_resolves_an_interrupted_switch` passes in the full suite. `tui.py` and `sync.py` are unchanged in this round.

## (d) N13 and N14: fixed

- **N13:** `_settle_foreign_old` renames a verified-redundant `.old` to `.<skill>.dropping` before calling `rmtree`. `_replace` and `_recover_update` both remove `.dropping` folders. This is confirmed by `s15` G6 under a real SIGKILL at unlink 4 (`after=['a','up']`, then `updated`), and by the new test, which passes.
- **N14:** `_update` calls `_put_back_old` before the local-edit check. That is one rename, only when the live folder is missing and `.old` is a real folder. `s15` G3 now gives `updated`, and the README wording matches.
- **N15, N16 and N17:** fixed as claimed (`s16` and `s5` above). Recovery now reads `swap["old"]`.

## Non-blocking findings

- **N18:** described in (b). Recommended before shipping, since the fix is one line with no measurable cost.
- **N19: recovery's "could not be activated" note cuts off the entry list.**
  - Location: `src/respec/journal.py` around line 741: `first = str(error).splitlines()[0]`. This dates from `a763a63`.
  - Scenario: recovery of a `use` journal hits unknown entries, after a power loss as in (b), or with a user entry in the way. The text output ends in "…sit where it would install or remove a skill:" with nothing after the colon. Neither the entries nor the `adopt` hint are shown.
  - Impact: the outcome is truthful and `status` and `use` list the entries, but the recover message reads as truncated. Drop the trailing colon, or include the count and the `adopt` hint.
- **N20: the flush test does not pin the boundaries.** `test_a_switch_flushes_to_disk_a_fixed_number_of_times` would pass with zero flushes. A lower bound would catch that (for example `few >= 3`: begin, phase, end).
- **N21: recovery removes every `.*.dropping` folder in the skills folder without checking it.** Location: `journal._recover_update`, the glob over `.*.dropping`. A folder of that name in a profile's `skills/` that respec did not make would be deleted. The risk is low because the folder is respec-managed and the name is specific. `_replace` limits the removal to the skill it is updating, and recovery could do the same: remove only the journaled swaps' skills.
- **N22: `_put_back_old` runs only when an update is available.** For an up-to-date skill whose folder is missing while `.old` exists, nothing is put back. This is minor, and the README does not promise otherwise for that case.

## Scope

The changes in `0156862..4cb420b` stay within review 3's P1 and N13 to N17. I wrote only this report and scratch files under `scratchpad/r4rv/`.
