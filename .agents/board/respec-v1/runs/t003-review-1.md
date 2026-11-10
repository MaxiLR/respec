# t003 review 1: interruption-safe switching journal

- Reviewer: fresh, independent (did not implement)
- Range: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..a763a6365840e99c6d43d709584ed857738ddd08` (one commit)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t003` (clean, HEAD `a763a63`)
- Inputs: ticket 003, the orchestrator's extra requirements, the spec risk "Interrupted switch", the
  003 map in `runs/int-3e563b6.md`, `orchestration.md`, and the implementer's claims in `runs/t003-impl-1.md`

## Verdicts

- spec-compliance: **FAIL**
- code-quality: **FAIL**
- tests-rerun: **PASS**
- blocking: **3**

## Gates rerun (fresh, at head)

| Gate                                                        | Result                                              |
| ----------------------------------------------------------- | --------------------------------------------------- |
| `uv sync --frozen`, then `uv run pytest -q`                 | 485 passed in 123.7s                                |
| `uv run pytest tests/test_json_contract.py`                 | 13 passed                                           |
| `uv run black --check src tests`                            | 40 files unchanged                                  |
| `npx prettier --check README.md "src/respec/**/*.md"`       | clean                                               |
| Pilot probe: TUI toggle while a switch is pending (scratch) | refused, state.json and profile.yaml byte-identical |

## Real-kill evidence (a)

The harness is in `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/kill/`
(`driver.py` plus `s1.py` to `s9.py`). It runs the real CLI in a subprocess with temp `HOME`, `RESPEC_HOME`
and `RESPEC_USER_HOME`, using real defaults (shipped skills). The process sends itself SIGKILL at one of
these points:

- a named checkpoint;
- the Nth `shutil.copyfile`, which is mid-`copytree`;
- the Nth `os.unlink`, which is mid-`rmtree`;
- right after a named function returns.

`NO_SYMLINK=1` forces copy mode. After each kill the harness runs `status --json`, then a follow-up
command, and checks four things:

- no journal is left;
- every `installed` record exists and is managed;
- the user's 20-file folder is still complete somewhere;
- the folder contents.

| Area                                                        | Kill points                                                                                             | Result                                                                                        |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| First `use`, copy mode (takeover backup and install copies) | copy 1, 5, 21, 25, 40, 60; follow-up `use a`                                                            | pending reported; rolled back (in backup) or finished; user folder intact; state matches disk |
| `use b` after `use a`, links                                | `use:begin`, `phase:apply`, `remove:start`, `removed`, `install:start`, `installed`, `step:done`        | pending, then finished (or rolled back before apply); consistent                              |
| `use b`, copy mode                                          | mid-rmtree (unlink 3, 15), mid-copytree (copy 4, 15); follow-up `use a`                                 | finished, partial copies set aside in a backup run, then `use a` applied; consistent          |
| `restore` (links and copy mode)                             | `restore:begin`, `phase:apply`, `remove:start`, `put-back:start`, mid put-back copy                     | pending, then `restore` finishes; user folder put back whole; state empty                     |
| `adopt --add` / `--remove`                                  | copy stage (mid-copy), `copied`, delete stage, mid-delete, `deleted`, `step:done`                       | nothing lost; delete stage finished; copy stage leaves the original                           |
| `adopt --add` overwrite of an edited copy                   | mid staging copy, `copied`, mid retire-rmtree, `deleted`                                                | nothing lost; see N1 for the leftover that blocks the retry                                   |
| `layer repair` (`_repair_links`)                            | `links:begin`, `profile-saved`, `remove:start`, `removed`                                               | finished; hand-made entry untouched                                                           |
| `update` (git, file base URL)                               | begin, mid-fetch copy, `fetched`, `swapped-out`, `swapped-in`, `phase:refresh`, `installed`, mid-rmtree | rolled back (v1, 16 files) or finished (v2); consistent, except B3                            |
| `add` from git                                              | begin, `phase:copy`, mid-copy, `added`, `phase:refresh`, `install:start`                                | rolled back or finished; consistent, except B1                                                |
| `profile install`                                           | begin, mid-copy, `copied`                                                                               | rolled back (folder removed)                                                                  |
| `use --json` refused (g)                                    | unknown entry blocks `use b`                                                                            | `active_profile: "a"`; fixed                                                                  |

