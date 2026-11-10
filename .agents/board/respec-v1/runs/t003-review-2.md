# t003 review 2: interruption-safe switching journal (fix round 1)

- Reviewer: fresh, independent (did not implement)
- Range: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..c7f460cfd27e6353e1cc062556dc14e4a93179b3` (`a763a63` plus fix `c7f460c`)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t003` (clean, HEAD `c7f460c`)
- Inputs:
  - ticket 003 and the orchestrator's extra requirements;
  - the 003 map in `runs/int-3e563b6.md`;
  - `spec.md` as amended by `orchestration.md`;
  - review 1 (`runs/t003-review-1.md`);
  - the implementer's claims in `runs/t003-impl-1.md` and `runs/t003-impl-2.md`, treated as unverified.

## Verdicts

- spec-compliance: **FAIL**
- code-quality: **FAIL**
- tests-rerun: **PASS**
- blocking: **1** (B4)

## Gates rerun (fresh, at head)

| Gate                                                  | Result                    |
| ----------------------------------------------------- | ------------------------- |
| `uv sync --frozen`, then `uv run pytest -q`           | 499 passed in 138.4s      |
| `uv run pytest -q tests/test_json_contract.py`        | 13 passed                 |
| `tests/test_shipped_skill_docs.py` (doc tests)        | green within the full run |
| `uv run black --check src tests`                      | 40 files unchanged        |
| `npx prettier --check README.md "src/respec/**/*.md"` | clean                     |

## Real-kill harness

- Location: `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/kill2/`. It is a copy of review 1's `kill/`, extended with `s10.py` to `s14.py`.
- What `driver.py` does: it runs the real CLI in a child process with a temp `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`, and real defaults. The child SIGKILLs itself:
  - at the Nth named checkpoint;
  - at the Nth `shutil.copyfile`;
  - at the Nth `os.unlink`;
  - right after a function returns;
  - at the Nth `os.unlink` after a named checkpoint (`armunlink`, new in this review).
- `sigint:` raises `KeyboardInterrupt`, the way Ctrl-C does.
- Results are in `kill2/out/`.

Harness correction: review 1's `s4.py` searched for `'USER-EDIT\\n'` inside an f-string, which is a literal backslash followed by `n`. Because of that, its `*_found=[]` results for P1 and P2 were not valid evidence. I fixed the search. B1 and B2 were still real: the implementer's red-first tests show both.

## (a) B1, B2, B3: fixed

| Finding | Reproduction (`s4.py`)                                                                                                    | Result at head                                                                                                                                                                                 |
| ------- | ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1      | Unlisted `profiles/w/skills/up` (`USER-UNLISTED`), then `add o/r#skills/up` killed at `copy:3` and at Ctrl-C `phase:copy` | Folder kept with its content. Recovery says `rolled-back`, "none of its skills were added": true. The uninterrupted baseline refuses the same way.                                             |
| B2      | `up` holds `USER-EDIT`, a stale `.up.old` exists, `update` killed at `update:begin`                                       | `up/SKILL.md` is still `USER-EDIT` and `.up.old` is kept. Recovery says `rolled-back`, which is true: nothing had changed yet. The message notes the `.old` it left in place.                  |
| B3      | `update` SIGKILLed right after `profiles.save_profile` returned                                                           | Recovery says `finished` ("profile.yaml already recorded the new commits"). The files are at v2, `profile.yaml` is at v2, and the next `update` reports `up-to-date`. Consistent and truthful. |

## (b) Review-1 SIGKILL matrix: no regression

- **First `use`, copy mode** (copy 1, 5, 21, 25, 40, 60): pending, then `rolled-back` (copy 1 to 21) or `finished` with one item set aside. The user's 20-file folder is whole, and state matches disk.
- **`use b`, links** (8 points): pending, then `finished`, or `rolled-back` at `use:begin`. Consistent.
- **`use b`, copy mode** (unlink 3 and 15, copy 4 and 15): `finished` with the partial copy set aside, then `use a` applied. Consistent.
- **`restore`** (links and copy mode; `put-back:start`, copy 3, copy 12): `finished`, with partials set aside, the user folder put back whole and the state empty.
- **`adopt --add` and `--remove`** (12 points): `rolled-back` while the copy was cut short, `finished` after it. Nothing was lost.
- **adopt overwrite** (copy 2/8/14/20, `copied`, unlink 2/5, `deleted`):
  - the staging folders the copy left are set aside under `set_aside` (N1 fixed);
  - the outcome matches the state;
  - the edited content and the original are each still in one place.
