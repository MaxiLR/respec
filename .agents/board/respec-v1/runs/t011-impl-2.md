# t011 implementation run 2 (fix round 1, part A)

- Branch: `codex/respec-v1-t011` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t011`)
- Base: `b8d1aee`; previous head `3b62e95`; not rebased (as instructed)
- Head: `535e735`
- Review addressed: `t011-review-1.md`. Fixed: B2, N1, N2, N3, N4. B1 is deferred to after the 009 merge, as instructed; `sync.py` still calls `switch._plan`.
- Status: DONE (part A)

## Changes

| Finding | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B2      | `items.user_path(text)` expands `~` and refuses a NUL byte or an unknown `~user` with a `RespecError`. `items.add_local`, `respec add` (cli) and the editor's Add folder all use it. The editor, the dialogs and Sync catch `FAILURES = (RespecError, OSError, RuntimeError, ValueError)` around every core call and show the error, so the TUI keeps running.                                                                                                                                                                                                                                                                      |
|         | Audit of the other input fields: the git source and ref go through `parse_spec`/`check_value` (RespecError). The profile name goes through `validate_name`; an `OSError` from `create_profile` (for example read-only home) is now shown in the dialog. Sync and the editor take no free text.                                                                                                                                                                                                                                                                                                                                      |
| N1      | Core (`sources.py`): every git command has a time limit, `RESPEC_GIT_TIMEOUT` seconds (default 120). An invalid value is refused with an error. Remote commands also get `-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30`, and the batch ssh command adds `-o ConnectTimeout=15`. Git runs in its own process group, so a stop also kills `git-remote-http`/ssh, which would otherwise hold the pipes open. `cancel_on(event)` is a contextvar-scoped cancel that raises `GitCancelled`, and the existing rollback paths run. The fix-4 settings are kept: no prompts, BatchMode, closed stdin, allowed protocols, cleaned env. |
|         | TUI: Add from git and Check updates run in a Textual worker (`asyncio.to_thread`). While they run, the feedback shows "Fetching …" or "Checking …" with "Press Esc or Cancel to stop", a Cancel button appears, and editing and Sync are disabled. A failed fetch rolls the profile back, so a concurrent edit would be lost. Esc or Back cancels instead of leaving, and leaving the screen cancels as well.                                                                                                                                                                                                                       |
| N2      | `sync.LinkProblem.folder_gone` names the active profile's skill folder when that skill is enabled but its folder is gone. In that case Sync shows the folder, says to restore it or disable the skill, and offers "Disable &lt;skill&gt;" (`items.set_enabled`, with refresh and rollback) instead of a Re-apply that cannot work. A broken link whose profile copy exists, such as a link to an old profile path, is still fixed by Re-apply.                                                                                                                                                                                      |
| N3      | New `src/respec/messages.py` holds `source_label`, `short`, `skill_change`, `layer_change` and `sourced_change`. `cli.py` and `tui.py` both use it, and the CLI output is unchanged (its existing tests pass). The TUI repair log now matches the CLI: one `  disabled 'x'` line per skill.                                                                                                                                                                                                                                                                                                                                         |
| N4      | `e` right after launch: new tests show it opens the active profile, or the first profile when none is active. The code already behaved this way, so I could not reproduce the reviewer's case and changed nothing. The `create_profile` `OSError` is fixed (see B2). The Sync choice keyed by path and the missing remove/layer on-off controls are unchanged, as the review accepted them.                                                                                                                                                                                                                                         |

## TDD (red first)

| Test                                                                                                    | Red reason                                           |
| ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `test_add_folder_with_an_unusable_path_shows_the_error_and_keeps_running[~nosuchuser_zz/skill, NUL]`    | RuntimeError / ValueError crashed the app            |
| `test_items.py::test_add_with_a_home_that_cannot_be_found_fails_with_an_error`                          | CLI traceback (RuntimeError)                         |
| `test_new_profile_that_cannot_be_written_shows_the_error`                                               | PermissionError crashed the app                      |
| `test_sources.py::test_git_gives_up_on_a_silent_server_after_the_timeout`                               | hung (killed by a 25s `timeout`)                     |
| `test_sources.py::test_an_invalid_git_timeout_is_refused`                                               | env var ignored                                      |
| `test_sources.py::test_git_can_be_cancelled_and_nothing_is_added`                                       | no `cancel_on`                                       |
| `test_add_from_git_shows_progress_stays_responsive_and_can_be_cancelled`                                | event loop blocked (hang)                            |
| `test_escape_cancels_a_running_update_check`                                                            | event loop blocked (hang)                            |
| `test_tui_sync.py::test_broken_link_without_its_profile_folder_offers_disable`                          | no folder shown, no disable, only a failing Re-apply |
| `test_layer_conflict_is_listed_and_repaired_keeping_the_chosen_skill` (log text updated to CLI wording) | old joined wording                                   |
| `test_broken_link_to_an_old_profile_path_is_relinked`, `test_e_right_after_launch_*` (2)                | passed at once; kept as regression tests             |

One more bug appeared while going green. Cancelling or timing out first took about 30s, because `git-remote-http` held the pipes open. Killing the process group fixed it: the timeout test now takes 2.2s and cancel takes 0.6s.

## Verification (fresh, at head)

- `uv sync --frozen` -> `Audited 27 packages`
- `uv lock --check` -> `Resolved 28 packages in 3ms`
- `uv run pytest -q` -> `385 passed in 97.50s`
- `uv run black --check .` -> `33 files would be left unchanged.`
- `npx prettier --check README.md` -> `All matched files use Prettier code style!` (the README documents `RESPEC_GIT_TIMEOUT` and the TUI's Cancel)
- I ran the TUI test files twice more, with no flakes (37 passed each time).

## Concerns

- B1 is still open: `sync.py` uses the private `switch._plan`. It is to be replaced by a public `switch.plan` after 009 merges.
- `cli.py` is now edited (shared messages, `user_path`). 009 may touch `cli.py` too, so expect small textual merge conflicts at rebase.
- `RESPEC_GIT_TIMEOUT` applies to every git command, local ones included. The 120s default is generous for a large fetch over slow links; raise it through the env var if needed.
