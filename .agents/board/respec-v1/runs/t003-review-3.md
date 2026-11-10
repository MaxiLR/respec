# t003 review 3: interruption-safe switching journal (fix round 2)

- Reviewer: fresh and independent; I did not implement this work.
- Range: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..0156862d50626c9a3a1d91b7860fd93e826c6f9b`. Review focus: `c7f460c..0156862`, plus regressions.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`. It was clean, with HEAD at `0156862`.
- Inputs:
  - ticket 003 and the orchestrator's requirements;
  - the 003 map in `runs/int-3e563b6.md`;
  - `spec.md`, as amended by `orchestration.md`;
  - reviews 1 and 2;
  - `runs/t003-impl-3.md`, treated as unverified claims.

## Verdicts

- spec-compliance: **FAIL**. All functional items pass: B4, N10, N11, N12 and the SIGKILL matrix. The failure is the performance limit the orchestrator set: a real `use` now takes more than 1s (P1).
- code-quality: **FAIL**. P1 is a blocking performance regression.
- tests-rerun: **PASS**
- blocking: **1** (P1)

## Gates rerun (fresh, at `0156862`)

| Gate                                                  | Result                                  |
| ----------------------------------------------------- | --------------------------------------- |
| `uv sync --frozen`, then `uv run pytest -q`           | 505 passed in 249.1s (wall time 4:09.8) |
| `uv run black --check src tests`                      | 40 files unchanged                      |
| `npx prettier --check README.md "src/respec/**/*.md"` | clean                                   |
| `uvx pyflakes` on the changed source and test files   | clean                                   |

## Real-kill harness

- Location: `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/kill3/`. It is a copy of review 2's `kill2/` with three new scripts:
  - `s15.py`: B4 followed by an update to v3, and the foreign `.old` cases;
  - `s16.py`: local `add` and `remove` (N11), and N10;
  - `s17.py`: the N10 messages.
- How it runs:
  - It runs the real CLI in a child process. `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` point to temp folders, with real defaults (shipped skills and three targets).
  - The child SIGKILLs itself at checkpoints, at `copyfile` or `unlink` calls, after a function returns, or at the Nth unlink after a checkpoint. A `sigint:` mode raises `KeyboardInterrupt`.
- Outputs are in `kill3/out/`.

## (a) B4 and the foreign `.old`: fixed

**B4 is fixed** (`s11.py`, `s15.py` G1). I SIGKILLed `update` from v1 to v2 at unlinks 1, 3, 8 and 14 after the `installed` checkpoint, with the journal at phase `refresh` and `.up.old` partly deleted:

- `recover` reports `finished`. When files were already deleted, it adds: "removed the rest of …/.up.old: this update's previous files of 'up', whose removal the interruption had cut short". That is truthful. At unlink 1, nothing had been deleted yet, so the full `.old` is removed silently, as normal cleanup.
- Afterwards there is no `.up.old`, and `up` is at v2.
- The next `update` returns `up-to-date`. With upstream moved to v3 (G1), the update gives `updated` and `up` is at v3.
- The false note "not from this update" is gone.

The rule is sound. In a committed recovery, the `.old` of a journaled swap is this run's own:

- `_replace` settles or refuses any existing `.old` before it journals the swap;
- the journal keeps other writers out;
- `committed` is now decided by the `profile.yaml` digest.

**Foreign `.old` (`s10.py` C1 and C2, `s15.py` G2 to G5):**

| Case                                                                | Result                                                                                                                          |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| C2: `.up.old` byte-identical to `up`                                | Removed, then `updated`                                                                                                         |
| G2: `.up.old` held only by a backup run (`backups/*/profiles/w/up`) | Removed, then `updated`; the backup run is kept                                                                                 |
| C1: `.up.old` with content that cannot be verified                  | Exit 1 with JSON `result: "error"` and a clear message. Every profile file and `state.json` is byte-identical before and after. |
| G4: `.up.old` holds a unique file                                   | Refused; the unique file is kept                                                                                                |
| G5: `.up.old` is a regular file                                     | Refused; the file is untouched                                                                                                  |

## (b) N10, N11, N12