Overall, the journal and recovery work well for the main paths: `switch.use`, `restore._apply`,
`_repair_links`, adopt, first-takeover backups, and copy-mode partial installs and removals. The blocking
issues are in the rollback rules for `update` and `add`.

## Blocking findings

### B1: rolling back an interrupted `respec add` deletes a folder the user placed in the profile (data loss)

- Location: `src/respec/journal.py` `_recover_add` (`for skill in added: ... _delete(folder)`, about lines 767-770), together with `src/respec/sources.py` `_add`. `_add` journals `skills=[...]` through `set_phase("copy", ...)` before `items.add_local` checks that the destination is free.
- Scenario: `profiles/w/skills/up/` exists but is not listed in `profile.yaml`. The user may have hand-placed it, or it may be the orphan that `items.remove` can leave. The user runs `respec add o/r#skills/up`, and the run is killed during the fetch copy (SIGKILL at `copy:3`) or stopped with Ctrl-C (a `KeyboardInterrupt` at `phase:copy`). The next command reports "Rolled back the add ... none of its skills were added" and deletes `profiles/w/skills/up`. A search for its marker content finds nothing afterwards (`s4.py`, `[P1 ...] unlisted_found=[]`).
- Baseline without an interruption: `add` refuses with "already exists but is not listed in profile.yaml; move it out of the way first", and the folder is kept.
- Impact: user content is permanently deleted. This contradicts the module docstring ("Nothing is deleted on the way") and the README ("Nothing is lost on the way"). Ctrl-C makes it easy to reach.
- Fix direction: record in the journal only the names whose folder this run created (mark each one before `add_local` copies it, or record the names that did not exist at begin). Delete only those. Set anything else aside instead of deleting it.

### B2: rolling back an interrupted `update` trusts any `.<skill>.old` and replaces the live folder (loses local edits)

- Location: `src/respec/journal.py` `_recover_update`, copy phase (about lines 727-737). The journal's `skills` is every sourced skill (`list(_sourced(profile, item))`), not the skills this run swapped. For each one, if `.<skill>.old` exists, the code deletes `live` and moves `.old` into its place.
- Scenario: `profiles/w/skills/up` holds local edits (`USER-EDIT`), and a stale `.up.old` exists. It can be left by `_update`'s `shutil.rmtree(old, ignore_errors=True)` failing part way, or by a crash before this version. `respec update` is killed at `update:begin`. The next `recover` reports "rolled-back", `up/SKILL.md` is now `stale`, and the edit is gone everywhere (`s4.py`, `[P2 ...] edit_found=[]`).
- Impact: local edits are permanently lost. This run never touched `up`, and the edits could have survived; the rollback alone destroys them. The precondition is uncommon, but the fix is cheap.
- Fix direction: journal each swap (a pending `swap` step, or append the skill to a `swapped` list just before `os.replace(live, old)`). Roll back only those skills, and set aside any `.old` that this run did not create.

### B3: `update` killed between saving `profile.yaml` and moving to phase `refresh` rolls back the files but not `profile.yaml`

