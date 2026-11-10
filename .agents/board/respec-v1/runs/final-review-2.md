# Final review 2: respec v1, whole feature

- Reviewer: fresh independent reviewer (did not implement any of this work)
- Range: `277d4363634ec92925f11ccb11284ecab0ea146f...4092c83fc1d41bd68a9cc763b1fe36694b5d0f00`
  (64 files, +23 643). Since final review 1 (374b7f2), fix-9 changed 21 files
  (+1 079 / -143): the new `src/respec/lock.py`, lock use in `cli.py` and
  `tui.py`, unique state temp names, the `update` `active` flag, message
  counts, README and shipped-skill text, and 20 new tests.
- Inputs: `spec.md`, tickets 001-013, and the "Engineer (chat)" amendments in
  `orchestration.md`. The amendments are treated as part of the spec: no
  `--home`, "skill" vocabulary, per-layer off, a skill added to an exclusive
  layer joins disabled, warn plus `layer repair`, add-to-active or
  remove-with-backup only (warn, not block), the manual TUI Sync, shipped skills
  in all targets with no opt-out, and "work until it works" for 007.
- Method: I ran the CLI from a clean `git archive` of 4092c83 in the
  scratchpad, with its own `uv sync --frozen` environment. Every run used a
  temporary `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`. Git sources were local
  bare repositories reached through `RESPEC_GIT_BASE_URL=file://…`. I did not
  edit the worktree. `git status` shows only the orchestrator's `.agents/`
  files.

## Verdicts

| Area            | Verdict                                                          |
| --------------- | ---------------------------------------------------------------- |
| Spec compliance | PASS (7/7 user stories; all exclusions respected)                |
| Code quality    | PASS (0 blocking)                                                |
| Tests rerun     | PASS: `pytest` 559 passed in 204 s, exit 0                       |
| Formatting      | PASS: Black 43 files unchanged; Prettier on committed md/yaml OK |
| Blocking        | 0                                                                |
| Parked (human)  | 012 (harness symlink and provider check), 013 (engineer review)  |

## Gates run independently

