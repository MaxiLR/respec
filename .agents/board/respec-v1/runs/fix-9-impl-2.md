# fix-9 implementation 2 (fix round 1)

- **Status:** DONE
- **Branch:** `codex/respec-v1-fix-9`
- **Head:** 55362bc → cb82293
- **Base:** 374b7f2 (not rebased)
- **Input:** `runs/fix-9-review-1.md`

## Changes

- **B1 (blocking):** I kept the current output and documented it exactly.
  - **README, "Running two at once":** a refused `--json` run prints on
    stdout:
    - `use`, `adopt`, `restore` (also `--release-only`) and `recover`: their
      usual keys, empty or as on disk, plus `error`;
    - every other command: only `error` and `warnings`.
  - **README, JSON contract `error` bullet:** other commands print errors on
    stderr only. The one exception is the busy refusal, which prints `error`
    and `warnings` on stdout. A refused combination of options still uses
    stderr only.
  - **`src/respec/shipped/respec/SKILL.md`:** a new ground rule describes the
    lock, the 1 s wait, the exact JSON shapes, retrying, and that reads never
    wait.
  - **`tests/test_json_contract.py`:** `test_a_change_refused_while_another_respec_runs_prints_the_documented_json`
    covers all 22 mutating invocations: `add`, `remove`, `enable`, `disable`,
    `update`, the 10 `layer` changes, `profile new`, `profile install`,
    `use`, `adopt`, `restore`, `restore --release-only` and `recover`.
    - The lock is held by a real subprocess paused inside `disable`.
    - For each invocation it asserts rc 1, the exact key set, the message,
      `warnings == []`, empty collections and no undocumented nulls.
    - It passes against the existing output; this is the docs-only fix the
      reviewer suggested.
- **N1:** `journal.pending` now enters `lock.reading(respec_home)` first.
  - If another process or thread holds the lock, it returns None without
    reading.
  - Otherwise it reads `state.json` while holding `LOCK_SH`, so no change
    can begin or end during the read.
  - `lock.busy()` is now a thin wrapper over `reading`.
- **N3:** the lock is now thread-aware.
  - Each `_Hold` records its owner thread. Reentry works only in that thread.
  - Another thread waits and then fails with `Busy`, exactly as another
    process would.
  - `holds()` is per thread, and `reading()` reports a lock held by another
    thread as busy.
  - The `_guard` mutex is no longer held while waiting, which fixes the
    `holds`/`busy` stall noted in N2. The 1 s UI wait itself stays, as
    allowed.
- **N4:** every fresh exclusive acquisition, which means no other process or
  thread holds the lock, sweeps `<respec home>/.state.json.*.tmp`.
  - The TUI has no unlocked writer that could still be writing one.
  - Read-only commands never sweep.
- **N5:**
  - `profile install` prints `messages.plural(n, 'skill')`, giving
    "(1 skill)".
  - `tui._plural` is removed; its 7 uses now call `messages.plural`, which
    has the same signature and output.
  - The trailing comments that Black had wrapped after
    `trees.delete_entry(...)` in `journal.py` now sit on the line above, as
    sentences.
- **N6:** not feasible without breaking atomicity, so documented.
  - The prompts run inside a change that has already started. For example,
    `use`'s unknown-entry handler runs inside `switch.use`'s journal, and
    adopt/update decide per entry mid-change.
  - Releasing the lock there would let another process see or recover a live
    journal.
  - README "Running two at once" now says the lock is held while a prompt
    waits for an answer, and why. The shipped skill mentions it too.
- **N2:** left as is, as allowed.

## Criterion → test (red on HEAD 55362bc src, green now)

| Finding | Test                                                                                                | On 55362bc src                       |
| ------- | --------------------------------------------------------------------------------------------------- | ------------------------------------ |
| B1      | `test_json_contract.py::test_a_change_refused_while_another_respec_runs_prints_the_documented_json` | passes (docs-only fix)               |
| N1      | `test_concurrency.py::test_a_change_that_ends_while_status_reads_is_not_called_interrupted`         | FAILED                               |
| N3      | `test_concurrency.py::test_a_change_from_another_thread_waits_its_turn_like_another_process`        | FAILED                               |
| N4      | `test_concurrency.py::test_temporary_state_files_of_a_killed_writer_are_cleaned_up`                 | FAILED                               |
| N4      | `test_concurrency.py::test_temporary_state_files_stay_while_a_change_runs`                          | passes (guard: no live-holder sweep) |
| N5      | `test_sources.py::test_profile_install_counts_one_skill_in_the_singular`                            | FAILED                               |

How the tests work:

- **N1:** the test patches `journal.load_state` so the paused change finishes
  between the read and the old lock check.
- **N3:** a second thread holds the lock while the CLI runs in-process
  `use a`. It must give rc 1 with "another respec is running" and change
  nothing.

The red runs used `git stash push -- src`, then the tests, then
`git stash pop`.

## Verification (after the last change)

- `uv sync --frozen`: "Audited 27 packages".
- `uv lock --check`: "Resolved 28 packages".
- `uv run black --check src tests`: 43 files unchanged.
- `npx prettier@3 --check README.md src/respec/shipped/respec/SKILL.md`:
  clean.
- No added line is longer than 88 columns.
- `uv run pytest -q`: **559 passed** in 198 s. The previous run had 553;
  6 tests were added. `test_shipped_skill_docs` passes with the new
  SKILL.md text.

## Concerns

- `release_all` at the end of a CLI command drops every hold in the process.
  That is correct for the CLI, which is single-threaded around the command.
  It also holds for in-process test runs, because the other threads in
  those tests use their own `exclusive` blocks and finish before or after.