- Location: `src/respec/sources.py` `_update`: `profiles.save_profile(...)` and then `journal.set_phase(respec_home, "refresh")` (about lines 719-720). Also `_recover_update` in `journal.py`, which never restores `profile.yaml`.
- Scenario: SIGKILL right after `save_profile` returns (`after:profiles.save_profile:1`). Recovery reports "Rolled back the update ...: its skills are as they were before". The files are back at v1, but `profile.yaml` records the v2 commit and digest. A later `respec update` reports `up-to-date`, so the skill stays at v1 and nothing reports it (`s4.py`, `[P3 ...] live='# up v1' next_update=[('up','up-to-date')]`).
- Impact: the state is inconsistent and the recovery message is wrong, which breaks the requirement to reach a consistent state and report it. The deterministic crash matrix misses this because there is no checkpoint between the two writes. The matrix crashes with a `BaseException`, which also runs `_update`'s `except BaseException: _restore(...)` (see N7).
- Fix direction: move to phase `refresh` before `save_profile` and treat a `profile.yaml` that matches the journal as committed. Alternatively, journal the previous `profile.yaml` (or the previous sources) and restore it on rollback.

## The implementer's stated limits (b)

1. **adopt, links and late restore can only be rolled forward.** This is acceptable. The ticket allows "resume or rollback", and the README documents it ("A restore, adopt or link change is finished"; "a restore that already removed skills can only be finished"). The wording is a minor issue: see N2.
2. **Commands that only edit `profile.yaml` warn but do not recover.** This is acceptable: they do not touch skill folders, and the later recovery reads the current `profile.yaml`. A related gap is N3: commit and refresh are not atomic.
3. **The orphan folder left by `items.remove`.** It is confirmed (SIGKILL at `step:done` after the refresh leaves `skills/lint` on disk with `profile.yaml` no longer listing it). It is non-blocking by itself: the user asked to delete that content, and a re-add refuses with a clear message. It is not documented in the README. It also feeds B1: a later interrupted `add` of the same name deletes that folder.

## Journal crash safety (c)

- Writes reuse `save_state`: a temp file, then `os.replace`. That is atomic against a kill. There is no `fsync` of the file or the directory, so after a power loss `state.json` can be empty or truncated. Every command then fails with "invalid state file", and nothing recovers it. The gap existed before this change, but the journal now depends on these writes. Non-blocking: N5.
- A corrupt journal gives the following results (`s5.py` R3):
  - a non-mapping journal is rejected cleanly ("journal must be a mapping with an operation");
  - an unknown `operation` leaves every changing command refused, and `recover` fails too, with no way out except hand-editing (non-blocking);
  - a missing required field such as `profile` for `update` gives a raw `KeyError` traceback on `recover` and `use` (non-blocking: respec itself never writes such a journal);
  - a truncated `state.json` is reported as invalid.

## fix-6 and fix-5 interaction (d)

- Recovery reuses fix-6's `adopt._clean_leftovers`. No second leftover mechanism exists, and the function is idempotent, so the normal adopt path and recovery cannot conflict.
- No double recovery: `ready()` does nothing while a change or a recovery is running. `begin` inside a recovery replaces the journal instead of refusing.
- `_undo_adds` (fix-5) is unchanged. `_settle_adopt` deletes an original only at the `delete` stage, after the copy completed. The real-kill adopt runs found no case where the only copy was deleted.
- See N1 for a usability gap at this boundary.

## TUI and Sync (e)

- The main screen shows a notice. Sync shows only the interrupted change, with Finish and Roll back (tested by `test_tui_sync_reports_and_resolves_an_interrupted_switch`).
- Every core mutation path the TUI uses calls `journal.ready()` under the refuse policy:
  - `items.commit`, `add` and `remove`;
  - `layers.set_active` and `repair` through `commit` and `_repair_links`;
  - `sources.add`, `update` and `install_profile`;
  - `adopt.adopt` and `resolve`, `switch.use`, `link_skills` and `relink_lasting`.
- My Pilot probe, a skill toggle in the editor while a switch is pending, was refused with the interrupted message. `state.json` and `profile.yaml` stayed byte-identical. PASS.

## JSON and docs (f), and `use --json` (g)

