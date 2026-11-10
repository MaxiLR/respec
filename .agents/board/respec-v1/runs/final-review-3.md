# Final review 3: respec v1, whole feature

- Reviewer: a fresh, independent reviewer who implemented none of this work.
- Range: `277d4363634ec92925f11ccb11284ecab0ea146f...a530f42d9ecf24fb29fab82e87a519a4f245900b`.
  Since final review 2 (4092c83), only fix-10 has landed (`4092c83..a530f42`:
  10 files, +874/-17). It adds the new `removal.py`, the
  `profiles.existing_folder` check that `load_profile` now uses, `cli profile
remove`, `switch.new_backup_run(parent=)`, the TUI `RemoveProfileDialog` with
  `d`/Remove, README and shipped `respec/SKILL.md` text, and 30 new tests.
- Inputs: `spec.md`, tickets 001-013, and the "Engineer (chat)" amendments in
  `orchestration.md`, which count as part of the spec: no `--home`, "skill"
  vocabulary, per-layer off, a skill added to an exclusive layer joins
  disabled, warn plus `layer repair`, unknown entries resolved only by add or
  remove (warn, don't block), the manual TUI Sync, shipped skills in all
  targets, "work until it works" for 007, and `respec profile remove`.
- Method: I worked from a clean `git archive` of a530f42 in
  `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/fr3/src`,
  with its own `uv sync --frozen --offline`. Every CLI run used a temporary
  `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`. Git sources were local bare
  repositories reached through `RESPEC_GIT_BASE_URL=file://…`. The worktree has
  no AGENTS.md. I edited no code; the only file I wrote in the worktree is this
  report. There were no guard denials.

## Verdicts

| Area            | Verdict                                                          |
| --------------- | ---------------------------------------------------------------- |
| Spec compliance | PASS (7/7 user stories, 7/7 exclusions, fix-10 amendment met)    |
| Code quality    | PASS (0 blocking)                                                |
| Tests rerun     | PASS: `pytest` 589 passed in 246 s, rc 0                         |
| Formatting      | PASS: Black 45 files unchanged; Prettier on committed md/yaml OK |
| Blocking        | 0                                                                |
| Parked (human)  | 012 (harness symlink and provider check), 013 (engineer review)  |

## Gates run independently

- `uv run --frozen --offline pytest -q -p no:cacheprovider` (archive copy):
  **589 passed** in 246.47 s, rc 0. That is 559 at final review 2 plus 30 from
  fix-10.
- `uv run --frozen --offline black --check .`: 45 files would be left unchanged.
- `npx --no-install prettier --check` on every committed `.md`, `.yaml` and
  `.json` file at a530f42: all formatted.

## fix-10: `respec profile remove` and exact profile names

The engineer's amendment asked that removal refuse the active profile, never
delete, take the lock, honour the `--json` contract, have a TUI action, and be
documented. I checked each point live:

| Check                                                         | Result                                                                                                                                                                                                                   |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Remove an inactive profile                                    | `profile remove extra --json` rc 0 `{name, path, backup, warnings}`; folder (profile.yaml, skills) at `removed-profiles/<UTC>/extra`; `profile list` no longer shows it                                                  |
| Remove it again                                               | rc 1 "does not exist; create it with …"                                                                                                                                                                                  |
| Active profile                                                | `profile remove B --json` rc 1 "is active, so it cannot be removed; nothing was changed …", JSON on stdout                                                                                                               |
| Alias of the active profile (`profiles/Plink -> P`, P active) | refused as active (`os.path.samefile`), nothing moved                                                                                                                                                                    |
| Case variants (APFS, case-insensitive)                        | `profile remove b`, `profile remove EXTRA`, `profile show EXTRA` and `use a --json` all rc 1 "does not exist (names are case-sensitive; did you mean 'B'?)"; `use` keeps its full key set plus `error`; `B` stays active |
| Invalid name                                                  | `../x` refused by `validate_name`                                                                                                                                                                                        |
| After `restore` (no active profile)                           | `profile remove B` rc 0                                                                                                                                                                                                  |
| Lock, journal, kill, TUI                                      | covered by `test_profile_remove.py` (pending journal refused, lock holder refused, kills at `profile-remove:move`/`moved`, empty run cleanup, linked-skill refusal) and `test_tui.py`; all green                         |

Code read (`removal.py`): the profile moves with one `os.rename` under
`lock.exclusive`, after these checks in order: journal pending, exact-name
existence, active (by name or samefile), and leftover symlinks into the profile
from every target folder and owned folder. A failed rename (for example EXDEV)
cleans up the empty run folder and changes nothing. `_drop_empty_runs` only
`rmdir`s, so it can never delete content. Ordering is safe: the removal holds
the lock, so a concurrent `use` cannot make the profile active between the
check and the rename.

### Regression check on the `load_profile` change

`load_profile` now goes through `existing_folder`. That function rejects any
name that `os.listdir(profiles/)` does not list exactly, and suggests the
case-folded match when there is one.

- Names match `^[A-Za-z0-9][A-Za-z0-9._-]*$` (ASCII), so APFS Unicode
  normalization cannot make a valid name fail.
- Every caller passes a name that is either user input or read from disk (the
  TUI uses `list_profile_names`, and `recover` rebuilds from folder names), so
  exact matching never turns down a legitimate name.
- Creation paths (`create_profile`, `install_profile`) still test existence
  through the file system, so `profile new WORK` is refused when `work` exists.
  `profile new EXTRA` worked after `extra` had been removed.
- A symlinked profile folder still loads (`profile show Plink`).
- A `listdir` per profile load costs nothing at this scale.
- The full suite (all `use`, `add`, layer, update, TUI and concurrency tests)
  is green. I found no regression.

## User stories (quick re-confirmation at a530f42)

| #   | Story                                                                                               | Verdict                                             | Evidence (this run)                                                                                                                                                                                                  |
| --- | --------------------------------------------------------------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | An oh-my-pi-only profile hides the others from Claude Code and `.agents`                            | PASS (delivered); real-harness claim depends on 012 | after `use B` (oh-my-pi): `~/.claude/skills` = old-skill (warned as unknown), profile-maker, respec; `~/.agents/skills` = profile-maker, respec; `~/.omp/agent/skills` = b1 + shipped                                |
| 2   | Add from git in one command; see newer commits; update on request                                   | PASS                                                | `add me/tools#skills/gs -p B --json` recorded repo/path/commit/digest; after an upstream push `update --check` gave `update_available: true`; `update gs --yes` gave `result: updated`, `active: true`               |
| 3   | Disable without losing files, source or edits                                                       | PASS                                                | `disable gs` unlinked it; `profile.yaml` kept `enabled: false` plus the full `source`; `enable gs` relinked it                                                                                                       |
| 4   | Layers; picking one in an exclusive layer turns the others off                                      | PASS                                                | `layer add-skill design-principles d2` disabled d2 on joining; `layer use … d2` swapped the links; `layer off` allowed both; `layer on` refused with a repair hint; `layer repair --keep d1` kept d1 and unlinked d2 |
| 5   | `restore` returns folders to their pre-respec contents                                              | PASS                                                | `restore --overwrite --json` released all three folders; `old-skill` came back byte-identical ("orig"); `.agents` and `.omp`, which did not exist before, were removed                                               |
| 6   | A foreign skill is offered for resolution; nothing is lost (amended)                                | PASS                                                | `status` lists an unknown entry with an `adopt` hint (warn, not block); `adopt --remove foreign --json` backed it up to `backups/<ts>/agents/foreign` before removing it                                             |
| 7   | An agent uses the shipped `respec` skill and `--json`, builds via `profile-maker`, knows hook scope | PASS                                                | the shipped SKILL.md documents `profile remove` and its JSON shapes, which match the live output; `test_shipped_skill_docs.py` checks it against the real Typer tree (green)                                         |

**Total: 7/7.**

## Out of scope (spec Exclusions)

None of these changed since final review 2, and fix-10 touched none of them:
output styles, hooks, instruction files, MCP or settings (none); project-scoped
skills (only the three global folders); per-skill target restriction (none);
targets beyond the three (`targets.yaml` lists exactly claude-code, agents and
oh-my-pi); automatic import or updates (none; `removed-profiles/` is never
pruned or restored automatically); profile inheritance (none); packaging and
publishing (none). **7/7 respected.**

## Parked human work, and what depends on 012

- **012 (parked, not a defect):** nobody has checked in real harnesses whether
  symlinked skill folders load, or which foreign providers oh-my-pi enables.
  These delivered behaviours depend on it:
  - Install mode is always a symlink, with a copy only when `os.symlink`
    fails. There is still **no per-target copy-mode field** in `targets.yaml`
    or `targets.py`. If 012 finds a harness that ignores symlinked folders,
    012's "set copy mode in the registry" will need new code, not just a data
    edit.
  - Story 1 isolation, and the README and shipped-skill claims that the
    harnesses see nothing of other profiles, assume oh-my-pi reads only its
    own folder plus `~/.claude/skills` and `~/.agents/skills`.
  - The shipped `respec` and `profile-maker` links in every target assume
    every harness loads them through symlinks.
  - `docs/harness-notes.md` (an output of 012) does not exist yet. That is
    expected.
- **013 (parked):** the engineer's review. It waits on 012 and the engineer.

## Security, data safety, concurrency

- fix-10 opens no new path from outside. The name goes through
  `validate_name` first, so a name cannot escape `profiles/`.
- Removal never deletes content: it renames, and it only `rmdir`s empty run
  folders. A link into the profile, whatever `state.json` says, blocks the
  removal, so no live link is left dangling.
- The lock covers both the CLI and the TUI. A pending journal refuses removal,
  so a later rollback can never point at a removed profile.
- Git transport limits, symlink and traversal refusals, and the lock and
  journal are unchanged since final review 2. Their tests are green.

## Findings

No finding blocks.

### N1 (info, new): the shipped SKILL.md describes the failure JSON of `profile remove` slightly loosely

- Location: `src/respec/shipped/respec/SKILL.md`, the "Exit code" bullet.
- It says `profile remove` "prints `name` and `error`". The live output also
  has `warnings: []`, as every JSON object does under the contract, and as the
  lock bullet just below says. No agent would be misled. Wording only.

## Known non-blocking items (already triaged, listed only)

- final review 2 N1: an interactive prompt holds the lock until it is answered
  (documented).
- final review 2 N2: a TUI change made during a long TUI git fetch is refused
  after up to 1 s.
- final review 2 N3: shared-folder backup and restore wording ("Restored
  agents from …/claude-code").
- `status --json` rarely raises `FileNotFoundError` during a concurrent switch
  (read-only).
- The TUI doesn't show `unreadable-takeover-log`.
- `version: true` is read as v1.
- `restore --release-only` doesn't name paths that are gone.
- A rerun of `restore` omits a removal made by the killed earlier run.
- int-a530f42 / fix-10 review 2 N5: while a journal waits, the generic stderr
  warning says "any respec command that changes skills finishes it first", but
  `profile remove` refuses instead (its own error is correct).
- int-a530f42 / fix-10 review 2 N6: `profile new WORK` / `profile install
--name WORK` say "already exists at …/profiles/WORK" (the typed variant)
  instead of naming `work`.
- final review 2 N4 (`profile rm` missing) is **resolved** by fix-10.

## Test quality

- fix-10's 30 tests drive the real CLI, child processes, kill points and the
  Textual Pilot against temporary homes. They assert on the file system,
  `state.json` and the JSON output. I found no source-text or mirror tests.
- The case-variant tests cover both the refusal and the fact that the active
  profile is left unchanged.

## README and shipped-skill accuracy

I checked these against the live CLI: the README `profile remove` paragraph
(backup path, `backup` key, refusals, case sensitivity, kill behaviour), the
lock list and busy JSON (`name`, `error`, `warnings`), the TUI Remove (`d`)
description, `profile --help`, and the shipped `respec/SKILL.md` command entry.
All of them match, apart from the N1 wording above.
