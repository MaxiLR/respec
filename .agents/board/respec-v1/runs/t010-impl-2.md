# t010 implementation run 2 (fix round 1)

- Branch: `codex/respec-v1-t010` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t010`)
- Base: `60224c7af58897549aac1253b7a49996833c1733`; previous head `6583406`; no rebase
- Head: `db313f0`
- Review addressed: `t010-review-1.md` (B1, N1, N2, N3)
- Status: DONE

## Changes

| Finding | Fix                                                                                                                                                                                                                                                                                                                                   |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1      | `src/respec/cli.py`: the no-command callback checks the existing `_interactive()`. Without a TTY it prints `ctx.get_help()` and exits 0. `_open_tui` (used by `respec tui` and the callback) fails without a TTY: it prints `error: the TUI needs a terminal ...` to stderr and exits 1. The app is never constructed in either case. |
| N1      | `src/respec/tui.py`: `activate(name, choices)` passes a handler that raises `switch.UnknownEntries` before resolving anything when any entry lacks a choice. The dialog then opens again with the full current list and a note that nothing was done yet. `_use_with_choices` is merged into `activate`.                              |
| N2      | `_failed(error, resolved)` lists each resolution in the CLI's wording ("Backed up X to Y and removed it", ...) before the error. The feedback line is now `height: auto; max-height: 6`.                                                                                                                                              |
| N3      | `pyproject.toml`: `textual>=8.2,<9`. `uv lock` was rerun and `uv lock --check` is consistent (still 8.2.8).                                                                                                                                                                                                                           |

## Tests (tdd, red first)

New tests in `tests/test_tui.py`. All four failed before the fix:

| Test                                                             | Red reason before fix                                      |
| ---------------------------------------------------------------- | ---------------------------------------------------------- |
| `test_bare_respec_without_terminal_prints_help_and_exits`        | `subprocess.TimeoutExpired` after 20s (real non-TTY hang)  |
| `test_respec_tui_without_terminal_fails_with_a_clear_error`      | `subprocess.TimeoutExpired` after 20s                      |
| `test_entry_appearing_after_the_dialog_opened_blocks_the_switch` | the switch went ahead without asking about the late entry  |
| `test_failed_switch_after_choices_reports_what_was_resolved`     | the feedback held only the error, with no "Backed up" line |

The non-TTY tests run the real CLI in a subprocess (`sys.executable -c "...app()"`, stdin `DEVNULL`, piped stdout/stderr, temp homes inherited from the autouse fixture). They do not stub `RespecApp.run`. The existing opens-the-TUI test now patches `cli._interactive` to True, so it covers the terminal path only.

## Acceptance criteria

These are unchanged from run 1: 5/5 met. The ticket 010 criteria evidence in `t010-impl-1.md` still applies, and the 14 original TUI tests still pass.

## Verification (fresh)

- `uv run pytest -q` -> `128 passed in 9.98s`
- `uv run black --check .` -> `23 files would be left unchanged.`
- `npx prettier --check README.md` -> `All matched files use Prettier code style!`
- `uv lock --check` -> `Resolved 28 packages in 3ms`
- Manual check with the installed `respec` and stdin `/dev/null`, output piped. Bare `respec` printed the usage. `respec tui` printed the error and exited 1. Both together took 0.55s.

## Concerns

- On a refused retry (N1), the dialog opens again with no earlier choices preselected. The user re-picks every entry.
