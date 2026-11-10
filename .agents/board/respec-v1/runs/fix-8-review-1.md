# fix-8 review 1: final polish (c9f6081..8a86af6)

- Reviewer: a fresh, independent reviewer (fresh-code-review). I did not
  implement this work.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-8`, head
  `8a86af6ab7d59bffc107656ca589434fd31f6c48`, clean.
- Diff: 1 commit, 11 files, +692/-109.
- AGENTS.md: there is none in the repository. I followed the global CLAUDE.md.
- I worked read-only, apart from this report and scratch at
  `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/fix8r/`.
  The scratch holds `gates.log`, `smoke.sh` and `smoke-head.log`,
  `matrix.py` and `matrix-head.log`, `tui/pilot.py` and `pilot.log`, plus
  `base/` and `head/` (`git archive` exports with their own venvs).
- I used only temp homes (`HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` under
  scratch) and stdin `/dev/null`.
- No guard denials.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking: 0

## Gates (rerun independently in the worktree)

| Gate                                                                        | Result                    |
| --------------------------------------------------------------------------- | ------------------------- |
| `UV_OFFLINE=1 uv sync --frozen`                                             | PASS (Audited 27)         |
| `UV_OFFLINE=1 uv lock --check`                                              | PASS (Resolved 28)        |
| `uv run --frozen pytest -q -rs`                                             | PASS, 539 passed, 187.18s |
| `uv run --frozen black --check .`                                           | PASS, 41 unchanged        |
| `npx --no-install prettier --check README.md src/respec/shipped/*/SKILL.md` | PASS                      |
| `uvx --offline ruff check src tests --select F`                             | PASS                      |

## Red on the base: every new test fails on c9f6081

I copied head's `tests/test_journal.py` and `tests/test_shipped_skill_docs.py`
next to the c9f6081 sources, which have their own venv, and ran them. The 16
new tests fail there and the 47 older ones pass.

The two tests that were written after their fix fail on the base for a real
reason:

- **`test_release_only_refuses_options_of_a_full_restore`:**
  `restore --release-only --overwrite` exits 0 on c9f6081 and releases.
- **`test_rerunning_an_interrupted_release_reports_what_it_kept`:** on
  c9f6081, rerunning `restore --release-only` after an interrupted release
  exits 1 with "respec owns no folders; nothing to release". That run's
  auto-recovery had already released everything. fix-8 fixes this
  incidentally, through the new `_release_only` journal check.

## Behaviour fixes, exercised with the real CLI or Pilot in temp homes

1. **The TUI banner clears after Sync recovery.**
   - Setup: a real SIGKILL of the CLI `use pi` (`tui/pilot.py`), then a
     fresh `RespecApp`.
   - Round A (killed at `installed` #1, then Roll back): after Sync closed,
     `#feedback` was `''`. It was still `''` after `r` (refresh).
   - Round B (killed at `removed` #2, then Finish): the same.
   - `consistent.py` found 0 problems in both rounds.
2. **`status` during an interrupted switch.**
   - Setup: a real SIGKILL at the 2nd `installed` of `use work` (rc 137).
   - Text `status`:
     - it shows the pending message plus "`…/d2` is the entry it was changing
       when it stopped; recovering the change settles it";
     - `d2` is not listed as `unknown symlink`;
     - only the user's `pre1` is unknown.
   - `status --json`: `unresolved` holds `pre1` only, and the warning has
     `in_flight: [".../d2"]`.
   - After `recover`, the warning reports `finished` and `unresolved` holds
     `pre1` only.
3. **A rerun of an interrupted restore reports its actions.**
   - Killed at `removed` #1; then `restore --json`:
     - `released` lists all three folders;
     - `removed` has 7 paths;
     - `restored` names the claude-code run;
     - the warning reports `finished`.
   - Text mode prints "Removed 7 respec skills / Restored claude-code from … /
     respec released its folders".
4. **`restore --list` combined with other options.**
   - `--list --release-only` (with and without `--json`) exits 1 with
     "'--list' only lists backups and cannot be combined with
     '--release-only'; nothing was changed."
   - `--release-only --overwrite` exits 1.
   - `state.json` is byte-identical afterwards, and `restore --list` still
     works.
5. **A corrupt log is reported and preserved.**
   - Case 1: after `use` + `restore`, I damaged the log, then ran `use pi
--json`.
     - The output has the warning `unreadable-takeover-log`, whose `path` is
       `backups/<ts>-2/takeovers.json` with the original bytes.
     - A new log holds the three new records.
     - The aside run is not listed by `restore --list`.
     - `restore <that-run>` is refused ("no backup").
   - Case 2: `restore --json` with a damaged log.
     - The warning appears and the damaged bytes are kept in a backup run.
     - No new log is written, because there are no records.
   - A read-only `restore --list` reports it as "left as it is" and changes
     nothing.
6. **A newer `takeovers.json` (version 2).**
   - These commands refuse and change nothing:
     - `restore` (exit 1, stderr);
     - `restore --release-only --json` (exit 1, JSON with `error`);
     - the first `use` (exit 1; the folders are untouched and there is no
       backup).
   - The log's sha1 is the same before and after.
   - `use work` with no new target succeeds without touching the log, which
     is correct.
7. **Missing path with release-only.** I deleted the `p1` link. `restore
--release-only --json` returns `kept: []`, and `p1` is in neither `kept`
   nor `removed`. See finding N1.
8. **Release-only recovery includes kept items.**
   - Setup: `p1` replaced by a user folder, then a SIGKILL at `removed` #1
     of `restore --release-only`.
   - The journal holds `kept: [.../p1]`.
   - `recover --json`: the message names "kept …/p1: respec cannot verify it
     as its own".
   - A rerun of `restore --release-only --json` gives `kept: [.../p1]`, plus
     `released` and `removed`.
9. **Rolled-back first use.**
   - Setup: a SIGKILL at `takeover-logged` #1 of the first `use pi`. Before
     recovery, the log held 3 unreleased records.
   - `recover` and `recover --rollback` both report `rolled-back`.
   - Afterwards all three records are `released: true`, `restore --list`
     says "No backups.", and the user's `pre1` is intact.

**Wording.**

- A `bogus` journal now reads "A 'bogus' change was interrupted and did not
  complete." ("interrupted" appears once).
- The rebuild note names `takeovers.json` (test red on the base).

**Cleanup.**

- `state.active_or_none` replaces `_SwitchRun._active`, `_active_or_none`,
  `RespecApp._active_now` and the inline copy in `_render_profile`. The
  semantics are identical.
- `describe` has deduplicated tables. Its only behaviour change is the
  intended fallback text: an unknown operation with a profile used to read
  "an operation 'x'" and now reads "a 'x' change".
- `OPERATIONS` is gone; grep finds no use.

## SIGKILL matrix and timing

The harness is `matrix.py` with `killer.py`, which sends a real SIGKILL at a
journal checkpoint.

- **Deterministic kills: 57.** These cover:
  - the checkpoints `backed-up`, `takeover-logged`, `installed`, `removed`
    and `phase:apply`, at hits 1, 2, 3 and 5;
  - the scenarios first use, switch and restore;
  - recovery through `recover`, `recover --rollback`, or the next `use`.
- **Async kills: 24**, at random times from 0.04 to 0.2 s.
- **Checks after each kill:**
  - `status --json` exits 0, and `unresolved` holds only the user's `pre1`;
  - recovery succeeds;
  - `consistent.py` finds 0 problems;
  - the targets with unreleased log records equal `state.owned`;
  - a bare `restore` leaves the user tree byte-identical to the
    pre-respec snapshot.
- **Result:** 76 of 81 checks were clean. The 5 others were all
  `restore`/`recover --rollback`, which refuses with "a restore cannot be
  rolled back once it has removed skills; run 'respec recover' to finish
  it". That refusal is documented and identical on c9f6081, so it is a
  harness artifact, not a regression. A later `recover` finishes the
  restore.
- **No data loss.** No in-flight entry appeared as unresolved, and no log
  record outlived its ownership.
- **`use` timing** (12 switches, 3 skills, 2 targets):

  | Build   | Median | Range        |
  | ------- | ------ | ------------ |
  | c9f6081 | 0.138s | 0.135–0.145s |
  | fix-8   | 0.140s | 0.133–0.143s |

  There is no regression.

## New surface: contract and docs

- **`unreadable-takeover-log`** has `type`, `path` and `message`.
  - It is documented in README (warning list and recovery section), in the
    shipped `SKILL.md` and in the `_print_json` docstring.
  - It is printed on stderr too, the same pattern as
    `unreadable-manifest`.
  - Tests: the two corrupt-log tests.
- **`in_flight`** appears only on a `pending` warning, and only when the
  entry exists. A missing field rather than an empty list follows the "left
  out when it does not apply" rule.
  - It is documented in README, `SKILL.md` and the docstring.
  - Test: `test_status_shows_the_half_made_link_…`.
- **`takeover-logged` checkpoint:**
  - It is exercised by `test_a_rolled_back_first_use_leaves_no_takeover_on_record`,
    which uses a real kill, and by the step-boundary matrices of `use`.
  - It is an internal checkpoint, so it needs no user documentation.
- **README `error` bullet:** it now matches the behaviour. `recover --json`
  and `restore --release-only --json` print JSON with `error`. Refused option
  combinations print on stderr only, also with `--json` (verified).

## Findings (none blocking)

### N1: release-only drops a missing path without naming it

- **Location:** `src/respec/restore.py` `release_only`, the `else` branch
  with `os.path.lexists`.
- **Scenario:**
  1. `use pi`.
  2. `rm ~/.claude/skills/p1`.
  3. `restore --release-only --json`.
- **Result:** `p1` appears nowhere in the output (`kept: []`, not in
  `removed`), and the text says nothing about it.
- **Assessment:** the criterion is "reports missing paths accurately (not
  'Kept')". The output is now accurate: nothing is called kept. N30 offered
  "drop silently, or report as already gone", and this takes the first
  option. README documents it ("a record whose path is gone is only
  dropped"), and it matches a normal restore. I judge the criterion met.
- **Impact:** a script or user cannot learn that a recorded skill was
  already gone. No data is involved. If the engineer wants it explicit, an
  `already_gone` list would be a small addition.

### N2: the TUI never shows takeover-log problems

- **Location:** `src/respec/tui.py`. Nothing calls
  `takeovers.take_problems` or `peek_problems`. The module-level
  `takeovers._problems` list is drained only by the CLI.
- **Scenario:** a corrupt `takeovers.json`, then a TUI action that takes a
  new folder over or releases one.
- **Result:** the log is moved into a backup run (preserved), but the TUI
  says nothing. In a long TUI session, the problems also pile up in the
  module list.
- **Impact:** low. The bytes are kept, and the next CLI read reports a
  still-damaged log. The CLI reports it fully. This follows the existing
  precedent: the TUI does not show `unreadable-manifest` either.

### N3: a restore rerun leaves out the removal the killed run finished

- **Location:** `cli._finish_restore` and `journal._recover_restore`.
- **Scenario:** a kill at `removed` #1 of `restore`, then `restore --json`.
- **Result:** `removed` lists 7 paths. The 8th, `p1`, was removed by the
  killed run and is not listed.
- **Impact:** a minor undercount. The implementer disclosed it, and every
  other key is correct. It meets "reports its actions" for this run.

### N4: `{"version": true}` is read as version 1

- **Location:** `src/respec/takeovers.py` `_read`. Because
  `True == 1 == VERSION`, the check passes.
- **Scenario:** a hand-edited log with `"version": true`.
- **Impact:** negligible. It is listed for completeness only.

## Scope

- Every change maps to int-c9f6081 items 1–6 or review 7's N29–N35.
- Nothing unrelated was refactored.
- No existing test was weakened: the diff only adds tests.
- `restore` and `use` behave the same apart from the stated fixes.
