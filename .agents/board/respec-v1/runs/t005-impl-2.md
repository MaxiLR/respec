# t005 impl 2: rebase onto eeca3cb

- Status: DONE
- Branch: `codex/respec-v1-t005` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t005`)
- New base: `eeca3cb13e94608ea86451782c87a96f32810adb` (contains ticket 010, the TUI)
- Previous head: `139fe85`
- New head: `02458e6` (one commit on top of the base; same scope as impl 1)

## Conflict resolutions

- `README.md` was the only textual conflict. I kept both sides: the
  `respec restore` paragraph stays in the usage section, after the
  unknown-entries paragraph, and is followed by the new `### TUI` section
  unchanged.
- `src/respec/cli.py` merged without conflicts. The TUI callback and the `tui`
  command from 010 are intact. Restore adds one import line
  (`from respec import restore as restore_backups`) and appends the `restore`
  command at the end of the file.
- Renamed helpers: `src/respec/tui.py` does not call `new_backup_run`,
  `utc_now`, `remove_installed`, or their old private names. A search of
  `src` and `tests` for `_new_backup_run`, `_utc_now` and `switch._remove`
  finds nothing, so no caller still uses an old name.
- `pyproject.toml` and `uv.lock` are untouched by this ticket. They come from
  the base, which added textual.

## Verification

- `uv sync --frozen`: installed textual==8.2.8 from the lock
- `uv lock --check`: Resolved 28 packages
- `uv run pytest -q`: 149 passed (the base suite plus 17 restore tests)
- `uv run black --check src tests`: 25 files would be left unchanged
- `npx prettier@3 --check README.md`: all files use Prettier code style

The acceptance criteria evidence and concerns from
`runs/t005-impl-1.md` still apply unchanged.
