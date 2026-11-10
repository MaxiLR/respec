# fix-6 review 2: unknown-entry model v2 (rebased onto fix-5)

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Diff: `493d8e8528670240bf66fedbded67b89741baf43..43d49d222663050b1b6a15efa3b83332bbbf73f4`
  (one commit; I verified `HEAD == 43d49d2` and a clean tree)
- Verdicts: spec-compliance **FAIL**, code-quality **PASS**, tests-rerun
  **PASS**
- Blocking findings: 2 (B1, B2). Both are reporting gaps under criterion 7. I
  found no data loss: every removed or overwritten entry has a complete copy in
  a profile or a backup run.

## Gates rerun (fresh, at head)

| Gate                                                     | Result                                       |
| -------------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                       | `Audited 27 packages`                        |
| `uv lock --check`                                        | `Resolved 28 packages`                       |
| `uv run pytest -q`                                       | `327 passed in 52.39s`                       |
| `uv run black --check .`                                 | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md`                       | `All matched files use Prettier code style!` |
| `uvx ruff check src --select F`                          | `All checks passed!`                         |
| `click` declared in `pyproject.toml`                     | `"click>=8.1"`                               |
| `grep -ci item` over `--help` of 15 commands             | 0                                            |
| Red check: head `tests/` on `git archive 493d8e8 src`    | 80 failed, 14 errors, 233 passed             |
| Red check: the 7 impl-3 tests named in the claim on base | all 7 fail                                   |

For the red check, I confirmed that `respec.__file__` pointed at the archive.
The tests are behavioral. They check disk, state, stdout/stderr and JSON, and
none of them assert on source text.

## Real-CLI scenarios

Each scenario ran in a temp home under the scratch directory, with `HOME`,
`RESPEC_HOME` and `RESPEC_USER_HOME` set. TTY runs used a `pty` harness. To
force failures, a driver applied a monkeypatch before `respec.cli.app()`.

| Scenario                                                                                                                                                   | Result                                                                                                                                                                                                                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| fix-5 B1: conflicted active profile (with a hand comment); `adopt --add foreign` and `adopt --all add --json`                                              | rc 1, `cannot adopt into profile 'work'`. The tree snapshot, `profile.yaml` bytes and `state.json` bytes are all identical. The JSON output has `resolved: []`, `error`, and `warnings` holding the `layer-conflict` entry. `adopt --remove foreign` afterwards backs up the nested `sub/x.txt`. **PASS** |
| fix-5 B3: profile on `claude-code` and `agents`, `~/.agents/skills` set to `chmod 555`, `adopt --add foreign` with a nested folder                         | rc 1, "linking ... did not complete ... The skills added in this run were taken back out." The tree snapshot is identical, including nested file hashes. The yaml is identical, and `state.json` has no record for `foreign`. **PASS: no partial apply, no loss**                                         |
| fix-6 review-1 B1: `s1` link replaced by an edited folder, plus a stray entry; `adopt --add stray`                                                         | rc 0. Output: "Added …/stray to profile 'a'" and "linked …/stray". It lists `s1` as left unknown. `status` shows `stray` as a symlink. `disable s2` is refused with `cannot refresh profile 'a'` and the profile is unchanged. **PASS**                                                                   |
| fix-6 review-1 B2: TTY `use b` (b takes over `agents`, which holds `aa` and `s1`); answers `aa: remove`, then `s1: add`, which clashes with a's `s1`       | rc 1. The switch summary (agents backup, "Removed 1 skills", "Switched to profile 'b'") prints first. Then the clash error, then "Backed up …/aa to …/backups/…-2/agents/aa and removed it", then a warning for `s1`. **PASS**                                                                            |
| B2 variant: Ctrl-C at the second takeover prompt                                                                                                           | rc 0. The switch summary, "warning: interrupted …", the `aa` backup line and a `zz` warning all print. **PASS**                                                                                                                                                                                           |
| **Ctrl-C at the second prompt of the switch's own handler** (entries in the way at b's install paths)                                                      | **FAIL (B1)**: output is only `Aborted.` with rc 1. `x1` was backed up and removed, or added to profile `a` and unlinked, and nothing reports either.                                                                                                                                                     |
| Overwriting add of an edited copy of the active profile's own `s1` (success, `--json`)                                                                     | The profile `s1` holds the edited content and is relinked. The previous copy is in `backups/<run>/profiles/a/s1`. JSON `replaced_copy` names it, and no `.respec-new`/`.respec-old` leftovers remain. The text output says only `Added … to profile 'a'` (**B2**).                                        |
| Overwriting add with a forced link failure: `switch.link_skills` raising `RespecError`, and `switch._install` raising `OSError`                            | Both: rc 1, "taken back out". The tree snapshot is identical: the profile `s1` is back to `ORIGINAL`, and the claude `s1` is the edited folder again. The state record is restored, and the previous-copy backup stays on disk. **PASS**                                                                  |
| First takeover, non-TTY (`pre` folder, `.DS_Store`, `.hidden`)                                                                                             | rc 0. The full-folder backup includes the dotfiles. `pre` is left in place, with a warning and an `adopt` hint. **PASS**                                                                                                                                                                                  |
| First takeover, TTY: answers `gone: add`, `pre: remove`                                                                                                    | `add` is offered and goes to `a`, the profile being activated. `gone` is linked, and `pre` is backed up to a separate run. `.DS_Store` is never asked about and stays. **PASS** (criteria 3 and 4)                                                                                                        |
| First `use`, entry at an install path, no active profile                                                                                                   | Non-TTY is blocked with an accurate lead. TTY offers only `remove`, then reports and switches. **PASS** (see N3 for the wording)                                                                                                                                                                          |
| Unrelated unknown `stray`; conflicted profile; `enable c`, `layer on/off output-style`, `layer repair … --keep b --json`, `layer off/on design-principles` | All rc 0. Each warns about `stray` on stderr. Repair JSON carries an `unknown-entry` warning, and `stray` is untouched. **PASS** (criterion 10)                                                                                                                                                           |
| Merged `warnings`: `layer on output-style --json` on a conflicted profile with `stray`                                                                     | `["layer-conflict", "unknown-entry"]`. Both carry `type` and `message`, as the README documents. **PASS** (criterion 8)                                                                                                                                                                                   |
| Copy mode, `.DS_Store` added inside an installed copy                                                                                                      | `status` still shows `s1 copy` (managed), and `disable s2` succeeds. A real edit then marks it replaced. **PASS** (criterion 6)                                                                                                                                                                           |

## Blocking findings

### B1: Ctrl-C at a `use` switch-handler prompt hides completed resolutions

- **Location**: `src/respec/cli.py` `use()`, in the `try: result = switch.use(...)`
  block. It catches only `switch.UnknownEntries` and `RespecError`. The handler
  calls `adopt_entries.resolve(..., done=resolutions)`, which prompts through
  `_prompt_choice`. `typer.Abort` / `click.exceptions.Abort` (`PROMPT_ABORTED`)
  is not caught there, unlike in `adopt`, `restore` and `_ask_about_takeover`.
- **Failing scenario (reproduced)**:
  - Profile `a` is active. Profile `b` has skills `x1` and `x2`, and
    `~/.claude/skills/x1` and `x2` are hand-made folders, so both are in the way.
  - On a TTY, run `respec use b`, answer `x1: remove`, then press Ctrl-C at the
    `x2` prompt.
  - Output: only `Aborted.`, with rc 1.
  - On disk, `x1` was backed up to `backups/<run>/claude-code/x1` and removed,
    and nothing names the backup.
  - With `x1: add` instead, `x1` is copied into the still-active profile `a`
    (enabled) and removed from `~/.claude/skills`. It is not linked again, so
    it disappears from the target folder with no message.
  - If the switch also took over a folder first, that takeover backup goes
    unreported too.
- **Impact**: This violates criterion 7 ("completed resolutions are always
  reported, including after … interrupted prompts, with backup paths"). It is
  the same class as review-1 B2, which was fixed only for the takeover prompt.
  No data is lost, but the user is told nothing was done.
- **Fix direction**:
  - Catch `PROMPT_ABORTED` around `switch.use`.
  - Report `resolutions` and any takeover backups. These are recorded in state:
    `switch.use` saves `owned` before calling the handler, so the CLI can
    re-read them, or the handler could record them.
  - Then fail with "interrupted; the switch did not happen".
  - Relink adds made into the still-active outgoing profile, or say they are
    unlinked until the next refresh.
  - Add a pty test, or a `CliRunner` test with a `decide` that raises
    `typer.Abort`.

### B2: the backup of the profile's previous copy is never shown in text output

- **Location**:
  - `src/respec/cli.py` `_report_resolution()`, which prints only
    `Added <path> to profile '<p>'`;
  - `src/respec/tui.py` `_resolution_text()`, which does the same;
  - `adopt.Resolution.replaced_copy`, which is filled by `_overwrite()`.
- **Failing scenario (reproduced)**:
  - Profile `a`'s `s1` link is replaced by an edited folder.
  - `respec adopt --add s1` prints `Added …/.claude/skills/s1 to profile 'a'`
    and `linked …`.
  - The profile's previous `s1` was overwritten and moved to
    `backups/<run>/profiles/a/s1`. Only the `--json` output names that path
    (`replaced_copy`).
  - The same happens through the `use` handler, the takeover prompt, `restore`
    and the TUI.
- **Impact**: Criteria 5 and 7 together require the replaced profile copy to be
  backed up and its backup path reported. The text says "Added" for what is an
  overwrite, so a user who wants the old version back has no pointer to it.
  This is the reporting gap left over from review-1 N4.
- **Fix direction**: When `replaced_copy` is set, print for example
  `Replaced profile 'a''s copy of s1 with <path> (previous copy backed up at
