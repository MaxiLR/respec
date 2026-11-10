# fix-6 review 4: unknown-entry model v2, round-3 fix

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Diff: `493d8e8..4b79c93` (focus `777ca83..4b79c93`)
- Verdicts: spec-compliance **PASS**, code-quality **PASS**, tests-rerun
  **PASS**
- Blocking findings: **0**. R3-B1 is fixed in text and JSON. The
  `_clean_leftovers` safety item is fixed: no hard-kill state I simulated lost
  data. Fix-5 B1/B3 and the forced link failures show no regression.

## Gates rerun (fresh, at `4b79c93`)

| Gate                                                  | Result                                       |
| ----------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                    | `Audited 27 packages`                        |
| `uv lock --check`                                     | `Resolved 28 packages`                       |
| `uv run pytest -q`                                    | `344 passed in 54.08s`                       |
| `uv run black --check .`                              | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md`                    | `All matched files use Prettier code style!` |
| `uvx ruff check src --select F`                       | `All checks passed!`                         |
| `grep -ci item` over `--help` of 14 commands          | 0                                            |
| `click` in `pyproject.toml`                           | `"click>=8.1"`                               |
| Red check: the new tests on `git archive 777ca83 src` | 7 fail, 4 pass (matches the impl claim)      |

For the red check, `respec.__file__` pointed at the archive. The 7 failures are
the takeover-reporting, leftover, wording and TUI tests. The 2 passing new tests
are the regression guards the implementer named. The tests check behavior
(disk, state, stdout/stderr, JSON). None asserts on source text.

## Real-CLI scenarios

Each scenario ran in a fresh temp home under the scratch directory, with
`HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` set, using the worktree's
installed `respec`. TTY runs used a `pty` driver that sends a real `\x03`.
Forced link failures used a wrapper that patches `switch._install` to raise
`OSError(28)` for named skills before `respec.cli.app()`. Copy-mode setups
patched `os.symlink` to refuse during the initial `use`.

R3-B1 setup (exact): `a` (claude-code: `tdd`, `lint` disabled) active; `b`
(claude-code + agents: `first`, `lint`); hand-made `first` and `lint` in
`~/.claude/skills`; `foreign` in a not-yet-owned `~/.agents/skills`.

| Scenario                                                                     | Result                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R3-B1 text**, pty: `first: remove`, `lint: add` (clash)                    | rc 1. It prints `Backed up …/first … and removed it` and `Backed up agents folder to …/backups/<run>/agents`, then the clash error and warnings for `lint` and `foreign`. `a` stays active. **Fixed.**                                          |
| **R3-B1 JSON**: `use b --unknown add --json`                                 | rc 1. `backups: {agents: …}`, `resolved: [first/add/a]`, `linked: [~/.claude/skills/first]`, warnings `lint` and `foreign` (typed `unknown-entry`), and `error` (clash). `first` is relinked as a symlink into the still-active `a`. **Fixed.** |
| Success JSON: `use b --unknown remove --json`                                | rc 0. `active_profile: b`, `backups`, `removed`, `installed`, `resolved` (2 removes with backup paths), `linked: []`, warning `foreign`.                                                                                                        |
| Refusal, no tty, no `--unknown` (text and JSON)                              | rc 1. The refusal comes before any takeover: no backups dir, `backups: {}`. The error offers `--unknown add\|remove`, and both clashing entries are warned. JSON has every key plus `error`.                                                    |
| Ctrl-C at the first pre-switch prompt                                        | rc 1. `Backed up agents folder …`, "interrupted; the switch to profile 'b' did not happen", and warnings for `first`, `lint`, `foreign`.                                                                                                        |
| `first: remove`, then Ctrl-C at `lint`                                       | rc 1. The `first` backup line, the agents folder backup, the interrupt notice, and warnings for `lint` and `foreign`.                                                                                                                           |
| Full switch `a`→`c`, takeover prompt: `foreign: add`, Ctrl-C at `zz`         | rc 0. Pre-switch removes, `Added …/foreign to profile 'a'` (outgoing, criterion 3), the agents backup, the switch summary, the interrupt notice, and a `zz` warning. `foreign` is in `profiles/a/skills` and `profile.yaml`.                    |
| First takeover (no active profile), clashing entries                         | Only `remove` is offered; `add` is re-asked. Ctrl-C reports the remove and both folder backups (claude-code, agents), then warns for the rest. rc 1.                                                                                            |
| First takeover, non-clashing entries: `gone: add`, `foreign: remove`, Ctrl-C | rc 0. `add` goes to the incoming `c` and is linked in both targets. The remove names its backup, both folder backups print, and `zz` is warned.                                                                                                 |
| Link error on the abort path: `first: add`, Ctrl-C, relink of `first` fails  | rc 1. `Added …/first to profile 'a'`, the agents folder backup (no longer dropped), `error: linking 'first' … did not complete`, the interrupt notice and warnings. `first` is in `profiles/a/skills`, so nothing is lost.                      |
| Link error on the failed-choice path, JSON (`--unknown add`, `first` fails)  | rc 1. `backups`, `resolved: [first]`, `linked: []`, warnings `lint` and `foreign`. `error` holds both the clash and the link failure.                                                                                                           |
| Link error inside `switch.use` (`--unknown remove`, `lint` install fails)    | rc 1. Both removes with backups, the agents backup, "did not complete … No profile is active …" and the `foreign` warning. The JSON is equivalent.                                                                                              |
| Link error inside `switch.use` after adds to the outgoing `a`                | rc 1. Both `Added … to profile 'a'` lines and the agents backup are printed. `link_added` skips the adds because no profile is active. Both skills are in `profiles/a/skills`.                                                                  |

### Leftover safety (`_clean_leftovers`, hard-kill states)

Setup: profile `a` (`tdd`, `other`) active as copies. The installed `tdd` is
hand-edited, so `adopt --add tdd` overwrites the profile copy and runs the
leftover sweep. Each leftover was planted in `profiles/a/skills` beforehand.

| Planted state                                                                     | Result                                                                                                                                                     |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Redundant `.other.respec-old`, identical to `backups/<old>/profiles/a/other`      | Deleted (held in the backup run). `other` live is untouched.                                                                                               |
| Redundant `.other.respec-new`, identical to the live `other`                      | Deleted.                                                                                                                                                   |
| **Only copy**: `.other.respec-old` "ONLY", live `other` differs, no backup        | **Kept.** Reported in text (`left … in place: … may hold the only copy`) and in JSON `leftovers`.                                                          |
| **Live missing**: `other` moved to `.other.respec-old`                            | **Restored** to `other` with its content ("ONLY").                                                                                                         |
| Live missing, both `.other.respec-old` and `.other.respec-new` ("NEW")            | `respec-old` is restored to `other`. `respec-new` is kept and reported. Nothing is lost.                                                                   |
| The skill being added has its own unique leftover (`.tdd.respec-old` "ONLY")      | Refused before any change ("move it out of the way first. Nothing was changed."). The profile copy, the leftover and the installed edit are all unchanged. |
| Kill between the two renames of the skill being added (`tdd` → `.tdd.respec-old`) | `.tdd.respec-old` is restored first, then the overwrite backs it up and proceeds. The backup holds the previous copy.                                      |

The digest ignores only `.DS_Store`, so a "same content" verdict cannot hide
any other dotfile difference.

## Fix-5 regressions (no regression)

- **Fix-5 B1** (refused `adopt --add` into a conflicted active profile): the
  active `work` has `layers.design-principles.skills: [a, b]` and a hand
  comment. `adopt --add foreign`, `--add foreign --json` and `--all add` each
  exit 1 with "cannot adopt into profile 'work'". Each time the snapshot of the
  home and the respec home is unchanged. The JSON has `resolved: []`, `error`
  and a typed `layer-conflict` warning. `use work` also refuses and changes
  nothing.
- **Fix-5 B3** (relink fails part way, `~/.agents/skills` set to `chmod 555`):
  `adopt --add foreign` (nested `sub/x.txt`) reports "did not complete … The
  skills added in this run were taken back out." The home snapshot is
  byte-identical (`foreign` is back as a real folder). `profile.yaml` is
  byte-identical, and `state.json` has no record.

## `use --json` key rename (`unknown` → `resolved`)

- `use` now matches adopt's success JSON (`resolved`, `linked`) and the shared
  `_fail_after` failure JSON (`resolved`, `error`). In adopt, `unknown` still
  means entries left unresolved, so the rename removes a clash of meaning.
- README line 81 documents `backups`, `resolved`, `linked`, `warnings` and
  `error`, which matches the observed output.
- Remaining inconsistency (pre-existing, outside this diff): see N2.

## Non-blocking findings

- **N1: a failed `use --json` says `active_profile: null` when a profile is
  still active.** `src/respec/cli.py` `_SwitchRun.finish` sets
  `active_profile`/`previous_profile` from `self.result`, which is `None` on
  every failure. In R3-B1 JSON, `a` stays active (`state.json`, `status`), but
  the JSON says `"active_profile": null`. Impact: a JSON consumer may conclude
  that no profile is active. Consider reading the active profile from state on
  failure, or leaving the key out.
- **N2: the restore JSON still uses `unknown` for resolutions.** In
  `src/respec/cli.py` `restore` (about line 1182), the success JSON has
  `"unknown": [resolutions]`, but its failure JSON (`_fail_after`) uses
  `resolved`, and adopt uses `unknown` for unresolved entries. This predates
  this diff (unchanged since `493d8e8`).
- **N3: text order after a takeover prompt.** On success, takeover
  resolutions print before `Backed up <target> folder …` and before
  `Switched to profile …`, although they happened after both. Cosmetic.
- **N4: duplicate error on a state-read failure.** `_SwitchRun.backups()` is
  called from `ask_about_takeover` and again from `finish`. If `load_state`
  fails, the same error is appended twice. Edge case only.
- **N5: a restored `.X.respec-old` is not checked against `profile.yaml`.** In
  `adopt._clean_leftovers`, if `X` was later removed from the profile, moving
  the leftover back creates an unlisted folder `X`. No data is lost; it needs a
  hard kill.
- **N6: doubled punctuation and a README line break.**
  - `LinkFailed` appends `.` to the OS error, which can end in `.` or a quote,
    so messages read like `…(forced).`.
  - The README reflow leaves `` `respec adopt` `` alone on its own line
    (about line 88). Prettier accepts it.
- **N7: the TUI feedback area is still capped at 6 lines** (the implementer's
  note). The CLI and `status` remain complete.

## Scope

`777ca83..4b79c93` touches `adopt.py`, `cli.py`, `switch.py`, `tui.py`, the
README and tests. All of it maps to R3-B1, the leftover safety item, and N1,
N2, N4 and N5 from review 3. There is no unrelated formatting churn. Spec
decision 5's "keep unmanaged" is overridden by the engineer's ledger decision
(not flagged).
