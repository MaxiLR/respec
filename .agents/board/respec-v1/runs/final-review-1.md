# Final review 1: respec v1, whole feature

- Reviewer: fresh independent reviewer (did not implement any of this work)
- Range: `277d4363634ec92925f11ccb11284ecab0ea146f...374b7f28815e7a7c919e65d0ddac7d18276dbb87`
  (62 files, +22 707)
- Inputs: `spec.md`, tickets 001-013, and the "Engineer (chat)" amendments in
  `orchestration.md`. Those amendments were applied and are not reported as
  defects: no `--home`, "skill" vocabulary, per-layer off, joining an exclusive
  layer as disabled, `layer repair`, add or remove only (no keep-unmanaged), the
  manual TUI Sync, shipped skills in all targets, and "work until it works" for 007.
- Method: I ran the code from a clean `git archive` of 374b7f2 in the
  scratchpad, so the worktree was not touched. Every CLI run used a temporary
  `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`, and git sources were local bare
  repositories reached through `RESPEC_GIT_BASE_URL=file://…`.

## Verdicts

| Area            | Verdict                                                 |
| --------------- | ------------------------------------------------------- |
| Spec compliance | PASS (7/7 user stories, all exclusions respected)       |
| Code quality    | PASS (no blocking defects; non-blocking findings below) |
| Tests rerun     | PASS: `pytest` 539 passed in 188 s                      |
| Formatting      | PASS: Black 41 files unchanged; Prettier md + yaml OK   |
| Blocking        | 0                                                       |
| Parked (human)  | 012 (harness symlink and provider check), 013 (review)  |

## Gates run independently

- `uv sync --frozen`, then `uv run --frozen pytest -q -p no:cacheprovider`:
  **539 passed** (exit 0).
- `uv run --frozen black --check .`: 41 files would be left unchanged.
- `npx prettier@3 --check "**/*.md"` and `"**/*.yaml"`: all files formatted.

## User stories

| #   | Story                                                                                                                  | Verdict                                                 | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                    |
| --- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | An oh-my-pi-only profile hides the previous profile from Claude Code and `.agents`                                     | PASS (delivered); the real-harness claim depends on 012 | CLI run: A(claude-code, agents) with a1 and a2, then `use B` (oh-my-pi). `~/.claude/skills` and `~/.agents/skills` held only `respec` and `profile-maker` (shipped, per amendment) plus the user's pre-existing `old-skill`, which was reported as unknown. None of A's skills remained. Tests: `test_use_status.py` (A→B scenario), `test_global_skills.py`.                                                               |
| 2   | Add a skill from GitHub in one command, see newer upstream commits, update only on request                             | PASS                                                    | CLI run: `add me/tools#skills/gs -p B` recorded repo, path, commit and digest, and linked the skill. After an upstream push, `update --check --json` gave `update_available: true`. A local edit made `update` prompt (`Aborted.` with no answer), `update --json` returned `skipped-local-edits`, and `--yes` applied v2. Tests: `test_sources.py` (90 tests).                                                             |
| 3   | Disable a skill without losing its files, source or edits                                                              | PASS                                                    | CLI run: `disable gs` unlinked it, while the folder and the `source:` record stayed in `profile.yaml`. `enable gs` linked it again. Tests: `test_items.py`.                                                                                                                                                                                                                                                                 |
| 4   | Layers; in an exclusive layer, choosing one turns the others off                                                       | PASS                                                    | CLI run: `layer add-skill design-principles d2` joined as disabled. `layer use … d2` disabled d1, and `enable d1` unlinked d2. `output-style` refused skills. `layer off` let both be enabled. `layer on` with a conflict was refused with a repair hint, and `layer repair --keep d2` fixed it. A hand-edited conflict was warned about in `status` and refused by `use`. Tests: `test_layers.py`, `test_layer_repair.py`. |
| 5   | `respec restore` returns folders to their pre-respec contents                                                          | PASS                                                    | CLI run: `restore` removed 10 respec entries, brought back `old-skill` byte-identical, left `~/.agents/skills` empty as it was found, and removed `~/.omp` (which did not exist before). `status` showed no active profile. I repeated this with `~/.agents/skills` symlinked to `~/.claude/skills`: correct. Tests: `test_restore.py`.                                                                                     |
| 6   | A foreign skill in an owned folder is offered for resolution and nothing is lost (amended: add or remove only)         | PASS                                                    | CLI run: foreign folder and file entries were listed by `adopt --json`. `--add foreign` copied it into the active profile and linked it. `--remove` and `--all remove` backed up to `backups/<ts>/<target>/` before deleting. An edited copy blocked `remove`, `disable` and `use` without touching the edit. Tests: `test_adopt.py` (65 tests).                                                                            |
| 7   | An agent reads the shipped `respec` skill, uses `--json`, can build profiles via `profile-maker`, and knows hook scope | PASS                                                    | Read both shipped `SKILL.md` files. They cover the CLI, schema, layers, sources, adopt, recovery and the hook-scope rule, and `profile-maker` rejects project-scoped content. `test_shipped_skill_docs.py` runs `--help` for every documented invocation and option and checks that every leaf command is named.                                                                                                            |

