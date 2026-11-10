# fix-6 review 3: unknown-entry model v2, round-2 fix

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Diff: `493d8e8..777ca83` (focus `43d49d2..777ca83`)
- Verdicts: spec-compliance **FAIL**, code-quality **PASS**, tests-rerun
  **PASS**
- Blocking findings: 1 (R3-B1), a reporting gap under criterion 7. I found no
  data loss and no regression of the fix-5 safety scenarios. Review-2 B1 and B2
  are fixed.

## Gates rerun (fresh, at `777ca83`)

| Gate                                                  | Result                                       |
| ----------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                    | ok                                           |
| `uv lock --check`                                     | `Resolved 28 packages`                       |
| `uv run pytest -q`                                    | `336 passed in 53.36s`                       |
| `uv run black --check .`                              | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md`                    | `All matched files use Prettier code style!` |
| `uvx ruff check src --select F`                       | `All checks passed!`                         |
| `grep -ci item` over `--help` of 12 commands          | 0                                            |
| Red check: the new tests on `git archive 43d49d2 src` | all 10 new or updated tests fail             |

For the red check, `respec.__file__` pointed at the archive. The new tests are
behavioral (disk, state, stdout/stderr); none asserts on source text.

## Real-CLI scenarios

Each scenario ran in a temp home under the scratch directory, with `HOME`,
`RESPEC_HOME` and `RESPEC_USER_HOME` set. TTY runs used a `pty` harness that
sends a real Ctrl-C (`\x03`, SIGINT). Forced failures used a wrapper that
monkeypatches before `respec.cli.app()`. Setup unless noted: `a` active on
`claude-code` with `tdd`; `c` on `claude-code` + `agents` with `first`,
`second`; hand-made `first` and `second` in `~/.claude/skills`; a hand-made
`foreign` in a not-yet-owned `~/.agents/skills`.

| Scenario                                                                                            | Result                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1: Ctrl-C at the first `use c` prompt                                                              | rc 1. Prints `Backed up agents folder to …/agents`, "interrupted; the switch to profile 'c' did not happen", and warnings for `first`, `second`, `foreign`. `a` stays active. **PASS**                                                                                |
| B1: `first: remove`, Ctrl-C at `second`                                                             | rc 1. `Backed up …/first to …/backups/<run>-2/claude-code/first and removed it` (backup holds `first`), the agents folder backup, and warnings. **PASS**                                                                                                              |
| B1: `first: add`, Ctrl-C at `second`                                                                | rc 1. `Added …/first to profile 'a'`, `linked …/first`. `status`: `first` is a managed symlink in the still-active `a`. **PASS**                                                                                                                                      |
| B1: overwrite during `use` (copy mode, edited `tdd` and `x`, switch to `b`): `tdd: add`, Ctrl-C     | rc 1. `Replaced profile 'a''s copy of 'tdd' … (its previous copy is backed up at …/profiles/a/tdd)`, relinked as a copy. Profile holds the edit; backup holds the original; `x` stays and warns. **PASS**                                                             |
| Takeover prompt: Ctrl-C at the first takeover prompt after a full switch                            | rc 0. Earlier resolutions, the folder backup and the switch summary print, then "interrupted; the remaining entries stay as they are" and a warning. **PASS**                                                                                                         |
| First takeover (no active profile), TTY: `gone: add`, `pre: remove`, Ctrl-C at `zz`                 | rc 0. `add` goes to the incoming `a` and is linked; `pre` is backed up to a separate run; `zz` warns. **PASS**                                                                                                                                                        |
| First takeover, non-TTY `--json`                                                                    | rc 0. Folder backup in `backups`; `pre` left, with a `type: unknown-entry` warning. **PASS**                                                                                                                                                                          |
| B2: `adopt --add tdd` of an edited copy (copy mode; also a link replaced by a folder)               | Text names the replacement and the backup of the previous copy; profile holds the edit; no `.respec-*` leftovers. `.DS_Store` alone does not mark a copy edited. **PASS**                                                                                             |
| New abort relink step with a forced link failure (`_install` raises `OSError` inside `link_skills`) | rc 1. Error is printed and the `Replaced …` line with its backup prints. No data loss: profile holds the edit, original in a backup. The managed `tdd` copy is gone from the folder (it was respec's own copy). The agents folder backup line is **missing** (R3-B1). |
| fix-5 B1: conflicted `work` (hand comment), `adopt --add foreign`, `adopt --all add --json`         | rc 1, `cannot adopt into profile 'work'`. Tree, `profile.yaml` bytes and `state.json` bytes identical. JSON: `resolved: []`, `error`, `layer-conflict` warning. `adopt --remove foreign` then backs it up. **PASS**                                                   |
| fix-5 B3: `~/.agents/skills` at `chmod 555`, `adopt --add foreign` (nested)                         | rc 1, "taken back out". Tree and yaml identical. **PASS**                                                                                                                                                                                                             |
| Overwriting add with `link_skills` failing (`OSError` in `_install`)                                | rc 1, "taken back out". Tree and `state.json` identical, profile `s1` original. **PASS**                                                                                                                                                                              |
| Handler failure: `first: remove`, then `lint: add` clashes with `a`'s disabled `lint`               | rc 1. Removal and clash error print. The `agents` folder taken over in this run (backup `…/agents`, now owned) is **not reported**, and no unknown-entry warnings print (R3-B1).                                                                                      |

## Blocking findings

### R3-B1: a folder taken over in a failed `use` is backed up silently

- **Location**:
  - `src/respec/cli.py` `use()`, the `except switch.UnknownEntries` and
    `except RespecError` branches, which call `_fail_after(resolutions, …)`
    only;
  - `src/respec/cli.py` `_interrupted_switch()`: `state = None` in the
    `except RespecError` branch, which also discards the takeover backups.
- **Cause**: fix-6 moved `_take_over` before the `on_unknown` handler in
  `switch.use` (at `493d8e8` it ran after the handler). A failure raised by the
  handler, or by the re-check after it, now leaves a new folder owned and
  backed up. Only the abort path reports that, by diffing `state.owned`.
- **Failing scenarios (reproduced, real CLI on a pty)**:
  - `a` active; `b` on `claude-code` + `agents` with `first`, `lint`; `a` has
    `lint` disabled; hand-made `first`, `lint` in `~/.claude/skills` and
    `foreign` in `~/.agents/skills`. `respec use b`, answer `first: remove`,
    `lint: add`. Output: the `first` backup line and the clash error. The
    `~/.agents/skills` folder was backed up to `backups/<run>/agents` and is
    now owned by respec. Nothing names that backup, and nothing warns about
    `foreign`. The next `use b` will not ask about `foreign` at takeover,
    because the folder is already owned.
  - Abort path with the relink failing (`_install` raising `OSError` inside
    `link_skills`): the `error: linking …` line prints, then the `Replaced …`
    line, but the `Backed up agents folder to …` line is dropped because
    `state` is reset to `None` though `load_state` already succeeded.
  - The `--json` failure output (`_fail_after`) also has only `resolved` and
    `error`: no takeover `backups` and no `warnings`.
- **Impact**: criterion 7 ("every completed resolution is always reported with
  backup paths, on every exit path including aborts and partial failures") and
  criterion 4 (first takeover asks or backs up and warns). No data is lost: the
  backup exists and `state.owned` records it. But the user is not told their
  folder was backed up and taken over. Review 2 named this case in its B1 ("If
  the switch also took over a folder first, that takeover backup goes
  unreported too"); round 2 fixed it for the Ctrl-C path only.
- **Fix direction**: compute `owned_before` once and report new `state.owned`
  backups (and `_warn_unresolved`) in `_fail_after` for `use`, in text and in
  JSON (`backups`, `warnings`). In `_interrupted_switch`, load the state in its
  own `try` so a link error does not drop the backup lines. Add a test that
  fails the handler after a takeover and asserts the backup path is printed,
  and one abort test that includes a takeover folder.

## Abort relink step (criterion check)

`_interrupted_switch` calls `adopt_entries.link_added`, which links only adds
made to the still-active outgoing profile, into folders respec already owns,
using the outgoing profile's plan. It never touches unknown entries (they are
reported as `blocked`). On a mid-way `OSError`, `link_skills` saves the state
after the earlier links and raises. Effects:

- No user data can be lost: the added content is already in the profile, and a
  replaced profile copy is already in a backup run before the overwrite.
- It can partly apply: earlier skills are linked, and a managed copy being
  reinstalled is removed first, so it can be left absent (respec's own copy,
  reinstalled on the next switch or refresh). The links that did succeed are
  not printed (`linked` stays `[]`). See N2.

## Non-blocking findings

- **N1: wording.** `Replaced profile 'a''s copy of 'tdd'` reads oddly because
  of `!r` quoting. Consider `Replaced the copy of 'tdd' in profile 'a' with …`.
- **N2: partial relink on abort is under-reported.** When `link_skills` fails
  after linking some skills, those links are not listed, and a managed copy
  that was removed for reinstall stays absent with no note. Nothing is lost.
- **N3: `_clean_leftovers` sweeps other skills' leftovers.** In
  `adopt._overwrite`, recovery of an interrupted rename (`.<name>.respec-old`
  back to `<name>`) is done only for the skill being overwritten. The sweep then
  deletes every `.*.respec-old` in the profile's `skills/`. If another skill
  `X` was left between its two renames (hard kill), its profile folder is gone
  and `.X.respec-old` is deleted. Its content survives only in the earlier
  backup run, while `profile.yaml` still lists `X`. Recover every
  `.X.respec-old` whose `X` is missing before sweeping. Requires a hard kill;
  not reachable through normal errors.
- **N4: handler-failure adds are not relinked.** On the `RespecError` path of
  `use` (not the abort path), adds made to the still-active outgoing profile
  are reported but not linked, unlike the abort path. Review 2 judged this
  cosmetic; it is now inconsistent between the two exit paths.
- **N5: test gaps.** No test covers an abort or a handler failure after a
  folder takeover in the same `use`, and none covers a relink failure in the
  abort path.
- **N6: TUI feedback cap** (implementer's own note): the 6-line feedback area
  can cut off a long list of resolutions. The CLI and `status` remain complete.

## Scope

`43d49d2..777ca83` touches `adopt.py`, `cli.py`, `switch.py`, `tui.py`, the
README and tests, all tied to review-2 B1, B2, N1, N2, N3 and N5. No unrelated
formatting churn. `spec.md` decision 5 is stale, but the engineer's decision
overrides it (not flagged).