- **N12: fixed** (`s10.py` C4). After Ctrl-C at `phase:refresh`, recovery reports `rolled-back`, `up` is back at v1 with the v1 commit, and `update --check` shows the update as available. Ctrl-C at `profile-saved` and `swapped-in` also gives `rolled-back` at v1. Ctrl-C at `installed` gives `finished` at v2. Every case is consistent.
- **N10: fixed** (`s16.py`, `s17.py`). An `update` journal without `profile`:
  - `recover` fails with "…journal in state.json is malformed (KeyError('profile')). It stays recorded. 'respec recover --rollback' discards the journal…".
  - `recover --rollback` discards it and exits 0.
  - `use a` then works.
  - A mutating command (`disable tdd`) is refused while the journal is pending.
- **N11: fixed** (`s13.py`, `s16.py`).
  - **`remove`**: SIGKILL after `save_profile`, at `step:done` or at `removed`:
    - a `links` journal is pending and shows in `status`;
    - recovery reports `finished`;
    - the `lint` folder is deleted, `profile.yaml` and the links agree, and the state is consistent.
    - A kill at `links:begin` gives `rolled-back`: the folder, its content and the link are intact.
    - A remove from a non-active profile, killed after the save, gives `finished`, the folder is gone, and the active profile is untouched.
  - **Local `add`**, to the active profile and to a non-active one:
    - A kill at `links:begin`, at `copy:1` or at `copy:6` gives `rolled-back`. There is no partial copy, the source (13 files) is intact, and a re-add succeeds.
    - A kill after `save_profile`, at `install:start` or at `installed` gives `finished`. The copy is complete and linked when its profile is active.
    - The journal records `created: ['mys']` before the copy starts.

## (c) SIGKILL matrix: no regression from B1 to B3

I reran `s1` to `s6` and `s9` and compared each with review 2's `kill2/out`, ignoring path and timestamp differences:

- **Identical:** `s1` (first `use` in copy mode, `use b` with links, `use b` in copy mode), `s2C` (`restore` with links and in copy mode), `s2D` (`adopt --add` and `--remove`), `s3F` (`update`, `add` from git, `profile install`) and `s9` (shipped refresh).
- **`s3E` (`layer repair`) and `s6` (adopt overwrite):** these differ only in the home path. The "record not managed: c" result predates this change, as review 2 showed.
- **`s5`:** it differs only where expected:
  - R2: the `remove` folder is now deleted, which is N11;
  - R3: `recover --rollback` now discards a journal without `profile`, which is N10.
- **`s4` (B1 to B3):**
  - B1: the unlisted folder and its content are kept, and recovery says `rolled-back`.
  - B2: `USER-EDIT` is intact and the stale `.old` is kept.
  - B3: recovery says `finished`, `up` is at v2, and the next update reports `up-to-date`.

Integration checks:

- Recovery still uses fix-6's `adopt._clean_leftovers` for adopt staging folders, and `_settle_foreign_old` reuses `adopt._backed_up`.
- fix-5's `_undo_adds` is unchanged.
- `tui.py` and `sync.py` are unchanged since review 2, and `test_tui_sync_reports_and_resolves_an_interrupted_switch` passes.
- A refused `use --json` still reports `active_profile: "a"`.

## (d) Performance

Setup:

- two profiles of 20 skills each (5 small files per skill), 10 of them shared;
- 3 targets (`claude-code`, `agents`, `oh-my-pi`), links mode;
- the real CLI, 5 runs each, measured with no other load;
- the script is in `scratchpad/perf3/perf.py`.

| Source tree                                            | `use a` (first) | `use b` (switch) | `use a` (back) | `status` |
| ------------------------------------------------------ | --------------- | ---------------- | -------------- | -------- |
| `3e563b6` (base)                                       | 0.156s          | 0.213s           | 0.212s         | 0.135s   |
| `c7f460c` (plain `fsync`)                              | 0.180s          | 0.258s           | 0.254s         | 0.137s   |
| `0156862` with `F_FULLFSYNC` disabled (one-line patch) | 0.175s          | 0.253s           | 0.252s         | 0.135s   |
| **`0156862` (HEAD)**                                   | **1.174s**      | **2.077s**       | **2.091s**     | 0.143s   |