**Total: 7/7.**

## Out-of-scope items (spec Exclusions)

| Exclusion                                              | Respected? | Evidence                                                                                                                                              |
| ------------------------------------------------------ | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Output styles, hooks, instruction files, MCP, settings | Yes        | No such code. `output-style` layer refuses skills. Hooks appear only as documented future rules in the shipped skill.                                 |
| Project-scoped skills                                  | Yes        | Only the three global folders.                                                                                                                        |
| Per-skill target restriction                           | Yes        | `SKILL_KEYS = ("enabled", "source")`; other keys are rejected.                                                                                        |
| Targets beyond the three                               | Yes        | `targets.yaml` lists exactly claude-code, agents and oh-my-pi.                                                                                        |
| Automatic import or updates                            | Yes        | `respec status` on an empty home created nothing at all. Updates run only on `update`. No watcher (`test_sync_does_not_watch_the_folders_by_itself`). |
| Profile inheritance or shared library                  | Yes        | `TOP_LEVEL_KEYS = ("targets", "skills", "layers")`.                                                                                                   |
| Packaging and publishing                               | Yes        | Only `pyproject.toml` with a hatch build; nothing is published.                                                                                       |

## Parked human work, and delivered behavior that depends on it

- **012 (parked):** nobody has yet checked in real harnesses whether Claude
  Code, the `.agents` readers and oh-my-pi load skills through symlinked
  folders, or which foreign providers oh-my-pi enables by default.
  Delivered behavior that depends on the outcome:
  - Install mode is always a symlink. A copy is made only when `os.symlink`
    raises (`switch._install`, `src/respec/switch.py:416`). There is **no
    per-target copy-mode setting** in `targets.yaml` or `targets.Target`. If
    012 finds a harness that ignores symlinked skill folders, that needs a new
    registry field and an install-path change, not just a data edit. Ticket
    012 says "set copy mode for that target in the registry", but no such field
    exists yet.
  - Story 1 isolation, and the README and shipped-skill claims that oh-my-pi
    sees nothing from other profiles, assume oh-my-pi reads only
    `~/.omp/agent/skills`, `~/.claude/skills` and `~/.agents/skills`.
  - The decision to put shipped `respec` and `profile-maker` links into every
    target assumes each harness loads them through symlinks.
  - `docs/harness-notes.md` (an output of 012) does not exist yet. That is
    expected.
- **013 (parked):** engineer review, not started. This is not a defect.

## Security

All checked; no blocking issue.

- **Git transport and argument injection:** `GIT_ALLOW_PROTOCOL` is limited to
  `file:git:http:https:ssh`, and `--end-of-options` comes before user values.
  Repository-local `GIT_*` variables are stripped, prompts are disabled, and
  ssh runs in BatchMode. Every command has a timeout and runs in its own
  process group. Tried: an `ext::sh -c …` source (treated as a missing local
  folder, never passed to git) and `--upload-pack=…` (rejected by option
  parsing).
- **Symlink exfiltration:** I built a bare repo containing a link to an
  absolute secret file (`skills/ev/leak`), a `../../..` folder link
  (`skills/ev2/up`), a profile whose `skills/a1` is a link to a local folder,
  and a `profile.yaml` with a skill named `../../../escape`. Every case was
  refused before anything was written, and `grep SECRET` over
  `~/.respec` found nothing.
- **Path traversal:** `#../../` paths, and `../` in profile, layer, skill and
  backup names, are all refused by `NAME_PATTERN` or `source_value_problem`.
  `adopt --remove ../../.respec` gave "no unknown entry matches".

## Data safety

All checked.

- An edited copy sitting where a skill is installed blocked `remove`,
  `disable` and `use`, and the user's edit survived each time. `adopt
