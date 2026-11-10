# fix-9 review 1

- **Reviewer:** fresh independent reviewer, read-only; did not implement this
  work.
- **Diff:** `374b7f28815e7a7c919e65d0ddac7d18276dbb87..55362bcbebee12295be70be77968e99808f4e230`
  (worktree `respec-worktrees/fix-9`, branch `codex/respec-v1-fix-9`).
- **Spec compliance:** FAIL (one blocking README/JSON-contract inaccuracy, B1).
- **Code quality:** PASS.
- **Tests rerun:** PASS.

## Gates rerun (fresh, in the worktree)

- `uv sync --frozen`: ok. `uv lock --check`: "Resolved 28 packages".
- `uv run pytest -q`: **553 passed** in 195 s.
- `uv run black --check src tests`: 43 files unchanged.
- `npx prettier@3 --check README.md`: clean.
- `ruff --select F401,F811,F841 src/respec` (ad hoc, unused/duplicate names):
  clean.
- Red on base: I ran the 13 new tests against the base `src` (via
  `PYTHONPATH`, which child processes inherit). 11 failed and 2 passed. The 2
  that passed are the read-only guard and the SIGKILL lock-release test,
  which the implementation report says are green on base. This matches the
  implementer's claims.

## Real-CLI investigation (temp homes only, under the scratchpad)

### (a) The final review's race

I used a harness of 40 skills × 3 targets, with the shipped skills included.
Each round ran 4 concurrent processes: `use B`, `use A`, `enable B<n> -p B` and
`disable A<n> -p A`. After each round I ran `status --json`, compared the link
listings of all 3 targets, and checked that the active profile's link count
equals the number of skills it has enabled, with no foreign links.

| Code        | Rounds | Runs ok | Busy | Tracebacks | False interrupted | Inconsistent |
| ----------- | ------ | ------- | ---- | ---------- | ----------------- | ------------ |
| fix-9       | 16     | 63/64   | 1    | 0          | 0                 | 0            |
| fix-9       | 20     | 80/80   | 0    | 0          | 0                 | 0            |
| base (ctrl) | 8      | 14/32   | 0    | 16         | 23                | 8            |

The base control shows that the harness detects the original bug. With the
fix, the 1 s wait serialises nearly all runs, and the one refused run printed
the clear message.

### (b) Audit of the mutating paths

- **CLI:** every mutating command calls `_hold_lock` at its start:
  - `use`, `add`, `remove`, `enable`, `disable`, `update` (not `--check`);
  - `layer add`, `rm`, `use`, `add-skill`, `remove-skill`, `enable`,
    `disable`, `on`, `off` and `repair`;
  - `adopt`, `restore` (not `--list`), `recover`, `profile new` and
    `profile install`.

  The read-only commands take nothing: `status`, `profile list` and `show`,
  `layer list` and `show`, `update --check` and `restore --list`.

- **Safety net:** `journal.begin` (outermost), `ready`, `recover` and
  `rebuild_state` lock themselves.
- **TUI:** every core mutation is wrapped. That covers:
  - create profile, the skill toggle, the layer radio, add folder;
  - git add (inside the worker, via `_changing`);
  - Sync adopt, repair, relink and disable-gone;
  - activate (`switch.use`, including the unknown-entry handler that runs
    inside it), the takeover resolve with `link_added`, and adopt.
  - Sync's `journal.recover` locks itself.
- **Re-entrancy:** the lock is reentrant per process, so `ready` →
  `recover` inside `use` and the TUI's `lock.exclusive` → `begin` cannot
  deadlock. This was exercised by auto-recovery in the kill tests below, by
  CLI `recover`, and by the TUI tests.
- **Internal guard:** `_guard` (a non-reentrant `threading.Lock`) is never
  re-taken while it is held.

### (c) TUI git add holding the lock for the whole fetch

This is acceptable.

- A CLI command that changes things during the fetch fails after 1 s with
  "another respec is running"; it never hangs. Read-only commands are
  unaffected.
- The fetch is bounded by `RESPEC_GIT_TIMEOUT`: 120 s per git command by
  default, plus the low-speed abort, and Esc/Cancel stops it. A hung fetch
  can therefore refuse CLI changes for at most a few multiples of the
  timeout. It never blocks them indefinitely, and nothing is lost.
