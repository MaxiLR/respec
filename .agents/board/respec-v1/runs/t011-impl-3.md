# t011 implementation run 3 (fix round 1, part B)

- Branch: `codex/respec-v1-t011` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t011`)
- New base: `e417ce87a36d965d3385c903e37b4153cd6f3791` (feature tip after the ticket 009 merge). Old base: `b8d1aee`.
- Rebased commits: `3b62e95` -> `fa23d2a`, `535e735` -> `16bfcb0`
- Head: `e05615e`
- Status: DONE

## Rebase and conflict resolutions

- `fa23d2a` (TUI editing and Sync) applied cleanly.
- `16bfcb0` (part A) had one conflict, in `tests/test_sources.py`, where both sides appended tests at the end of the file. I kept both:
  - 009's `test_git_add_of_a_skill_named_like_a_shipped_skill_is_refused` and `test_profile_install_with_a_skill_named_like_a_shipped_skill_is_refused`;
  - part A's `silent_server` fixture and the timeout, invalid-timeout and cancel tests.
- `cli.py`, `items.py` and `sources.py` merged with no conflict.
- The full suite passed after the rebase, before any new change: 427 passed.

## Changes

| Item                  | Change                                                                                                                                                                                                                                                                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1                    | `switch.plan(respec_home, user_home, profile)` is a public seam over `_plan_all`, the plan `use` installs (profile, global and shipped skills). `sync._link_problems` builds its expected set from it, so the private `_plan` is no longer used and Sync uses the same plan as `use`.                                                         |
| int-e417ce8 finding 1 | `AdoptDialog` and Sync now call `adopt.choices(profile, entry, respec_home)`, as the CLI prompt does. An entry named like a shipped or global skill is offered only "Back up and remove", in the `a` dialog, the switch and takeover dialogs, and Sync. After the removal, respec links its own skill again (009's `relink_lasting`).         |
| Optional: marking     | The status panel adds `shipped` or `global` (accent) after the mode of those skills. The profile editor shows an "Also installed whenever a profile is active" group that lists shipped skills ("in every target") and global skills ("in this profile's targets"). An unreadable `config.yaml` adds no marks; Sync and the switch report it. |
| README                | One sentence on the markers and on Sync's expectations for these skills.                                                                                                                                                                                                                                                                      |

## TDD (red first; all in `tests/test_tui_sync.py`, using the `shipped` marker and a global skill in `config.yaml`)

| Test                                                                                   | Red reason before the fix                                                                   |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `test_clean_use_with_shipped_and_global_skills_is_in_sync` (core `sync.check` and TUI) | `report.clean` was False: shipped and global links were "no longer enabled"                 |
| `test_reapply_puts_back_a_removed_shipped_or_global_link[respec, gnotes]`              | the missing link was hidden behind false positives, and Re-apply never got to "All in sync" |
| `test_global_skill_listed_by_hand_but_not_linked_is_found`                             | the not-linked global skill was not detected                                                |
| `test_entry_named_like_a_shipped_or_global_skill_can_only_be_removed[respec, gnotes]`  | `#sync-unknown-0-add` and `#unknown-0-add` were offered                                     |
| `test_shipped_and_global_skills_are_marked_in_the_tui`                                 | `'shipped' in '● respec  symlink'` failed, confirmed against the previous `tui.py`          |

All pass after the change.

## Verification (fresh, at head)

- `uv sync --frozen` -> `Audited 27 packages`
- `uv lock --check` -> `Resolved 28 packages in 3ms`
- `uv run pytest -q` -> `434 passed in 101.76s`
- `uv run black --check .` -> `36 files would be left unchanged.`
- `npx prettier --check README.md` -> `All matched files use Prettier code style!`

## Concerns

- `switch.py` gained only the `plan` wrapper. The duplicate helpers that int-e417ce8 lists (finding 3) are unchanged and out of scope.
- If a global skill's own folder is gone, Sync shows the link problem and offers Re-apply, which `use` refuses with its own message. The "Disable" fix from part A covers only profile skills, because a global skill is removed from `config.yaml`, not disabled.