Counting calls to `_flush_to_disk` in a separate, instrumented run gave 274 flushes for the first `use` and 490 for a switch. That is `state.json` plus a folder flush after every installed or removed entry, and each `F_FULLFSYNC` costs about 4ms.

## Blocking finding

### P1: `F_FULLFSYNC` on every `state.json` write makes a real switch about 8x slower (2.1s for 20 skills across 3 targets)

- **Location:** `src/respec/state.py` `_flush_to_disk`. `write_durably` and `sync_folder` both call it, and every `save_state` uses them. That includes the per-item saves in `switch.remove_installed` and `switch._install`, inside `use`.
- **Failing scenario:** run `respec use b` with the active profile `a` (20 skills each, 3 targets, links mode). It takes 2.08s at HEAD and 0.25s at `c7f460c`. The first `use` takes 1.17s. With `F_FULLFSYNC` disabled, HEAD is back to 0.25s, so `F_FULLFSYNC` alone causes the slowdown.
- **Impact:**
  - Both timings are above the orchestrator's threshold of about 1s for a real `use`. Every switch, refresh, `add` and `remove` on macOS slows down in proportion to the number of skills times targets.
  - Every TUI action that refreshes waits the same time.
  - The full suite nearly doubled (137s to 249s).
  - It buys little: the journal's correctness rests on write ordering and the phase records, not on drive-cache durability for every per-item record.
- **Fix direction**, as suggested in the brief:
  - Keep `F_FULLFSYNC` only where the journal changes phase: `journal.begin` (the journal is written), `mark`/`set_phase`/`note` before a destructive step, `_clear`, and `profiles._write`.
  - Use plain `fsync` for the per-item `save_state` calls inside a journaled run. A lost per-item record after a power loss is already settled by the journal's recovery, which reconciles from disk.
  - Alternatively, take a `durable=` flag on `write_durably`.
  - Then rerun the timing above. The target is under about 0.3s for a switch.

## Non-blocking findings

- **N13: a kill while settling a redundant foreign `.old` leaves a partial `.old` that then blocks `update`.**
  - Location: `src/respec/sources.py` `_settle_foreign_old`, the `shutil.rmtree(old)` call.
  - Scenario (`s15.py` G6): `.up.old` is byte-identical to `up`, and `update` is SIGKILLed at unlink 4 while deleting it, before the swap is journaled.
  - Result:
    - recovery says `rolled-back` and "left …/.up.old in place: it is not from this update…", which is true;
    - the partial `.old` is now a subset of `up`, so it is neither identical to `up` nor in a backup;
    - the next `update` refuses `up`.
  - Impact: no data is lost, since the content was redundant. However, the user is blocked by a folder respec partly deleted itself. This is the same pattern as B4, but it needs a rare precondition.
  - Fix: rename the `.old` to a unique trash name before deleting it, or journal the drop (for example, note it under `swaps` or a `dropping` key first).
- **N14: the README's "put back when the skill folder is gone" cannot happen through `update`.**
  - Scenario (`s15.py` G3): `up` is missing and `.up.old` exists.
  - Result: `update` reports `skipped-local-edits` before `_replace` runs, so `_settle_foreign_old`'s put-back never runs. The skill stays missing, with its content in `.up.old`.
  - Impact: nothing is lost, and this predates the change. Still, the README claim in "Interrupted changes" is inaccurate for this path. Reword it, or let `update` (or Sync) put the folder back first.
- **N15: the message wording for a non-active profile is misleading.**
  - Location: `journal._recover_links`. For a `remove` or local `add` on a non-active profile, the message says "the links of the active profile match its profile.yaml".
  - The active profile is a different one. The outcome itself is correct.
- **N16: the swap journal stores an `old` path that recovery never reads.**
  - Location: `sources._replace`, `swap["old"]`. Recovery recomputes the path instead.
  - This is harmless, but it is dead data.
- **N17: `describe()` prints "profile None" for an `update` journal without `profile`.** This is cosmetic.

## Scope

The changes in `c7f460c..0156862` stay within the ticket, the 003 map and the review-2 findings. No guard denied any action. I changed no code, tickets or git state. I wrote only this report and the scratch harnesses (`kill3/`, `perf3/`) under the scratchpad.