- `test_json_contract.py` is green.
- The `interrupted-operation` type and its fields (`operation`, `outcome`, `set_aside`, `profile`) are documented in the README, in `_print_json`'s docstring and in the shipped `SKILL.md`. `recover --json` is documented too.
- A refused `use --json` now reports the real active profile. Verified by a real CLI run.
- The README claim "Nothing is lost on the way" is untrue until B1 and B2 are fixed.

## Non-blocking findings

- **N1** (adopt overwrite, `journal._settle_adopt`, copy stage plus `adopt._clean_leftovers`).
  - What happens: a kill during the staging copy of an overwrite (copy 14 or 20) leaves a partial `.tdd.respec-new`. Recovery keeps it with the message "may hold the only copy of earlier content". The next `adopt --add tdd` is then refused until the user moves it by hand (`s8.py`).
  - What the journal already knows: the step is at stage `copy` and the entry is still whole, so the staged folder is a partial duplicate. It could be set aside to a backup run and reported in `set_aside`.
  - A kill during the retire rmtree similarly leaves a partial `.tdd.respec-old` that is also kept.
- **N2** (outcome wording, `journal._recover_links`).
  - An adopt whose copy stage was cut short is reported as `finished`, although the add was not made and the entry is still unknown.
  - A `layer repair` killed at `links:begin` is reported as `finished`, although the repair was not applied and `profile.yaml` is unchanged.
  - `recover --rollback` on these also says `finished`. The state is consistent, but the message misleads.
- **N3** (orchestrator's "items/layers refreshes", `items.commit` and `layers` through `commit`).
  - What happens: `save_profile(after)` runs before the refresh opens its journal. A kill between the two (`disable lint` killed after `save_profile`, `s5.py` R1) leaves `lint` disabled in `profile.yaml` but still linked. No journal is left and no warning appears in `status`.
  - Detection: only Sync's link check finds it. Nothing is lost, and the next `use` fixes it.
  - Suggested fix: begin a `links` (or `use`) journal before `save_profile` in `commit`.
- **N4** (`prepare`-phase rollback of `use` and `global_skills.refresh_shipped`).
  - What happens: a kill inside `refresh_shipped` (unlink 1, with an outdated shipped copy) leaves `~/.respec/shipped/respec` empty plus a `.respec.new`. Recovery says "Rolled back ... nothing ... changed", and the active profile's `respec` link points to an empty folder. `status` reports nothing (`s9.py`).
  - Impact: this is respec's own content and heals on the next `use`. Still, the rollback could call `refresh_shipped`, or `relink_lasting`/`align_links`.
- **N5** (`state.save_state`): there is no `fsync` before or after `os.replace`. This is a power-loss durability gap that existed before. Consider an fsync of the temp file and the directory now that the journal relies on these writes.
- **N6** (`cli.restore`): when a restore is pending, `respec restore <other-backup>` silently finishes the pending restore (of its own backup) and ignores the argument. JSON then prints an empty restore payload.
- **N7** (tests).
  - The crash matrices raise a `BaseException`. That runs `finally` blocks and `except BaseException` handlers that a real kill skips, for example `sources._update`'s `_restore`. So the `update` matrix mostly exercises the in-process rollback, not the journal recovery.
  - Only one test kills a process for real (`os._exit` during `use`).
  - My SIGKILL runs show recovery works for these paths apart from B2 and B3, but the suite does not guard it.
  - Suggested: a subprocess kill variant for `update`, `add` and adopt, and a checkpoint between `save_profile` and `set_phase` in `_update`.
- **N8** (corrupt journal): an unknown `operation` cannot be recovered and blocks every change. Consider letting `recover --rollback` (or a `--discard`) drop an unrecognised journal after confirmation.

## Scope

The scope is in line with the ticket and the 003 map. `_replace` now restores a lone `.old` instead of deleting it, a data-safety fix within scope. No guard denials occurred, and no code, tickets or git state were changed by this review.