- `uv run pytest -q -p no:cacheprovider` in the worktree: **559 passed**
  (539 at final review 1, plus fix-9's 20 tests), exit 0.
- `uv run --frozen black --check .`: 43 files would be left unchanged.
- `npx prettier@3 --check` on every committed `.md` and `.yaml` file (taken
  from a `git archive` of 4092c83): all formatted. The worktree has 25
  uncommitted orchestrator run reports under `.agents/board/respec-v1/runs/`
  that Prettier would change. They are not part of the feature commit range
  and were left alone, as instructed.

## Final review 1 findings: re-checked

| Finding                                             | Status                             | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --------------------------------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N1: no inter-process lock                           | **Resolved**                       | `lock.py` puts an `flock` on `~/.respec/.lock`. It is reentrant per thread, waits up to 1 s, then raises `Busy`. Every mutating CLI command takes it: `profile new` and `install`, `use`, `recover`, `add`, `remove`, `enable` and `disable`, every layer change, `adopt`, `restore` (not `--list`) and `update` (not `--check`). The lock is let go at `ctx.call_on_close`. Every TUI change takes it as well (`tui.py`: `lock.exclusive` at 260, 564, 812, 841, 900, 1296 and later). State temp files are now named `.state.json.<pid>.<uuid>.tmp`, and leftovers are swept on a fresh acquire. **Repro of the final review 1 scenario:** 20 rounds of `use B`, `use A`, `enable s3`, `disable s3` and `status --json` run at once (40 skills × 3 targets). Result: 0 tracebacks, 7 clean `another respec is running` refusals, and no interrupted journal. Folder counts were equal across all three targets in every round, and no temp files were left. With the lock held externally, `enable --json` printed `{error, warnings}` and exit 1, `use --json` printed its full key set plus `error`, `status` still ran, and `disable` failed after about 1.1 s. |
| N3: `update --json` `active: false`                 | **Resolved**                       | `sources._update` now sets `active` from `state.active_profile` before any swap. A live `update gs --yes --json` on the active profile gave `"active": true`. A test was added in `test_sources.py`, and the README now documents `active`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| N4: README `--json` claim, counts, plurals          | **Resolved** (bullets 1 and 2)     | The README now says "Every command except `tui` accepts `--json`". `use` prints "installed 4 skills (10 links)", "installed 1 skill (1 link)" and "Removed 2 skills (4 links)".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| N4 bullet 3: shared-folder wording                  | Unchanged (deliberately)           | `fix-9-impl-1.md` records that this bullet was out of scope. Still observed: `use` says "Backed up agents folder to …/agents", while `restore` says "Restored agents from …/claude-code". The result on disk is correct. Listed as non-blocking below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| N2: no `profile rm`; N5: `cli.py` and `tui.py` size | Unchanged (engineer's call / info) | The duplicate `_delete` helpers are now merged into `trees.delete_entry`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

No regression found: the full suite is green, and the story scenarios below
behave as at final review 1.

## User stories (re-verified by CLI against 4092c83)

| #   | Story                                                                                                               | Verdict                                             | Evidence                                                                                                                                                                                                                                                                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | An oh-my-pi-only profile hides the previous profile from Claude Code and `.agents`                                  | PASS (delivered); real-harness claim depends on 012 | A(claude-code, agents) held a1 and a2. After `use B` (oh-my-pi), `~/.claude/skills` and `~/.agents/skills` held only `respec` and `profile-maker` (shipped, as amended) plus the user's pre-existing `old-skill`, which is warned about as unknown. `~/.omp/agent/skills` held b1 plus the shipped skills.                            |
| 2   | Add a skill from git in one command; see newer upstream commits; update on request                                  | PASS                                                | `add me/tools#skills/gs -p B --json` recorded repo, path, commit and digest, and linked gs. After an upstream push, `update --check --json` gave `update_available: true` with current and latest commits. `update gs --yes --json` applied v2 (`result: updated`). Without `--check` and without a run of `update`, nothing changed. |
| 3   | Disable a skill without losing files, source or edits                                                               | PASS                                                | `disable gs` unlinked it from `~/.omp/agent/skills`. `profile.yaml` kept `enabled: false` and the full `source:` record. `enable gs` linked it again.                                                                                                                                                                                 |
| 4   | Layers; choosing one in an exclusive layer turns the others off                                                     | PASS                                                | `layer add-skill design-principles d2` disabled d2 on joining, because d1 was already enabled. `layer use design-principles d2` disabled d1, linked d2 and unlinked d1. Repair, off and on were covered by `test_layers.py` and `test_layer_repair.py` (green).                                                                       |
| 5   | `respec restore` returns folders to their pre-respec contents                                                       | PASS                                                | `restore` removed every respec link and brought `old-skill` back byte-identical ("orig"). It removed `~/.agents/skills` and `~/.omp`, which did not exist before, and left no profile active. It also worked with `~/.agents/skills` symlinked to `~/.claude/skills`: the symlink was kept and the content restored.                  |
| 6   | A foreign skill in an owned folder is offered for resolution; nothing is lost (amended)                             | PASS                                                | The foreign folder appeared in `status` and in `adopt --json` `unresolved`, as a warning that did not block. `adopt --remove foreign` backed it up to `backups/<ts>/agents/foreign` before deleting it. `old-skill`, which was not chosen, was listed as left as it is.                                                               |
| 7   | An agent reads the shipped `respec` skill, uses `--json`, builds profiles via `profile-maker`, and knows hook scope | PASS                                                | The shipped `respec/SKILL.md` now documents the lock and the busy JSON shape, which matches the live output above. `test_shipped_skill_docs.py` checks every documented command and option against the real Typer tree (green).                                                                                                       |

**Total: 7/7.**

## Out-of-scope items (spec Exclusions)

| Exclusion                                              | Respected | Evidence                                                                           |
| ------------------------------------------------------ | --------- | ---------------------------------------------------------------------------------- |
| Output styles, hooks, instruction files, MCP, settings | Yes       | No such code. Hooks appear only as the documented scope rule in the shipped skill. |
| Project-scoped skills                                  | Yes       | Only the three global folders in `targets.yaml`.                                   |
| Per-skill target restriction                           | Yes       | Skill keys are `enabled` and `source` only.                                        |
| Targets beyond the three                               | Yes       | `targets.yaml` lists exactly claude-code, agents and oh-my-pi.                     |
| Automatic import or updates                            | Yes       | Installing creates nothing. Updates run only on `update`. Sync is manual.          |
| Profile inheritance or shared library                  | Yes       | Profiles are self-contained folders.                                               |
| Packaging and publishing                               | Yes       | Only `pyproject.toml` (hatch); nothing is published.                               |

## Parked human work, and delivered behavior that depends on it

- **012 (parked, not a defect):** nobody has verified in real harnesses
  whether symlinked skill folders load, or which foreign providers oh-my-pi
  enables. Delivered behavior that depends on 012:
  - Install mode is always a symlink. A copy is made only when `os.symlink`
    raises (`src/respec/switch.py:424`). There is still **no per-target
    copy-mode field** in `targets.yaml` or `targets.py`. If 012 finds a harness
    that ignores symlinked folders, ticket 012's "set copy mode in the
    registry" needs new code, not just a data edit.
  - Story 1 isolation, and the README and shipped-skill claims that the
    harnesses see nothing from other profiles, assume oh-my-pi reads only
    `~/.omp/agent/skills`, `~/.claude/skills` and `~/.agents/skills`.
  - The shipped `respec` and `profile-maker` links in every target (an
    amendment) assume every harness loads them through symlinks.
  - `docs/harness-notes.md` (an output of 012) does not exist yet. That is
    expected.
- **013 (parked):** engineer review, not started.

## Security

fix-9 added no new input surface. The lock file is created `0o644` in the
user's own respec home. Its descriptor is non-inheritable (Python's default
`O_CLOEXEC`), so git child processes do not keep the lock. Git transport
limits, `--end-of-options`, and symlink and path-traversal refusals are
unchanged since final review 1 (`sources.py` changed only in the `active`
flag), and their tests are green.

## Data safety and concurrency

- The concurrent stress run above showed no lost content, no stuck journal and
  no drift between targets.
- `test_concurrency.py` (12 tests) spawns real child processes. It covers a
  kill while a change holds the lock (no stale lock), racing switches, state
  saves from several threads, status reading while a change ends, and the
  temp-file sweep. These are behavioral tests, not mirrors of the
  implementation.

## Findings

No finding blocks.

### N1 (low): an interactive prompt holds the lock indefinitely

- **Location:** `src/respec/cli.py`. `_hold_lock` is taken before the
  `use` or `adopt` prompts, and `ctx.call_on_close(lock.release_all)` releases
  it only at the end.
- **Scenario:** a user leaves `respec use B` waiting at an unknown-entry
  prompt. Every TUI toggle and every agent CLI change then fails with
  `another respec is running` until the prompt is answered.
- **Impact:** small. The behavior is intended and documented (README "Running
  two at once" and the shipped skill), and the error message is clear. It
  could surprise an agent that retries in a loop. No change needed for v1.

### N2 (low): a TUI change made during a long TUI git fetch is refused

- **Location:** `src/respec/tui.py`. The git worker holds `lock.exclusive`
  for the whole fetch, and a change on the UI thread waits up to 1 s in
  `lock.acquire`.
- **Scenario:** the user adds a git skill in the TUI and toggles another skill
  while the fetch is still running. The toggle is refused, after the UI
  freezes for up to 1 s, with the busy message.
- **Impact:** cosmetic. No data is affected. `fix-9-impl-1.md` records this.

### N3 (info): shared-folder backup and restore wording (final review 1 N4, bullet 3)

- **Location:** the restore report in `src/respec/cli.py` (`_report_restore`).
- **Scenario:** with `~/.agents/skills` pointing to `~/.claude/skills`,
  `restore` prints "Restored agents from …/claude-code", although `use` had
  reported "Backed up agents folder to …/agents".
- **Impact:** confusing wording only. The result on disk is correct.

### N4 (info): `profile rm` is still missing (final review 1 N2)

This is a new feature and the engineer's call. It is not re-litigated here.

## Known non-blocking items (already triaged, listed only)

- `status --json` rarely hits a `FileNotFoundError` during a concurrent
  switch (read-only).
- The TUI doesn't show `unreadable-takeover-log`.
- `version: true` is read as v1.
- `restore --release-only` doesn't name paths that are gone.
- A rerun of `restore` omits a removal made by the earlier run.
- There is no `profile rm`.

## Test quality

- 559 behavioral tests drive the CLI, child processes and Textual Pilot
  against temporary homes. They assert on the filesystem, `state.json` and the
  `--json` output.
- I found no source-text assertions on `.py` files and no mirror tests.
  `test_isolation.py` still guards against touching the real home.
- fix-9's new tests are behavioral: real processes, real locks and kills.

## README and shipped-skill accuracy

I checked these sections against the live CLI:

- the README's "Running two at once" section and the JSON-on-busy rule
  (`use` gives its full keys plus `error`; other commands give only `error`
  and `warnings`; exit 1);
- the `active` field;
- the `--json` exception for `tui`;
- the `use`, `add`, `update`, `enable`/`disable`, layer, `adopt` and
  `restore` flows.

All of them matched what I observed, apart from the wording in N3. Both
shipped skills are covered by `test_shipped_skill_docs.py` (green).
