# fix-9 review 2

- **Reviewer:** a fresh, independent, read-only reviewer who did not
  implement this work.
- **Diff:** `374b7f28815e7a7c919e65d0ddac7d18276dbb87..cb822930c2ea1025def60ca600b57d12e636abe0`.
  The focus was round 1, `55362bc..cb82293`. Worktree:
  `respec-worktrees/fix-9`, with a clean tree at HEAD `cb82293`.
- **Spec compliance:** PASS.
- **Code quality:** PASS.
- **Tests rerun:** PASS.
- **Blocking findings:** none.

## Gates rerun (fresh, in the worktree)

- `uv sync --frozen` and `uv lock --check`: ok.
- `uv run pytest -q`: **559 passed** in 203 s.
- `uv run black --check src tests`: 43 files unchanged.
- `npx prettier@3 --check README.md src/respec/shipped/respec/SKILL.md`: clean.
- No added line is longer than 88 columns.
- **Lock audit of the suite:** I added an ad hoc pytest plugin, loaded from the
  scratch directory (not committed). It wraps `state.save_state`,
  `takeovers._save` and `profiles._write`. It logs any call reached from
  `respec/cli.py` or `respec/tui.py` while the calling thread does not hold
  the lock.
  - Full suite: **0 unlocked writes**, with 559 passed.
  - Sanity check: in log-everything mode it recorded 621, 36 and 16 calls on
    the TUI and use/status tests, so the wrap was active.
  - This matters for N4: the sweep is safe only if no writer runs without the
    lock.

## Real-CLI checks (`.venv/bin/respec`, temp homes under the scratchpad only)

### B1: busy `--json` output against the README and SKILL.md

- **Setup:** a real `disable a0` was paused at `links:begin`, holding the
  lock. I ran all 22 mutating invocations with valid arguments (`add`,
  `remove`, `enable`, `disable`, `update`, the 10 `layer` changes,
  `profile new`, `profile install`, `use`, `adopt --all remove`, `restore`,
  `restore --release-only` and `recover`).
- **Result: 22/22 match** "Running two at once" and the `error` bullet of the
  JSON contract.
  - Every run exited 1, with `another respec is running` in `error`,
    `warnings == []`, empty stderr and no traceback.
  - The other commands printed exactly `{error, warnings}`.
  - `use`, `adopt`, `restore`, `restore --release-only` and `recover` printed
    exactly the key set of their own success run, plus `error`.
  - For `use`, `active_profile` shows what is on disk (`a`).
- `state.json` was byte-identical before and after the refused runs.
- **Without `--json`:** stdout is empty, stderr has `error: another respec
is running…`, and the exit code is 1.
- **Reads while the lock was held:** `status --json`, `update --check --json`,
  `restore --list --json`, `profile list` and `layer list` all returned 0. None
  of them waited or reported an interruption.
- SKILL.md's new bullet states the same shapes.

### N1: a live operation is never reported as interrupted

- **Hammer test:**
  - 4 threads looped `status --json` without pause.
  - Meanwhile, 30 times, a `use` was paused at `use:begin` and released
    mid-loop, followed by 60 back-to-back `use a`/`use b` switches.
  - Over 713 status runs there were **0 false `interrupted-operation`
    warnings**.
- **The fix:** `journal.pending` now checks the lock and reads the journal
  under one shared lock (`lock.reading`). This closes the read-then-probe
  window from review 1.
- **The new test is meaningful:** its patched `load_state` ends the change
  between the read and the probe, and it was red on `55362bc` according to the
  implementation report.
- **Same-thread reads:** `reading()` reports "not busy" to the thread that
  holds the lock. That is correct, because the thread's own journal is
  genuinely current.
- **No other readers to fix:** no other code path reports a pending journal.
  `cli._journal_reports`, `cli status` and TUI Sync all go through
  `pending()`.

### N4: the temp sweep never deletes a live writer's temp file

- **Concurrent writer:**
  - A real `use b` was paused inside `os.replace` on its second
    `state.json` save. At that point its uniquely named temp file had been
    written but not yet renamed, and the writer held the lock.
  - While it was paused, I ran 21 concurrent processes:
    - mutators: `use a`, `enable` and `recover`, all busy with rc 1;
    - readers: `status`, `status --json`, `profile list` and
      `restore --list`, all rc 0.
  - The writer's temp file **survived**. The writer then renamed it and
    finished with rc 0. The writer itself asserted that its temp file still
    existed.
- **Stale file:** I planted `.state.json.99999.deadbeef.tmp` before the
  writer started. The writer's own fresh acquisition swept it.
- **Afterwards:** no `.state.json.*.tmp` files were left, and the next `use`
  succeeded.
- **Why it is safe:**
  - `_sweep` runs only in `_try_take`, which means this process holds no
    hold and has just won `LOCK_EX`.
  - With the lock audit above showing no unlocked writers, no live writer
    can own a temp file at that moment.
  - A second thread in the same process cannot sweep while the first holds
    the lock, because `hold is not None` keeps it from calling `_try_take`.