- **`layer repair`**: at `links:begin` the outcome is `rolled-back` and `profile.yaml` is unchanged (N2 fixed). At later points it is `finished` and the hand-made `c` is untouched.
  - Separately, `check()` flags `c` as "record not managed". The base `3e563b6` does the same without any kill (`s14.py` run against `git archive 3e563b6`), so this behavior predates the change and is not a regression.
- **`update`**:
  - `rolled-back` (v1, 16 files) at begin, at copy 5, at `swapped-out`, at `swapped-in` and at unlink 5;
  - `finished` (v2) at `phase:refresh` and at `installed`;
  - every case is consistent.
- **`add` from git**: `rolled-back` in `copy`, `finished` in `refresh`. Consistent.
- **`profile install`**: `rolled-back`, and the half-copied folder is removed.
- **Other checks**:
  - `disable` killed after `save_profile` is now journaled as `links` and reported (N3 fixed for `commit`).
  - The shipped-skill refresh cut short heals (N4 fixed).
  - A refused `use --json` reports `active_profile: "a"`.

## (c) The `.old` refusal in `update`

- **Clear and changes nothing.** With a foreign `.up.old` (`s10.py` C1), `update` exits 1. The JSON row has `result: "error"` and a message naming the path ("move it out of the way first. 'up' was not updated."). The text output is the same. A snapshot of every profile file and `state.json` is byte-identical before and after.
- **Not consistent with fix-6.** fix-6's `adopt._clean_leftovers` deletes a leftover when its content is verifiably held elsewhere: it equals the live folder, or a backup run holds it. It moves a previous copy back when the live folder is missing. Only content it cannot verify is kept and reported. `update` refuses even when `.up.old` is byte-identical to `up` (C2), although that leftover is verifiably redundant.
- **Recommendation.** Keep the refusal for content that cannot be verified, which is the right data-safety default. Apply the fix-6 rule first:
  - delete a `.old` identical to the live folder;
  - move a `.old` back when the live folder is missing;
  - most importantly, settle the `.old` of this run's own journaled swap in a committed recovery (B4).

## Blocking finding

### B4: a kill during `update`'s final `.old` cleanup leaves a partial `.old`, and recovery wrongly calls it "not from this update"; later updates of that skill are then refused

- **Location:**
  - `src/respec/sources.py` `_update`, the `finally: shutil.rmtree(old, ignore_errors=True)` after `items.refresh_active` (about lines 735-740);
  - `src/respec/journal.py` `_recover_update`: `ours = ... _digest_or_none(old) == before` (line 864), then `_old_leftovers` (lines 829-836, 876).
- **Scenario** (`s11.py`, `s12.py`): `update` from v1 to v2 is SIGKILLed during the rmtree of `.up.old`, at unlinks 3, 8 or 14 after the `installed` checkpoint, with the journal in phase `refresh`. The next `recover` reports `finished`, which is correct, but adds "left …/.up.old in place: **it is not from this update** and may hold the only copy of earlier content". That statement is false. The folder is this run's own `.old`, cut part way: 9 of 16 files remain (v1). The digest check fails only because the deletion had started. Upstream then moves to v3, and `respec update` refuses `up` ("…is left from an interrupted change…; move it out of the way first. 'up' was not updated."). `status` shows no warning for it.
- **Impact:**
  - Recovery reports a false provenance, which breaks "reports it truthfully".
  - Every later update of that skill is blocked until the user moves a folder by hand, although it is redundant: v1 was the committed old version, and `profile.yaml` already records v2.
  - The window is the last step of every successful update, and for large skills it is the slowest step. No data is lost.
- **Fix direction:**
  - In a committed recovery, a `.old` of a journaled swap is this run's whatever its digest. `_replace` refuses to start when a `.old` exists, and the journal blocks other writers in between, so recovery can delete it.
  - Or mark a pending `drop-old` step before the final rmtree.
  - Also apply the fix-6 redundancy rule from (c), so a `.old` identical to its live folder does not block `update`.
  - Add a SIGKILL test at an unlink after `installed`.

## (d) Journal durability and corrupt journals

