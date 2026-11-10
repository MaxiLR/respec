# t009 review 2 (fresh, independent)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t009` (clean tree)
- Diff: `b8d1aee..7ee413f` (the whole ticket: `5dc0cd1` plus fix `7ee413f`)
- Judged against: ticket 009 as amended by engineer decisions 1-5, spec decisions 11 and 12, and review 1 (F1, N2)

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking: 0

## Gates rerun

| Gate                                                             | Result                                     |
| ---------------------------------------------------------------- | ------------------------------------------ |
| `uv run --frozen pytest -q`                                      | 386 passed                                 |
| `uv run --frozen black --check .`                                | 32 files would be left unchanged           |
| `npx prettier@3 --check README.md src/respec/shipped/*/SKILL.md` | All matched files use Prettier code style! |
| `uv lock --check`                                                | Resolved 28 packages                       |

## F1 (review 1 blocker): fixed in every add path

All runs used the real CLI (`uv run --frozen --project <worktree> respec`) with `RESPEC_USER_HOME` set to scratch homes, plus a `file://` `RESPEC_GIT_BASE_URL` for git. "No change" was checked with a snapshot of the home tree (paths, link targets and file hashes) and, where noted, a byte comparison of `state.json`.

| Path                                                                                           | Result                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Review 1 reproduction: `p2` on oh-my-pi, replaced `profile-maker`, `adopt --add profile-maker` | exit 1, "cannot add 'profile-maker' ... Nothing was changed. Choose remove instead"; `state.json` byte-identical; the edited entry is untouched; the profile holds only `tdd` |
| Second variant: `pi`, `~/.agents/skills/respec` replaced, `adopt --add respec`                 | exit 1; snapshot unchanged                                                                                                                                                    |
| Global name: `~/.omp/agent/skills/notes` replaced, `adopt --add notes`                         | exit 1 ("it is a global skill listed in .../config.yaml"); unchanged                                                                                                          |
| `adopt --all add` with an unrelated `aaa` plus a reserved entry                                | exit 1; `aaa` not moved (snapshot unchanged)                                                                                                                                  |
| `use b --unknown add` (adds to the profile being left)                                         | exit 1; unchanged; `pi` stays active                                                                                                                                          |
| Adopt prompt (real pty)                                                                        | says it "cannot be added", offers only `[remove]`, re-asks on `add` ("please answer: remove"); remove backs up and relinks                                                    |
| CLI `add` (inactive profile `-p b`, shipped name; active profile, global name)                 | both exit 1, "Nothing was changed"; unchanged                                                                                                                                 |
| Git `add acme/tools` (`profile-maker` + `lint`), with and without `-p`                         | exit 1; `profile.yaml` still has `skills: {}`; nothing fetched into the profile                                                                                               |
| `profile install` (`respec`, disabled) and (`notes`, enabled)                                  | both exit 1; no profile folder created                                                                                                                                        |
| Extra: `restore --unknown add` over a replaced shipped link                                    | exit 1; `state.json` unchanged; then `restore --unknown remove` puts the user's original `respec` back                                                                        |

Resolution by remove:

- `adopt --remove profile-maker` printed `linked .../.omp/agent/skills/profile-maker`, and the link points at `<respec home>/shipped/profile-maker`.
- The interactive remove relinked `~/.agents/skills/respec` (shipped) and `~/.omp/agent/skills/notes` (global).
- After that, `disable tdd`, `use b` and `use pi` all succeed. No profile is wedged any more.

Code check:

- `global_skills.refuse_reserved` is called in `items.add_local`, `sources.add` (before the fetch is copied), `sources.install_profile` (before the folder is created) and `adopt._add`.
- `adopt.resolve` asks about reserved entries first and refuses before any entry is applied.
- The other ways a skill name gets into a profile do not add new names: `layer add-skill` needs an existing skill, and `update` replaces existing ones.

## Restore cleanup of created folders

**How it is recorded.** `switch._missing_folders` runs at takeover, before anything is created. It walks up from the skills folder while `os.path.lexists` is false, stops at the user home, and stores the result as `Owned.created`, deepest first. A folder that exists at takeover, even an empty one or a dangling symlink, is never recorded. `restore._remove_created` runs only after a fully successful restore and only for targets that no backup restores. It uses `rmdir` (never recursive) and skips symlinks.

| Case                                                                         | Result                                                                                                                        |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| A. Nothing existed before                                                    | home left with only `.respec`; `.claude`, `.agents` and `.omp/agent` are removed                                              |
| B. Empty `~/.omp`, `~/.agents` and `~/.claude` existed before                | `created` holds only the folders below them; all three stay                                                                   |
| C. Empty skills folders existed before                                       | backed up and restored; all stay                                                                                              |
| D. Created parents gained content (`.omp/agent/config.yml`, `.agents/other`) | kept with their content                                                                                                       |
| E. `~/.agents` is a symlink to `dot/agents`                                  | only `~/.agents/skills` is recorded; it is removed inside `dot/agents`; the symlink and its target stay                       |
| F. Switch `p` to `q`, then restore                                           | everything created is removed                                                                                                 |
| Review-1 regression setup                                                    | the home tree after restore is identical to the original (types, modes, hashes, link targets); review 1's N2 leftover is gone |

## No regression of review 1's verified behaviours

Setup as in review 1: profiles `pi` (oh-my-pi) and `cc` (claude-code), global `notes`, a pre-existing `~/.claude/skills/{mine,respec}` and `~/.agents/skills/other`.

- `use pi` blocks on the hand-made `respec` and offers only remove.
- `--unknown remove` makes takeover backups for claude-code and agents and installs 8 skills. `mine` and `other` only produce warnings.
- `use cc` succeeds.
- `add` of `respec` to `cc` is refused.
- `restore` gives a byte-identical original tree, including the hand-made `respec`.

## Non-blocking observations

- **N1. "Created" really means "missing at takeover".**
  - Location: `switch.use` saves state after `_take_over`, before `on_unknown` runs and before anything is installed.
  - Scenario: an interactive first `use` is interrupted at the unknown-entry prompt, so the target folders were recorded but never created. The user then creates one of those folders themselves, still empty. A later `restore` would `rmdir` it.
  - Impact: very narrow, and only empty folders are ever affected. It could be tightened by recording the folders after the links are installed. Not required.
- **N2. Hint wording in other contexts.** In the `restore --unknown add` and `use --unknown add` contexts, the refusal hint suggests `respec adopt --remove <name>`. That works, but `--unknown remove` would be the natural next step there. Cosmetic.
- **N3. Stale docstring.** The `global_skills` module docstring still says only "the switch refuses" for name clashes. The add-time refusal is documented in the README and in the shipped `SKILL.md`. Cosmetic.
- **N4. Known follow-up.** `tui.py` still offers add for a reserved entry. The core refuses it and nothing changes. Ticket 011, as stated.
- **N5. Older state files.** Folders taken over before this change have no `created` record, so restore never cleans them. That is safe, and the implementer disclosed it.

## Implementation claims checked

The claims in `t009-impl-2.md` match the code and the CLI behaviour above:

- the test count (386);
- the list of call sites;
- the relink on remove;
- the `created` recording;
- that cleanup applies only to targets without a backup.