<replaced_copy>)`, in both the CLI and the TUI. Add an assertion to
  `test_overwriting_add_backs_up_the_profile_previous_copy`.

## Judgement: adds during `use` that are not rolled back on a later failure

**This is a partial apply that is reported, not data loss.** An add during `use`
can come from the handler (to the outgoing profile) or from the takeover prompt
(to the outgoing profile, or at first takeover to the profile being activated).
In both cases, `resolve()` deletes the original only after `add_local` or
`_overwrite` has completed the profile copy. The overwritten previous copy is
first saved to a backup run.

A later failure in the switch has three forms:

- an `OSError` during removal or install;
- a refusal by the re-check after `on_unknown`;
- a clash on the next entry.

None of these touches the profile copy. `_fail_after` prints every `done`
resolution, and `_ask_about_takeover` prints them before the error (verified in
the review-1 B2 rerun). The remaining effects are cosmetic:

- the entry now lives in the outgoing profile and is not linked until that
  profile is active again;
- after an `OSError` mid-switch, no profile is active, as the error says.

This matches how removals are treated: they are not rolled back either and are
reported with backups. Rolling back an add would need `_put_back` across a
half-done switch, which adds risk for no safety gain. I recommend accepting it
and documenting it in one README line ("a switch that fails part way keeps the
choices already made; they are listed"). The real exception is the interrupted
handler prompt, where nothing is reported: that is B1.

## fix-5 invariants (criterion 9)

- `adopt()` asks every choice before any change and calls
  `refuse_layer_conflicts(before, "adopt into")` when any choice is `add`.
  Verified byte-exact above.
- `_put_back` and `_undo_adds` delete a profile copy only after a verified
  restore. The new `replaced_copy` restore runs only on that verified branch.
  On an unverified branch, the edited content stays in the profile and the note
  names both copies.

## Non-blocking findings

- **N1: TUI success feedback gives counts only.** In `tui.py`,
  `_ask_about_takeover.chosen`, `action_adopt.chosen` and `_switched` show
  "Resolved N unknown entries" or "resolved N unknown", with no paths or backup
  locations. Failures do list them (`_failed`). The CLI is complete, apart
  from B2.
- **N2: misleading hint in the add-clash error.** At `items.add_local` (reached
  from `adopt._add`), an `add` whose name already exists in the target profile
  says
  `profile 'a' already has a skill 's1'; remove it first with 'respec remove s1 -p a'`.
  Following that hint deletes the profile's own skill. For unknown-entry
  resolution, a better hint is "choose remove (it is backed up first)".
- **N3: first-takeover wording and `--unknown`.**
  - With no profile active, a non-TTY block says "Resolve them with
    'respec adopt': add each to the active profile". There is no active
    profile, so only remove works.
  - `use a --unknown add` at first takeover is refused up front ("needs an
    active profile"). Yet on a terminal the takeover prompt would send `add` to
    `a`, and the README says `--unknown` "answers these too".
  - Both are consistent with "add during a switch goes to the outgoing
    profile", but the wording should say so.
- **N4: the board spec is stale.** `spec.md` lines 45 and 61 (decision 5) still
  list "keep unmanaged". Update the spec to the engineer's two-choice decision.
  The board is not part of this diff.
- **N5: `_overwrite` cleanup.** `shutil.rmtree(retired, ignore_errors=True)` can
  leave a hidden `.<name>.respec-old` in the profile's `skills/` on a cleanup
  error. This is harmless, because the next overwrite removes it first and the
  digest ignores nothing here. It is just untidy.
- **N6: tests.** No test covers an interrupted handler prompt in `use` (only
  `test_interrupted_takeover_prompt_reports_and_leaves_the_rest_unknown`), and
  no test checks the text output of an overwriting add. Both match B1 and B2.

## Scope

The diff stays within the fix-6 acceptance list. The changes:

- the two choices (`keep` is removed, and the legacy `unmanaged` record is
  pruned: `test_entries_once_kept_unmanaged_are_unknown_again_and_the_record_is_pruned`);
- `conflicts()` narrowing;
- `link_skills`;
- the `refresh` wording;
- the layer on/off relink;
- the merged `warnings`;
- dotfile handling;
- the `click` dependency and lock.

I found no unrelated formatting churn.