- The same applies to CLI `add`/`update` from git.
- The add's journal is begun before the fetch, so the lock must cover the
  fetch for the "live journal is not interrupted" rule to hold.
- Within the TUI, the git worker and the UI thread share the per-process lock
  (see N3), but the UI already disables editing and Sync (`check_action`)
  while git runs.

### (d) SIGKILL while holding the lock

Each case ran in a fresh home: kill -9 at a checkpoint, then `status`, then
`recover`, then `use A`.

| Kill point                   | `status` | `recover`   | Next `use` | Targets equal |
| ---------------------------- | -------- | ----------- | ---------- | ------------- |
| `disable` at `links:begin`   | pending  | rolled-back | ok         | yes           |
| `enable` at `links:begin`    | pending  | rolled-back | ok         | yes           |
| `use` at `use:begin`         | pending  | rolled-back | ok         | yes           |
| `use` at `removed`           | pending  | finished    | ok         | yes           |
| `use` at `installed`         | pending  | finished    | ok         | yes           |
| `restore` at `restore:begin` | pending  | finished    | ok         | yes           |
| `restore` at `removed`       | pending  | finished    | ok         | yes           |

- In 3 further cases (`use` at `use:begin`, `installed` and `removed`), the
  next `use A` auto-recovered directly in 0.2–0.3 s. There was no stale lock.
- **Stale temp file:** I planted `.state.json.99999.deadbeef.tmp`. It is
  harmless: it was ignored, and recover and `use` worked. It is never
  cleaned up, though (N4).

### (e) Read-only commands during a long mutation

- I paused a `use B` inside its change and kept it alive. During the pause:
  - `status` and `status --json` returned in about 0.1 s with no
    interrupted warning;
  - `profile list`, `layer list`, `restore --list` and `update --check` all
    worked;
  - `enable --json`, `recover --json` and `use A` each failed after about
    1.1 s with rc 1 and the clear message, and changed nothing.
- When I released the holder, it finished. Status then showed B and no
  warnings.
- **Hammer test:** I ran 372 `status --json` calls during 300 back-to-back
  switches. None reported a false interruption and none crashed. N1
  describes the remaining narrow race.

### (f) Regressions

- The SIGKILL-matrix and JSON-contract tests are in the suite and pass.
- **`use` timing:** 40 skills × 3 targets with the shipped skills, 6 runs of
  the real CLI each. fix-9 took 0.40–0.41 s and base took 0.39–0.40 s, so
  there is no regression.
- **Busy JSON shapes:**
  - `use`: full use keys, with `active_profile` filled.
  - `restore`: full restore keys plus `resolved`, and `kept` with
    `--release-only`.
  - `adopt`: `resolved`, `linked`, `unresolved`.
  - `recover`: `active_profile`, `recovered: false`.
  - Every other command: `{error, warnings}`.
  - All of these exit 1.

### Other acceptance items

- **N3:** `update --json` reports `active` correctly. This is covered by the
  test, which was red on base.
- **N4 counts:**
  - `use` printed "Removed 1 skill (3 links)" and "installed 1 skill (3
    links)".
  - `restore` printed "Removed 3 skills (9 links) placed by respec".
  - The README `--json` claim is fixed.
- **Unreadable takeovers.json:** `status` (text and JSON) warns
  `unreadable-takeover-log`, and the file's md5 is unchanged afterwards.
- **`_delete` merge:** `trees.delete_entry` has a body identical to both
  removed helpers.

## Findings

### B1 (blocking, low): the README contradicts the new busy JSON output

- **Location:** `README.md`, the section "Running two at once" (around line
  240), and the JSON contract bullet on `error` (around lines 357–362).
- **Scenario:** while another respec holds the lock, I ran `respec add
/x --json`, `respec update -p A --json` and `respec profile install o/r
--json`. The same path applies to `remove`, `enable`, `disable`, the
  `layer` changes and `profile new`. Each printed
  `{"error": "another respec is running…", "warnings": []}` on stdout and
  exited 1.
  - Line 242 says a busy `--json` run "prints the command's usual keys,
    empty, plus `error`". That is false for all of these commands: an
    `enable --json` success has `profile`, `skill`, `action`, `enabled`,
    `path`, `active`, `linked`, `unlinked` and `unresolved`.
  - Lines 357–362 still say that every command other than `use`, `adopt`,
    `restore` and `recover` prints "their error on stderr only". That is now
    also false: these commands print JSON on stdout, but for any other
    failure they still print nothing on stdout. For example, `enable nosuch
--json` gives stderr only.
- **Impact:** `--json` output and the README are the machine-readable
  contract (spec line 123), and the scope of this fix includes README
  accuracy. An agent that follows the README either expects keys that never
  come, or never parses stdout on failure. The fix is small: document that a
  busy refusal always prints `{error, warnings}` (plus the full keys for the
  4 named commands), or emit the usual keys.

