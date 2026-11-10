# t010 fresh review 2

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t010`
- Diff: `60224c7af58897549aac1253b7a49996833c1733..db313f04a834acdf84af2b8b9c69f3f87c842b9a` (6583406 plus fix commit db313f0)
- Scope: ticket 010, spec decision 13, follow-up on `t010-review-1.md` (B1, N1, N2, N3)

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking: 0

## Gates rerun (fresh)

| Gate                                                      | Result                                       |
| --------------------------------------------------------- | -------------------------------------------- |
| `uv run pytest -q` (db313f0)                              | `128 passed in 9.53s`                        |
| `uv run black --check .`                                  | `23 files would be left unchanged.`          |
| `npx prettier --check README.md`                          | `All matched files use Prettier code style!` |
| `uv lock --check`                                         | `Resolved 28 packages in 12ms`               |
| Scratch merge of db313f0 onto 77d592c, `uv run pytest -q` | `132 passed in 12.20s` (clean auto-merge)    |

## (a) B1 is fixed, reproduced with the real binary

The binary was `.venv/bin/respec` with temp `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`, run under a 15 s timeout. The one-sided cases used `script -q /dev/null` to provide a pty.

| Case                                     | Bare `respec`                                           | `respec tui`                                        |
| ---------------------------------------- | ------------------------------------------------------- | --------------------------------------------------- |
| stdin and stdout both non-TTY            | usage, rc 0, 0.19 s                                     | `error: the TUI needs a terminal ...`, rc 1, 0.11 s |
| stdin non-TTY only (`< /dev/null`)       | usage, rc 0, 0.16 s                                     | the same error, rc 1, 0.13 s                        |
| stdout non-TTY only (`\| cat`, `> file`) | usage, rc 0, 0.15 s and 0.17 s                          | the same error on stderr, rc 1, 0.13 s              |
| both TTY (positive control)              | TUI opens and runs (timed out, 30 KB of Textual output) | n/a                                                 |

`cli.py` `main()` checks the existing `_interactive()` (stdin and stdout are both TTYs) and prints `ctx.get_help()` when it is false. `_open_tui` refuses with exit 1 before it imports or builds the app. The new tests run the real CLI in a subprocess with `stdin=DEVNULL`, piped output and `timeout=20`, without stubbing `RespecApp.run`, so they are observable tests. The opens-the-TUI test now patches `_interactive` to true and covers only the terminal path.

## (b) N1: fixed, and the UX nit is acceptable

`tui.py` `activate(name, choices)`: the handler raises `switch.UnknownEntries` before `adopt.resolve` runs if any entry has no choice. `switch.use` calls `on_unknown` before `_preflight` and before any mutation (`switch.py` around lines 250-259), so nothing changes on disk. The `except switch.UnknownEntries` branch comes before `except RespecError`, which is required because `UnknownEntries` subclasses `SwitchBlocked`. It reopens the dialog with the full current list and the note "The unknown entries changed; nothing was done yet." `test_entry_appearing_after_the_dialog_opened_blocks_the_switch` checks this through the dialog paths, `status --json` (still alpha) and the untouched files.

The dialog reopens without the earlier choices preselected. That is acceptable: the race is rare, the state is safe (nothing was resolved), and the user is told why they are asked again. Prefilling the earlier choices would be a nice later touch, but it does not block.

## (c) N2: fixed

`_failed(error, resolved)` lists each resolution in the CLI's wording (`_resolution_text`) before the error line. `#feedback` now uses `height: auto; max-height: 6`. `test_failed_switch_after_choices_reports_what_was_resolved` makes the switch fail after a backup choice. It checks for "Backed up ... stray" plus the error in the feedback, checks that the active profile is unchanged, and checks that `stray` is gone. The feedback block holds at most 6 lines, so a very long list of resolutions would be cut off. This does not block, because the backups also appear in status and in the backups folder.

## (d) N3: fixed

`pyproject.toml` now has `textual>=8.2,<9`. `uv.lock` still pins textual 8.2.8, and `uv lock --check` passes.

## (e) Thin layer, and errors are shown rather than crashing

The fix adds no core logic. `activate` still delegates to `switch.use`, with `adopt.resolve` in the handler, which mirrors the CLI `use`. `_resolution_text` copies the CLI's message strings. That is presentation, not duplicated logic, but if the CLI wording changes the two can drift (non-blocking). `RespecError` from the first switch, the retry and the post-choice failure all go to `_failed` and the feedback line. None of them escape the app.

## Interaction with fix-1 (77d592c)

- The merge is clean, and the merged suite passes (132).
- After fix-1, copy-mode records carry a digest, and `unknown.is_managed` returns false for an edited or replaced copy. That entry then reaches the TUI as `Unknown(replaced=True)`. The adopt dialog (`tui.py` around line 273) labels it "…, replaced an item respec installed", and the status panel (around line 189) says "replaced a managed item". For a copy that was edited in place, "replaced" is slightly misleading. The wording comes from the core flag and matches the CLI message in `switch.py`, so it is consistent, not a TUI bug. Non-blocking: consider "changed or replaced" in both the CLI and the TUI.
- Side effect: a copy-mode record written before fix-1 has no digest, so `is_managed` returns false and the entry shows in the TUI as a replaced unknown on the next switch. The choices (add, back up, keep) are all safe. This is fix-1 behaviour, not t010 behaviour.

## Non-blocking findings

- NB1 `tui.py` `_ask_then_activate`: earlier choices are not carried into the reopened dialog (see b).
- NB2 `tui.py` CSS `#feedback max-height: 6`: a long list of resolutions plus the error can be cut off.
- NB3 The "replaced" wording for edited copies after fix-1 (see above). It comes from the core and the CLI.

## Scope

The fix commit touches only `cli.py`, `tui.py`, `pyproject.toml`, `uv.lock` and `tests/test_tui.py`. The README is unchanged since 6583406. There are no unrelated changes. Acceptance criteria 1-5 remain met.