--remove` writes the backup before deleting.
- I did not repeat the SIGKILL matrices that earlier reviews ran (the
  integration runs report 52-98 kills with no loss). The 539 tests include the
  journal and recovery suites, and they pass.

## Findings

No finding is blocking. They are ordered by severity.

### N1 (medium): no lock between concurrent respec processes

- **Location:** `src/respec/state.py` (fixed temp name `.state.json.tmp`);
  `journal.ready`; there is no lock anywhere (`grep -i lock` finds none).
- **Scenario 1:** I ran `respec use B & respec use A` concurrently 15 times in
  one temp home (40 skills × 3 targets). 14 runs printed a raw Python
  traceback, `FileNotFoundError … .state.json.tmp -> state.json`, because
  both processes share one temp file name.
- **Scenario 2:** I added concurrent `enable sN` and `disable sN` to the same
  loop (12 rounds).
  - Twice, `status` reported `interrupted-operation: pending` while no respec
    process was running. `respec recover` then finished it.
  - Once, `status` reported folder counts that differed between targets
    (claude-code 40, agents 41) with no warning and no unresolved entry.
- **What was not affected:** no file content was lost, and profile skill
  folders were untouched.
- **Impact:** agents in several harnesses, or the TUI next to an agent's CLI
  call, can plausibly run respec at the same time. When that happens, users
  see tracebacks, spurious "interrupted" journals and drifted links that only
  Sync or `use` notices. Ticket 003 excludes concurrency only "beyond a simple
  lock file", so a simple lock seems to have been intended, but no acceptance
  criterion demanded one.
- **Suggested fix:** an exclusive `flock` on `~/.respec/.lock` around every
  mutating command and around journal recovery, plus unique temp names.

### N2 (low): no way to delete a profile through the CLI

- **Location:** `respec profile --help` lists only `new`, `list`, `show` and
  `install`.
- **Scenario:** the spec's proposed command surface included
  `profile new|list|show|rm`, but no ticket picked up `rm`. The shipped skill
  tells agents never to edit profile folders by hand. If a user deletes an
  active profile's folder by hand instead, the links are left broken.
- **Impact:** a small gap in the command surface. Worth a follow-up ticket
  that, for example, refuses to remove the active profile.

### N3 (low): `update --json` reports `"active": false` for the active profile when nothing was swapped

- **Location:** `src/respec/sources.py`, `UpdateResult.active` (default
  `False`, set only by `items.refresh_active`).
- **Scenario:** with B active, `respec update gs -p B --json` and the skill
  skipped for local edits printed `"active": false`.
- **Impact:** an agent reading `active` could believe B is not the active
  profile. The field is undocumented in the README; rename it, document it,
  or always fill it.

### N4 (low): small doc and wording inaccuracies

- **`--json` claim:** the README says "Every command accepts `--json`", but
  `tui` does not. The shipped skill states this correctly.
- **Counts:** `use` prints "installed 10 skills", which counts links, not
  skills (2 skills × 2 targets + 2 shipped × 3 targets). It also prints
  "installed 1 skills" and "Removed 1 skills" (pluralisation, also noted in
  int-374b7f2).
- **Shared folder report:** when `~/.agents/skills` is a symlink to
  `~/.claude/skills`, `use` reports "Backed up agents folder to …/agents", but
  `restore` reports "Restored agents from …/claude-code". The result is
  correct; the message is confusing.

### N5 (info): code-size and duplication hotspots

- `cli.py` is 1 633 lines and `tui.py` 1 802. The duplicate `_delete` helpers
  that int-374b7f2 noted are still there.
- This is not a defect, but splitting the CLI JSON and report plumbing out of
  `cli.py` would ease the next phase (hooks and output styles).

## Test quality

- There are 539 tests across 19 files. They are behavioural: they drive the
  CLI against temp homes, assert on the filesystem, `state.json` and `--json`
  output, use local bare git repos, and include Textual Pilot tests with 94
  `pilot.click` calls.
- I found no source-text assertions on `.py` files and no mirror tests.
  `test_shipped_skill_docs.py` reads the shipped Markdown and checks it
  against the real Typer command tree and `--help`. That is a doc-accuracy
  test, which is appropriate.
- `tests/test_isolation.py` fails any test that resolves a path under the
  real home.

## README and shipped-skill accuracy

- Every command and option in both shipped skills exists (test plus manual
  read).
- The README matched what I observed for `use`, `status`, `add` (local and
  git), `update`, `enable` and `disable`, the layers commands, `adopt` and
  `restore`, with the exceptions in N3 and N4.
