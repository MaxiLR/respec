# t002 fresh review 2

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t002`, HEAD `1d2f486`, clean
- Diff reviewed: `a8ec9de..1d2f486` (whole ticket: `134a0e6` plus fix `1d2f486`)
- Inputs: ticket 002, spec revision 2, claims `t002-impl-1.md` and `t002-impl-2.md`,
  prior review `t002-review-1.md`. No AGENTS.md, CONTEXT.md or decision records in
  the worktree.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking: 0

## Gates rerun

| Gate                             | Result             |
| -------------------------------- | ------------------ |
| `uv run pytest -q`               | 56 passed          |
| `uv run black --check .`         | 14 files unchanged |
| `npx prettier --check README.md` | clean              |
| Worktree clean, HEAD `1d2f486`   | yes                |

## Prior blocking finding B1: resolved

I reproduced each scenario with the real CLI (`uv run respec`), using scratch
`RESPEC_HOME` and `RESPEC_USER_HOME` and profiles written to disk. After every step I
compared `state.json` with the target folders.

| Scenario                                                                                                                                                                                     | Result                                                                                                                                                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1. `~/.claude/skills` is a symlink to `~/.agents/skills` and already holds `existing`. `a` = [claude-code, agents] with `tdd` and `grill`. `b` = [oh-my-pi]. Run `use a`, `use b`, `use a`. | `use a` exits 0 and installs each skill once, recorded under the claude-code path. `use b` removes both. Both folders keep only `existing`, and `state.json` lists only the oh-my-pi item. Running `use a` again works, with no "not managed" refusal. Disk and state matched at every step.        |
| S1b. Same alias, with order `a` = [agents, claude-code], then `c` = [claude-code], then `b`.                                                                                                 | An item recorded through one alias is recognised through the other (`_real` compare). Each switch removes the previous items cleanly, and the final folders are empty apart from oh-my-pi.                                                                                                          |
| S2. The agents folder is read-only, so the install fails partway.                                                                                                                            | The CLI prints `error: ... did not complete ... No profile is active ...` and exits 1, with no traceback. `state.json` has `active_profile: null` and records exactly the two claude-code links on disk. After restoring permissions, `use b` removes both and leaves claude-code and agents empty. |
| S3. An unmanaged `~/.claude/skills/tdd` already exists.                                                                                                                                      | Preflight refuses. No `state.json` and no backups are written, and the user file is unchanged.                                                                                                                                                                                                      |
| S4. Removal fails partway (agents folder read-only while switching `a` to `b`).                                                                                                              | The claude-code item is removed and dropped from state. The agents item stays recorded and on disk, so state matches disk. After permissions are restored, the next `use b` removes it and finishes.                                                                                                |
| S5. Removal succeeds and the install fails in oh-my-pi.                                                                                                                                      | `state.json` has `installed: []` and the disk is empty, so they match. `status` reports no active profile. A retry succeeds.                                                                                                                                                                        |

A later `use` removed everything the previous profile installed in every case. The
fix commit adds regression tests for the alias case, the partial install with a
follow-up switch, and the failed backup. All three pass.

## Implementer residuals

### R1. `status` lists a shared-real-folder item under the first target only (non-blocking)

- Location: `src/respec/switch.py` `status()`, which filters items by
  `item.target == target`. `_preflight` skips aliased folders.
- Scenario: in S1, `respec status` shows `agents ... (no managed items)` while
  `~/.agents/skills` really holds `tdd` and `grill` through the alias.
- Impact: cosmetic and possibly misleading. Each item is recorded once and removed
  correctly, so isolation and removal are unaffected. The ticket asks for "linked
  items per folder". The real folder's items are shown, once, under the target that
  installed them. I do not consider this blocking. Suggested follow-up: mark aliased
  targets in `status`, for example `agents -> same folder as claude-code`. Ticket 004
  is a natural place, since its unknown-entry listing needs per-real-folder awareness
  anyway.

### R2. A failing `save_state` inside the error handler surfaces raw (non-blocking, deferred to 003)

- Location: `src/respec/switch.py` `use()`, in the `except OSError` handler, and the
  per-step `save_state` calls.
- Scenario: the disk fills up or `RESPEC_HOME` becomes unwritable after a symlink
  was created but before its record was saved. The created path goes unrecorded, and
  the second `save_state` in the handler raises a raw `OSError` traceback.
- Impact: this is the same class of failure as a crash or kill between creating a
  path and recording it. Ticket 002 excludes interruption recovery, and the spec
  assigns that journal to 003. The window is now one filesystem operation, not the
  whole install loop. I do not consider it blocking. Ticket 003 should record intent
  before creating each path, wrap the handler's save, and print a non-traceback
  error.

## Non-blocking observations

- N-a. The error text "Items installed so far are recorded ..." is also shown for
  removal-phase failures (S4). It is accurate in effect but worded for the install
  phase. Consider "Items respec created are recorded ...".
- N-b. The previous review's N1 is still open: copy-mode removal `rmtree`s without a
  content check. The implementer deferred it to 004/005. This is acceptable, since
  only recorded paths are touched.
- N-c. In an aliased setup, takeover backs up both alias paths. The content is
  duplicated, which is harmless.
- N-d. A `RespecError` from the profile-folder guard in `_remove` is not caught by
  the `except OSError` handler. State was already saved after each earlier removal,
  so disk and state still match. Only the "no profile active" message is skipped.

## Acceptance evidence check

| Criterion                                                                                     | Evidence                                                                                                                                       |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Symlink each enabled skill into every target, copy fallback, record every created path        | Tests `test_use_symlinks...` and `test_copy_fallback_when_symlinking_fails`, plus S1 and S2. `FileExistsError` no longer falls back to a copy. |
| First takeover backs up full contents. Installing alone changes nothing.                      | Tests for backup, one-time backup, same-second collision and failed backup with no partial folder. S3 shows a refusal writes nothing.          |
| A switch removes every previous path from every folder and installs only into the new targets | `test_switch_scenario_a_to_b...`, S1, S2, S4 and S5                                                                                            |
| Scenario A(claude-code, agents) to B(oh-my-pi)                                                | Test plus S1 (aliased) and S2 (after a failure)                                                                                                |
| Disabled skills are never linked                                                              | `test_disabled_skills_are_never_linked`                                                                                                        |
| Removal touches only recorded paths. Profile folders are kept.                                | Test plus code review: `_remove` unlinks symlinks without following them and refuses copies inside the profiles root                           |
| `status` and `--json`                                                                         | Tests plus S1. See R1.                                                                                                                         |

The tests assert filesystem state, backups and `state.json` against independent
expectations. None asserts on source text or mirrors the implementation. Scope stays
within 002: unknown-entry handling, the journal and restore are not implemented.