- **Durability.** `state.save_state` and `profiles._write` now go through `write_durably`: write the temp file, `flush`, `fsync`, then `os.replace`, then `sync_folder` (an `fsync` of the folder). The order is correct.
  - Non-blocking N9: on macOS, `os.fsync` does not issue `F_FULLFSYNC`, so it does not guarantee the data reached the platter after a power loss. Consider `fcntl(F_FULLFSYNC)` where it is available.
  - The fixed temp name `.state.json.tmp` is fine under the lock.
- **Corrupt journals** (`s5.py` R3):
  - Non-mapping journal: `invalid state file … journal must be a mapping with an operation` on every command (clear).
  - Unknown `operation`: `recover` explains that `--rollback` discards it. `recover --rollback` drops it, and `use a` then works (N8 fixed).
  - A `use` journal with a partial `pending` recovers cleanly.
  - An `update` journal without `profile`: every command, `recover --rollback` included, fails with "could not recover the update of profile None: its journal in state.json is malformed (KeyError('profile')) … remove the journal entry from state.json by hand". The message is clear, with no traceback. Non-blocking N10: the only way out is hand-editing. `recover --rollback` could offer the same discard as for an unknown operation, with confirmation.
  - A truncated `state.json` is reported as invalid. Every command stops; that is unchanged and now less likely because of the fsync.

## (e) The `respec remove` orphan folder

`s13.py`, with `lint/SKILL.md` set to `LINT-CONTENT`:

- Killed at `step:done`, `removed` or `use:begin` of the refresh: the journal (`use`) is reported, then `finished`/`rolled-back`. The `lint` folder stays in the profile, unlisted, with its content intact. Re-adding it refuses with "already exists but is not listed in profile.yaml; move it out of the way first". Nothing is lost.
- The README "Known limit" paragraph describes this case.
- Non-blocking N11: `items.remove` (and local `items.add`) save `profile.yaml` before any journal exists. They do not use `items.commit`/`journaled`, which the N3 fix covered.
  - A SIGKILL right after `save_profile` in `remove` leaves no journal and no `status` warning. `lint` is out of `profile.yaml` but still linked into `~/.claude/skills`.
  - A kill during a local `add`'s copytree leaves a partial, unlisted copy (the source is intact).
  - Nothing is lost, and the next `use` puts the links in line. However, the README says "Every change of several steps is recorded in a journal … (also an edit of the active profile)". The Known-limit paragraph only covers the final rmtree window.
  - Fix: wrap `remove` and `add` in `items.journaled`, or document both windows.

## (f) JSON contract and docs

- `test_json_contract.py`: 13 passed. The doc tests pass in the full run.
- `interrupted-operation`:
  - fields `operation`, `outcome` (`finished`, `rolled-back` or `pending`), `message`, `set_aside` and `profile`;
  - documented in the README, in `_print_json` and in the shipped `SKILL.md`;
  - `recover --json` is documented.
- `use --json` refused: `active_profile` is the real active profile.

## Integration with fix-6 and fix-5, and the TUI and Sync

- Recovery still reuses `adopt._clean_leftovers`. For an overwrite cut short in `copy`, it now sets aside only that skill's `.respec-new` and `.respec-old`. This is safe because `_overwrite` refuses to start while either exists. Other leftovers are kept and reported. There is no second mechanism.
- fix-5's `_undo_adds` is unchanged.
- `tui.py` is unchanged since review 1, where its Pilot probe passed. `test_tui_sync_reports_and_resolves_an_interrupted_switch` passes.

## Other non-blocking findings

- **N12** (`sources._update` with `journal._recover_update`): wrong outcome after Ctrl-C at `phase:refresh` (`s10.py` C4).
  - What happens: the `KeyboardInterrupt` runs `_update`'s `except BaseException: _restore(...)`, so the files and `profile.yaml` go back to v1, but the journal stays at phase `refresh`. Recovery reports `finished` and "profile.yaml already recorded the new commits", while everything is at v1.
  - Impact: the state is consistent (`update --check` shows the update available), but the outcome is wrong. The window is narrow: between `set_phase` and the end of the `try`.
  - Fix: decide `committed` from the `profile.yaml` digest alone, or clear the phase in `_restore`.
- **Tests:** the new SIGKILL matrices cover the update step boundaries, but not the cleanup after `installed` (B4). The implementer notes that the N1, N3, N4, N6 and N8 tests were not written red-first.

## Scope

The changes stay within the ticket, the 003 map and the review-1 findings. No guard denials occurred. No code, tickets or git state were changed. Only this report and the scratch harness under the scratchpad were written.
