# t009 review 1 (fresh, independent)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t009`
- Diff: `b8d1aee..5dc0cd1` (one commit, 11 files)
- Judged against: ticket 009 as amended by engineer decisions 1-5, and spec decisions 11 and 12

## Verdicts

- spec-compliance: FAIL (one blocking finding, F1)
- code-quality: FAIL (F1)
- tests-rerun: PASS

## Gates rerun

- `uv run --frozen pytest -q`: 373 passed.
- `uv run --frozen black --check .`: 32 files unchanged.
- `npx prettier@3 --check README.md src/respec/shipped/*/SKILL.md`: all formatted.
- `uv build --offline`: both the sdist and the wheel contain `respec/shipped/respec/SKILL.md` and `respec/shipped/profile-maker/SKILL.md`. Packaging works, since hatch picks up the files under `src/respec`.

## Blocking findings

### F1: adopt "add" bypasses the guard against shipped and global skill names, which wedges the active profile and breaks the "shipped skills everywhere" invariant

- **Location**:
  - `src/respec/adopt.py` (add path) has no check against `global_skills`.
  - The guard exists only in `switch._check_global`, which `use` and the item refreshes (`add`, `enable`, `disable`) call.
  - `adopt --add`, interactive adopt, and `use --unknown add` (which adds to the profile being left) never run it.
- **Scenario** (real CLI, temp homes, symlink mode):
  1. Activate profile `p2` (targets oh-my-pi).
  2. Replace `~/.omp/agent/skills/profile-maker` (shipped link) with a folder holding an edited `SKILL.md`.
  3. Run `respec adopt --add profile-maker`. It exits 0, prints `Added ... to profile 'p2'`, and links `~/.omp/agent/skills/profile-maker` to `profiles/p2/skills/profile-maker`.
  4. `respec disable tdd` then fails with `cannot refresh profile 'p2': skill 'profile-maker' has the name of a skill respec ships ...`, and `respec use p2` fails the same way. The profile stays wedged until `respec remove profile-maker`.
- **Second variant**:
  1. Activate `pi` (omp only).
  2. Replace `~/.agents/skills/respec` with a folder.
  3. Run `adopt --add respec`. It moves the folder into `pi`, and `~/.agents/skills` is left with **no** `respec` skill: the shipped skill is missing from that target until some later switch. `pi` can then never be activated again.
- **Impact**:
  - A routine flow leaves the profile unusable. Fix-6 adopt prompts offer "add" for an edited shipped copy, and with fix-1 copy digests an edited copy in copy mode is reported as replaced, so the same flow applies there.
  - The amended rule "shipped skills in all targets whenever a profile is active" is violated.
  - The ticket asserts the same name-clash rule for `add`/`enable`, which do enforce it, so the behaviour is inconsistent.
  - The implementer's concern 4 acknowledges the block but not that adopt accepts the conflicting add in the first place.
- **Suggested direction**: refuse "add" for an unknown entry whose name is a shipped or global skill, and offer only "remove". This should happen in the adopt preflight and in the switch's `--unknown add` path, with a test for each.

## Non-blocking observations

- **N1. Test seam (item a)**:
  - `tests/conftest.py::shipped_skills` monkeypatches `global_skills.shipped_names` to `()` unless a test has `@pytest.mark.shipped`.
  - It is a test-only seam: no environment variable, flag or config key reaches the product, so users have no opt-out. That is acceptable.
  - Spot check: a plugin that marks every test `shipped` gave 56 failed and 2 errors, matching the claim.
  - I categorized about 40 of the failures across adopt, tui, layers, layer_repair, items, use_status, restore and sources. All were one of:
    - extra `respec`/`profile-maker` entries in exact-list assertions;
    - "first takeover of a new target" or backup-count scenarios that can no longer occur, because every folder is taken over at the first `use`.
  - None was an interaction bug. The seam does hide F1, though: no shipped-marked test covers adopt "add" at a shipped path.
- **N2. Leftover folders after restore**:
  - Restore is byte-identical for `~/.claude/skills` and `~/.agents/skills`.
  - It leaves empty `~/.omp/agent` (and `~/.agents` when absent before) behind. The cause predates this change, but every user now gets these folders for tools they may not have installed.
- **N3. Takeover "add" for unrelated entries**: an unrelated entry in a folder outside the profile can be adopted with "add", which moves it into a profile that does not target that folder, so it disappears from its original folder. This follows the amended "normal unknown handling", and the implementer disclosed it.
- **N4. Status JSON**: it does not distinguish shipped and global entries from profile skills. The implementer disclosed this.

## Verified OK

### (b) Real CLI

Setup: profile `pi` = oh-my-pi; pre-existing `~/.claude/skills/{mine,respec}` and `~/.agents/skills/other`; `config.yaml` with `global.skills: [notes]`.

- `use pi` blocks on the unknown `~/.claude/skills/respec`. With no active profile, only remove is offered.
- `--unknown remove` backs it up. Then:
  - first-takeover backups are taken for claude-code and agents;
  - the shipped skills are linked into all three folders and `notes` only into omp;
  - `mine` and `other` only produce warnings.
- Switching to `cc` (claude-code):
  - `removed` has 2 entries (tdd and notes in omp) and `installed` has 2 (lint and notes in claude-code);
  - the shipped links are untouched;
  - `notes` follows the active targets.
- `restore` removes 8 skills. A file and mode snapshot of the original folders matches, including the hand-made `respec`. The only difference is the empty parent folders (N2).
- `respec add` of a skill named `respec` or `notes` to the active profile is refused and rolled back.

### (c) SKILL.md accuracy

- Every documented command and option matches `--help`, checked by hand for `profile install`, `layer repair --keep`, `layer add -d`, `adopt --add/--remove/--all`, `restore --list/--unknown/--overwrite`, `update --check/--yes` and `use --unknown`.
- The documented warning types match `cli.py`.
- There is no `--home`, "keep unmanaged" or "item(s)" in the shipped skills.
- The hook-scope rule is present and marked as not built.
- `profile-maker` rejects project-scoped content and applies changes only through the CLI.
- `tests/test_shipped_skill_docs.py` checks the docs against the real CLI rather than its own copy of the commands: it resolves the commands through Typer, runs `--help`, and checks coverage in both directions.

### (d) Fix-1 copy digests

- `refresh_shipped` leaves matching content alone and rewrites through a staged folder, so links stay valid. Copies are reinstalled on each switch, which avoids stale digests.
- `remove_installed` refuses to delete inside the shipped and global roots.
- `restore._respec_link` skips links into those roots.