### N1 (non-blocking, low): `journal.pending` checks the lock after reading the journal

- **Location:** `src/respec/journal.py`, `pending()`: `journal =
load_state(...).journal` and then `lock.busy(...)`.
- **Scenario:** the two calls are separate steps. If the change that wrote
  the journal finishes between the read and the probe, its finished change
  is reported as `interrupted-operation: pending`.
  - I reproduced it deterministically: a `status --json` with a 1.5 s delay
    injected before `busy()` ran while a held `use B` was released. Status
    printed `['interrupted-operation']`, and the next `status` was clean
    (B active).
  - Without the injected delay the window is microseconds: 0 hits in 372
    hammer runs.
- **Impact:** a rare, transient false "interrupted" message from `status`,
  the warnings or TUI Sync. It does no harm, because `recover` re-reads the
  journal under the exclusive lock.
- **Fix:** take `LOCK_SH` non-blocking first and hold it across the
  `load_state` read; if that fails, the change is running.

### N2 (non-blocking): a busy TUI action freezes the UI for up to 1 s

- **Location:** `src/respec/lock.py`, `acquire`.
- **Scenario:** the 1 s wait runs on the TUI's UI thread. While it polls,
  `acquire` also holds the process-wide `_guard`, so `holds()` and `busy()`
  calls from other threads block for up to 1 s.
- **Impact:** a brief UI freeze only. The implementer already disclosed it.

### N3 (non-blocking): the lock is reentrant per process, not per thread

- **Location:** `src/respec/lock.py` (`_held` is keyed by home only).
- **Scenario:** while the git worker holds the lock, a mutation started on
  the TUI's UI thread would get a reentrant pass instead of being refused.
  Sync's `pending()` would also see `holds()` as true and could offer to
  recover the live add.
- **Impact:** none today, because `_set_busy` and `check_action` block
  editing and Sync while git runs. It is a latent hazard if a future TUI
  action skips those guards. Thread-owner tracking, or refusing a
  cross-thread re-entry, would make it robust.

### N4 (non-blocking): stale `.state.json.<pid>.<uuid>.tmp` files are never cleaned up

- **Location:** `src/respec/state.py`, `save_state`.
- **Scenario:** a SIGKILL between the temp write and the rename leaves a
  uniquely named temp file. Nothing ever removes it.
- **Impact:** harmless and rare, but such files accumulate.
- **Fix:** sweep `.state.json.*.tmp` under the lock, for example in `begin`.
- Unlike `.state.json`, the other atomic writers still use fixed temp names
  (`profiles.py:626`, `takeovers.py:163`, `switch.py:315`). That is fine now
  that every writer holds the lock.

### N5 (non-blocking): leftover pluralisation and a duplicated helper

- **Location:** `cli.py:1690`, `profile install`, prints `({n} skills)`,
  which gives "(1 skills)".
- **Location:** `tui.py:253`. Its `_plural` duplicates the new
  `messages.plural`.
- **Location:** `journal.py`. Black wrapped several `trees.delete_entry(...)
  # comment`calls awkwardly, leaving trailing comments after`)`.
- **Not addressed:** N4's third bullet (the shared-folder backup/restore
  wording) was left out of scope, as the implementer stated.

### N6 (non-blocking, note): the CLI holds the lock while waiting at a prompt

- **Scenario:** the interactive CLI prompts hold the lock while a person
  answers: `use`'s unknown-entry questions, `update`'s overwrite
  confirmation, `layer repair`'s keep choice and `adopt`'s per-entry
  questions. Other changes fail after 1 s until the person answers.
- **Impact:** this is expected for a single-writer lock and is acceptable.
  It could be mentioned in "Running two at once".

## Scope

The changes stay within fix-9. There are no unrelated edits, tests were not
weakened, and no assertions were dropped. 14 tests were added.