### N3: thread safety in the TUI

- **Ownership:** `_Hold.owner` restricts re-entry to the owning thread.
  Another thread polls, does not hold `_guard` while it sleeps, and then
  raises `Busy`. `holds()` and `reading()` are per thread.
- **Matching threads:** each TUI site acquires and releases on the same
  thread.
  - The 11 `with lock.exclusive(...)` sites are synchronous blocks on the
    event-loop thread. None of them spans an `await`.
  - Git add runs `_changing` entirely inside the `asyncio.to_thread` job, so
    the worker thread takes and drops the lock.
  - `sources.check` (Check updates) is read-only and takes no lock.
- **Sync while git runs:** Sync on the UI thread while the git worker holds
  the lock now gets `reading() → True`, so it shows no false pending.
- **Test:** `test_a_change_from_another_thread_waits_its_turn_like_another_process`
  covers a mutation from another thread. A CLI `use` gets rc 1 and changes
  nothing.

### Concurrent race and SIGKILL

- **Race:** 12 rounds, each on 30 skills × 3 targets, each running 4
  concurrent processes: `use b`, `use a`, `enable b3 -p b` and
  `disable a4 -p a`.
  - 48/48 runs gave rc 0, with 0 busy and 0 tracebacks.
  - There were 0 false interrupted warnings, in the runs or in the
    `status --json` after each round.
  - All rounds were consistent: no journal remained, and every target folder
    equalled the active profile's enabled skills.
- **SIGKILL while holding the lock:**

| Kill point              | `status` | Next `use a` | Recovery    | Targets equal | Temp files |
| ----------------------- | -------- | ------------ | ----------- | ------------- | ---------- |
| `use b` @ use:begin     | pending  | rc 0, 0.20 s | rolled-back | yes           | none       |
| `disable` @ links:begin | pending  | rc 0, 0.28 s | rolled-back | yes           | none       |
| `use b` @ removed       | pending  | rc 0, 0.28 s | finished    | yes           | none       |
| `use b` @ installed     | pending  | rc 0, 0.25 s | finished    | yes           | none       |

No stale lock was left in any case.

### Other round-1 items

- **N5:** `profile install` now uses `messages.plural`. `tui._plural` is
  removed, and its 7 call sites use `messages.plural`, which gives the same
  output. The `journal.py` comments are now on their own lines. All of these
  are behaviour-preserving.
- **N6:** README "Running two at once" and SKILL.md both say that the lock is
  held while a prompt waits. This is accurate: the prompts run inside a
  journaled change.

## Findings

There are no blocking findings.

### R2-N1 (non-blocking, pre-existing, outside the diff): `status` can crash during a concurrent switch

- **Location:** `src/respec/unknown.py:53` (`is_managed`: `path.is_symlink()`
  followed by `path.resolve()`), reached from `switch.status`, which
  `cli.status` calls at `cli.py:661`.
- **Scenario:** in 4 status loops during 40 back-to-back switches, 2 of
  about 600 runs of `status --json` exited 1 with a `FileNotFoundError`
  traceback. A link that `use` removed between `is_symlink()` and
  `resolve()` caused it; on Python 3.12, `realpath`'s `readlink` is not
  guarded. The crash appeared in 1 of 3 attempts and is timing-dependent.
- **Impact:** a read-only command occasionally crashes during a concurrent
  change. It is transient, and a retry works. Status deliberately runs
  without the lock, as acceptance item 1 requires. The code is unchanged by
  fix-9, so this is pre-existing.
- **Suggested fix:** treat `OSError` in `is_managed` as "not managed", or
  read the link with `os.readlink` and catch the error.
- It is worth a follow-up ticket. It does not block fix-9.

### R2-N2 (non-blocking, docs nit): two adjacent SKILL.md bullets need reading together

- **Location:** `src/respec/shipped/respec/SKILL.md`, around lines 28–32.
- **Scenario:** the exit-code bullet still says that "other commands … print
  the reason on stderr". The new bullet that follows it carves out the busy
  refusal, which prints `{error, warnings}` on stdout.
- **Impact:** the two bullets are consistent when read together, but an agent
  that reads only the first would miss the stdout JSON. The README's `error`
  bullet states the exception inline. A short "(except a busy refusal, below)"
  in the first bullet would remove the ambiguity.

### R2-N3 (non-blocking, carried over from review 1 as accepted): a busy TUI action can freeze the UI for up to 1 s

- When an action is busy, the 1 s wait runs on the event-loop thread.
- `_guard` is no longer held during the wait, so `holds()` and `busy()`
  from other threads no longer stall.

## Scope

Round 1 touches only the lock, the journal's `pending`, the README,
SKILL.md, the tests and the review's N-items. It contains no unrelated
changes, weakens no tests and adds 6 tests. Acceptance items 1–4 are met, as
the evidence above shows.
