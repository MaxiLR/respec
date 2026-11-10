# fix-6 impl 2: fix round 1 (review-1 findings)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Branch: `codex/respec-v1-fix-6`
- Base: `f629644`. This round goes from `56ed201` to `dcdf333`, in one commit. Not rebased, as instructed: fix-5 merges first.
- Status: DONE. Both blocking findings (B1, B2) are fixed, the orchestrator decision is applied, and the two small items are done.

## Changes

| Finding                                           | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1: adopt add blocked by an unrelated edited copy | New `switch.link_skills()` links only the named skills of the active profile, and only into owned folders. A destination with an unknown entry in the way goes to `blocked`, and other unknown entries are ignored. A managed link is left as it is, and a managed copy is reinstalled. `adopt.link_added()` now uses it, so it no longer re-applies the whole profile and the "cannot switch" message cannot appear. `adopt.adopt(..., done=)` keeps partial results. CLI `adopt` reports `done` on failure: text lines, or JSON `{"resolved": [...], "error": ...}` with exit 1. A Ctrl-C at the prompt reports what was done and warns.                                                                                                       |
| B2: takeover prompt failure hides the switch      | In CLI `use`, the takeover step now runs outside the switch's `try`. The switch summary (resolutions, folder backups, removed, switched) is always printed first. `_ask_about_takeover` collects choices with `done=` and reports each one with its backup path. A failed choice prints the error and exits 1. An interrupted prompt (typer or click `Abort`) warns "interrupted; the remaining entries stay as they are" and exits 0. Unresolved entries then get the usual stderr warning with the `respec adopt` hint. The new `_fail_after()` helper is shared by `use`, `adopt` and `restore`, and outputs valid JSON when `--json` is set. TUI: `_ask_about_takeover` and `action_adopt` pass `done=` and call `_failed(error, resolved)`. |
| Orchestrator decision: first-takeover add target  | New `adopt.takeover_profile(result)` returns `result.previous`, or the incoming profile when no profile was active. CLI and TUI both use it. Conflicts in the way before a switch still offer add only to the outgoing profile, and `--unknown add` with no active profile still fails up front.                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| N1: `--unknown` help                              | The help now says that on a terminal it also applies to entries already in a folder taken over for the first time. The README says this too, along with the first-takeover add target and the interrupt behaviour.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| N3: dead restore confirm                          | Removed. `--overwrite` is the only route. A prompt abort during restore is reported through `_fail_after`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| N7 (partial)                                      | The takeover filter is moved into `adopt.taken_over(respec_home, result)` and shared by the CLI and the TUI.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

## Regression tests (red first, against the `56ed201` src, then green)

Stashing `src` and running the new tests: 10 failed, all for the intended reasons. After the fix, all of them pass.

- B1:
  - `test_adopt_add_while_an_edited_copy_waits_reports_and_links_the_add`
  - `test_adopt_add_json_while_an_edited_copy_waits_lists_the_link`
  - `test_adopt_failing_part_way_reports_what_was_already_done[text|json]`
- B2:
  - `test_failed_takeover_choice_still_reports_the_switch_and_what_was_done`: checks the summary, the folder backup line and the removed entry's backup path, and that it exits 1.
  - `test_interrupted_takeover_prompt_reports_and_leaves_the_rest_unknown`: exit 0, warns, and points to `respec adopt`.
  - TUI: `test_failed_takeover_choice_in_the_tui_reports_what_was_resolved`
- First-takeover target:
  - `test_very_first_takeover_adds_to_the_profile_being_activated`: the entry is added to the incoming profile and linked.
  - `test_first_takeover_on_a_terminal_asks_about_existing_entries_right_away` is updated to offer `add to profile 'a'`.
  - TUI: `test_very_first_takeover_in_the_tui_adds_to_the_profile_being_activated`

## Verification (fresh, at `dcdf333`)

- `uv sync --frozen`: Audited 27 packages
- `uv lock --check`: Resolved 28 packages
- `uv run pytest -q`: 277 passed
- `uv run black --check .`: 28 files would be left unchanged
- `npx prettier@3 --check README.md`: All matched files use Prettier code style
- `uvx ruff check src --select F`: All checks passed

## Concerns and open items

- `cli.py` now imports `click` directly to catch `click.exceptions.Abort`, because `typer.prompt` raises `typer.Abort` while click's own prompt raises click's `Abort`. `click` is a transitive dependency of typer and is not declared in `pyproject.toml`.
- `link_skills` links only into owned folders. If an active profile lists a target that was never taken over, an add is not linked there until the next `use`. Normally every active target is owned.
- Not addressed (non-blocking): N2, an option to skip at the first-takeover prompt. It is now less pressing, because add is available at the very first takeover. Also not addressed: N4 (overwrite discards the old profile copy without a backup), N5 and N6.
- At the rebase onto fix-5, the shared JSON `warnings` field must be merged as the review describes. fix-5's `_print_json` spread would overwrite the unknown-entry warnings. The plan is to merge both lists in `_print_json`, each element carrying a `type` discriminator.
