# fix-6 impl 4: fix round 2 (review-2 findings)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Branch: `codex/respec-v1-fix-6`
- Base: `493d8e8`. This round adds one commit on top of `43d49d2`, giving head `777ca83`.
- Status: DONE. Not rebased, pushed or merged. `spec.md` was not edited.

## Changes

| Finding                                         | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1: abort at a switch-handler prompt            | `cli.use()` now catches `PROMPT_ABORTED` (typer or click `Abort`) around `switch.use` and calls `_interrupted_switch()`. In order, that function: ends the prompt line; links skills just added to the profile, which is still active; prints every applied resolution with its backup path; names the backups of folders that were taken over during the interrupted run (it compares `state.owned` before and after); warns `interrupted; the switch to profile '<p>' did not happen`; prints the usual unknown-entry warnings with the `respec adopt` hint; and exits 1. The TUI has no prompts: its dialog either cancels before any change or applies all choices, so no change was needed there. The takeover and `adopt` abort paths now also end the prompt line before reporting. |
| B2: overwrite not shown in text                 | New `Resolution.describe()` is the single wording used by both the CLI (`_report_resolution`) and the TUI (the TUI's `_resolution_text` is removed). For an overwrite it reads: `Replaced profile 'a''s copy of 'tdd' with <path> (its previous copy is backed up at <backup>)`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| N2: add-clash hint                              | `adopt._add` checks for a name clash itself before calling `add_local`. The error now reads `... already has a skill 'x'; choose remove instead ('respec adopt --remove x'): the entry is backed up first, and the profile's own copy is kept`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| N3: wording around `--unknown add` and takeover | When a switch is blocked and no profile is active, `UnknownEntries(can_add=False)` says that the entries can only be removed, each backed up first. The CLI hint then offers only `--unknown remove`. When no profile is active, `--unknown add` now explains that it always means the profile active now, and that a terminal without `--unknown` can add entries found at the first takeover to the profile being activated. The README states the same rule, plus the reviewer's suggested line that choices made before a failed or interrupted switch are kept and reported.                                                                                                                                                                                                          |
| N5: leftover `.respec-old`                      | `_clean_leftovers()` removes every `.*.respec-new` and `.*.respec-old` folder in the profile's `skills/` before and after an overwrite. If an earlier overwrite stopped between its two renames, the first rename is undone before the backup is taken. The profile's previous copy is always saved to a backup run before staging, so these leftovers never hold the only copy.                                                                                                                                                                                                                                                                                                                                                                                                           |
| N1: TUI counts only                             | New `_resolved_text()` makes the switch, takeover and `a` (adopt) success messages list `describe()` for each resolution, after the summary line.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

## Tests

The new tests were written first. Against the `43d49d2` src (stashed) all 9 failed, for the intended reasons: no "Backed up" line after the abort, only "Added", leftover folders still present, "respec remove" in the hint, the add wording, and count-only TUI messages. All are green at head.

- `test_adopt.py`:
  - `test_abort_at_a_second_switch_prompt_reports_a_removal_and_its_backup` (exit 1; reads the backup path from the output and checks its content; warns that the switch did not happen and names `second` with `respec adopt`)
  - `test_abort_at_a_second_switch_prompt_reports_and_links_an_add` (the add is reported and linked back into the still-active profile `a`)
  - `test_overwriting_add_says_the_previous_copy_was_replaced_and_where_it_went`
  - `test_overwrite_cleans_up_leftover_staging_folders`
  - `test_add_clash_points_to_remove_with_a_backup_not_respec_remove`
  - `test_block_without_an_active_profile_does_not_offer_add`
  - `test_unknown_add_without_an_active_profile_explains_the_takeover_case`
- `test_tui.py`:
  - `test_tui_names_what_it_resolved_and_where_backups_went`
  - `test_tui_says_an_overwriting_add_replaced_the_profile_copy`
- Updated: `test_switch_policy_add_without_an_active_profile_fails_before_any_change` now expects the new "no profile is active" wording.

The aborts are simulated with `CliRunner` input that ends at the second prompt. That makes `typer.prompt` raise `typer.Abort`, which is what Ctrl-C raises too.

## Verification (fresh, at `777ca83`)

- `uv sync --frozen`: Audited 27 packages
- `uv lock --check`: Resolved 28 packages
- `uv run pytest -q`: 336 passed
- `uv run black --check .`: 29 files would be left unchanged
- `npx prettier@3 --check README.md`: All matched files use Prettier code style
- `uvx ruff check src --select F`: All checks passed

## Concerns

- The TUI feedback area is capped at 6 lines (existing CSS), so a long list of resolutions is cut off there. The CLI and `respec status` still show everything.
- Following the review's judgement, adds made before a switch fails part way are kept and reported, not rolled back. The README now says so.
- The stale `spec.md` text (review-2 N4) was left for the orchestrator, as instructed.
