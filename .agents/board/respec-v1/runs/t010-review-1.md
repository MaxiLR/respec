# t010 fresh review 1

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t010`
- Diff: `60224c7af58897549aac1253b7a49996833c1733..6583406fc058925216fbf62976222ce80360a07d`
- Scope: ticket 010, spec decision 13 and the command surface (`respec` with no args or `respec tui` opens the TUI)

## Verdicts

- spec-compliance: PASS (all five acceptance criteria are met; bare `respec` opening the TUI is what the spec asks for)
- code-quality: FAIL (one blocking robustness defect, see B1)
- tests-rerun: PASS

## Gates rerun (fresh)

| Gate                             | Result                                       |
| -------------------------------- | -------------------------------------------- |
| `uv run pytest -q`               | `124 passed in 8.03s`                        |
| `uv run black --check .`         | `23 files would be left unchanged.`          |
| `npx prettier --check README.md` | `All matched files use Prettier code style!` |
| `uv lock --check`                | `Resolved 28 packages` (lock is consistent)  |

## Blocking findings

### B1: bare `respec` and `respec tui` hang when stdout or stdin is not a terminal

- Location: `src/respec/cli.py` `main()` callback (`if ctx.invoked_subcommand is None: _open_tui(ctx.obj)`) and the `tui` command. Neither checks for a terminal before calling `RespecApp(...).run()`.
- Failing scenario: from a script, a pipe or CI, with temp homes:
  `subprocess.run(["uv","run","respec","--home",H], capture_output=True, input=b"", timeout=10)`
  and the same call with `tui`. Both hit `TIMEOUT after 10s` with 0 bytes on stdout. `respec --help` under the same conditions exits 0 in 0.17s. Reproduced with stdin set to `/dev/null` and stdout piped as well.
- Impact: any script, agent or CI step that runs bare `respec`, for example to print help as it did before this change, now blocks forever with nothing printed. This is the "must not hang" requirement from the review brief. The CLI already has `_interactive()` (`sys.stdin.isatty() and sys.stdout.isatty()`, `cli.py:217`) for this exact purpose, and the `use` prompt relies on it. A no-TTY run should not open the TUI. It should print help (or a clear error) and exit, ideally with a non-zero code for `respec tui`.
- Test gap: `test_respec_without_command_or_tui_opens_the_tui` monkeypatches `RespecApp.run`. Under `CliRunner` stdout is not a TTY, so the test asserts the hanging behaviour as correct. Add an observable test along these lines: with a non-TTY stream, `respec` exits promptly and prints usage. With TTY detection patched to true, the TUI opens.

## Non-blocking findings

### N1: dialog choices are keyed by path, so entries that appear later are left alone without notice

- Location: `src/respec/tui.py` `_use_with_choices`, where `lambda e: choices.get(e.path)` is passed to `adopt.resolve`.
- Scenario: the user opens the unknown-entry dialog and, before Apply, another unknown entry appears in an owned folder. `switch.use` calls the handler with the fresh list. The new entry gets `None`, is left in place, is not recorded as unmanaged, and the switch goes ahead. The CLI `use` always has a decision for every entry.
- Impact: low. The entry is untouched (no data loss) and still shows as unknown in status. Still, the switch completes without the user deciding about every entry. Either re-open the dialog for undecided entries or refuse (raise) on them.

### N2: partial resolutions are not reported when the retried switch fails

- Location: `src/respec/tui.py` `_use_with_choices`, `except RespecError: self._failed(error)`.
- Scenario: the handler resolves some entries (for example, backs up and removes one) and then `_preflight` raises `SwitchBlocked`. The CLI reports each resolution before the error (`cli.py` `use`). The TUI shows only the error, and `resolved` is discarded.
- Impact: the user is not told that an entry was already moved to a backup. On-disk safety is unaffected because the core handles the backup.

### N3: `textual>=8.2` has no upper bound

- Location: `pyproject.toml`.
- This matches the existing style (`pyyaml>=6.0`, `typer>=0.12`), and `uv.lock` pins 8.2.8 (adding `linkify-it-py`, `mdit-py-plugins`). The TUI uses private-ish styling hooks (`ListItem.-highlight`), so a future Textual 9 could break it. It is acceptable for an unpublished tool, but consider `<9` once it is distributed.

## Investigation points

- (a) Thin layer: confirmed. `tui.py` calls only `profiles.list_profile_names/load_profile`, `switch.status/use`, `adopt.resolve/find/adopt` and `load_state`. It contains no switching, detection, backup or rollback logic of its own. The first `switch.use` without a handler raises `UnknownEntries`, so the core does the blocking. The retry passes a handler with the same shape as the CLI's. Backups and rollback stay in `switch.use` and `adopt._backup`.
- (b) Bare `respec` opening the TUI matches the spec (command surface: "`respec` (no args) or `respec tui` opens the TUI"). The non-TTY case hangs, see B1.
- (c) Dependency: `uv lock --check` passes and the lock is consistent. Pinning is noted in N3.
- (d) Tests: 14 Pilot/CLI tests use the autouse `isolated_homes` fixture (temp `HOME`, `RESPEC_HOME`, `RESPEC_USER_HOME`, with real-home guards). Outcomes are checked independently through `respec status --json` and the filesystem: symlinks, backup contents, the added profile skill. They cover real mouse clicks (`pilot.click`), keyboard activation, cancel and the add/backup/keep choices. None are mirror tests. The gap is in the no-args test, see B1.
- (e) Errors: `SwitchBlocked`/`RespecError` from `use`, from the retry, from `adopt.find/adopt` and from `status` are caught and shown in the `#feedback` line, then the view refreshes. `test_failed_switch_reports_error_and_changes_nothing` confirms this. Raw `OSError` from `adopt._delete` would propagate, but the CLI has the same behaviour, so it is not specific to the TUI.

## Scope

The diff stays within the ticket: `tui.py`, a small change to the `cli.py` callback and a new command, the dependency, tests and a README section. No unrelated changes.
