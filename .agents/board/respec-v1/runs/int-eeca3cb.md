# Integration check: eeca3cb

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- Head: `eeca3cb13e94608ea86451782c87a96f32810adb` (matches expected)
- Change range: `77d592c..eeca3cb` (ticket 010 TUI merged onto fix-1)
- Merged so far: 001, 002, 006, 008, 004, fix-1, 010
- AGENTS.md: none in the repository
- Mode: read-only. The only file written is this report. Throwaway probes live
  outside the repo, in the session scratchpad.

## Gates

| Gate                            | Command                                                | Result                                                              |
| ------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------- |
| Environment                     | `uv sync --frozen`                                     | exit 0 (installed textual 8.2.8 and related packages from the lock) |
| Lockfile                        | `uv lock --check`                                      | exit 0, "Resolved 28 packages"                                      |
| Full suite                      | `uv run pytest`                                        | **132 passed** in 10.36s, no skips (test_tui.py: 18 passed)         |
| Black (88)                      | `uv run black --check src tests`                       | "23 files would be left unchanged"                                  |
| Prettier                        | `npx prettier@3 --check $(git ls-files '*.md')`        | "All matched files use Prettier code style!" (14 tracked .md files) |
| Pyflakes (extra, informational) | `uvx ruff@0.6.9 check --no-cache --select F src tests` | "All checks passed!"                                                |

## TUI against fix-1 semantics (copy-mode items)

Probe: a throwaway Pilot test file (not committed) reusing the repo's
`conftest.py` and `tests/test_tui.py` helpers. Profile `alpha` (claude-code,
`a1`) is activated with `os.symlink` patched to fail, so `a1` is installed as a
**copy** with a digest. Profile `beta` targets oh-my-pi. Run with
`uv run pytest -p no:cacheprovider <scratch>/inttests -q`.

| Scenario (edit = SKILL.md rewritten; replace = rmtree + new folder)                                                                                                                             | Result                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| edit / replace: status panel shows `▲ a1 unknown folder, replaced a managed item`, not as a managed `●` item                                                                                    | PASS                                                                                                                                                                                                                                                                 |
| edit / replace: activating beta opens AdoptDialog. Entry meta reads `folder in claude-code, replaced an item respec installed`. Escape cancels: active stays alpha and the content is unchanged | PASS                                                                                                                                                                                                                                                                 |
| edit / replace + Back up and remove: switch completes, backup holds the edited/foreign content, original removed                                                                                | PASS                                                                                                                                                                                                                                                                 |
| edit / replace + Keep unmanaged: switch completes, the edited copy is **not deleted**, it is listed under `unmanaged`, and its record leaves `state.installed`                                  | PASS                                                                                                                                                                                                                                                                 |
| edit + Add (to beta): profile beta gets the edited content, the claude-code copy is removed, and the item links into oh-my-pi                                                                   | PASS                                                                                                                                                                                                                                                                 |
| unmodified copy: listed as a managed `copy` item. Switch runs with no dialog and removes the copy                                                                                               | PASS                                                                                                                                                                                                                                                                 |
| `a` key (adopt outside a switch) on an edited copy, then Keep: resolved. A later `respec use beta` does not block and leaves the copy intact                                                    | PASS                                                                                                                                                                                                                                                                 |
| `a` key on an edited copy, then Add to the **active** profile alpha                                                                                                                             | Fails with `error: profile 'alpha' already has an item 'a1'; remove it first with 'respec remove a1 -p alpha'`. Nothing changes: the edited copy and the profile copy are both intact. CLI `respec adopt --add a1` gives the identical error (exit 1). See finding 1 |

Blocking: the only switch path in the TUI is `switch.use`. With no choices it
raises `UnknownEntries` and the dialog opens. With choices, the handler re-raises
`UnknownEntries` when an entry has no choice, before anything is resolved (the
repo test `test_entry_appearing_after_the_dialog_opened_blocks_the_switch` covers
this). `switch._remove` now skips every path that `is_managed` rejects, so a
mutated copy can never be deleted silently by a TUI-initiated switch.

## Bare `respec` with non-TTY I/O (10 s timeout via `subprocess.run(timeout=10)`)

Isolated `HOME`/`RESPEC_HOME`/`RESPEC_USER_HOME` under the scratchpad, binary
`.venv/bin/respec`:

| Invocation                                 | Result                                                                                                                                   |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `respec`, stdin=/dev/null, stdout=pipe     | rc 0 in 0.62s (cold start), prints help                                                                                                  |
| `respec`, stdin=empty pipe, stdout=pipe    | rc 0 in 0.20s, prints help                                                                                                               |
| `respec`, stdin=pty, stdout=pipe           | rc 0 in 0.20s, prints help                                                                                                               |
| `respec`, stdin=/dev/null, stdout=pty      | rc 0 in 0.23s, prints help (the pty master must be drained)                                                                              |
| `respec tui`, stdin=/dev/null, stdout=pipe | rc 1 in 0.14s, `error: the TUI needs a terminal (stdin and stdout must be a TTY); use the respec commands instead (see 'respec --help')` |

No home folders or state were created. One early run of the stdout=pty probe
hit the timeout because the harness did not drain the pty master, so the help
text filled the pty buffer. That was a harness artifact; with a drain thread
the run exits in 0.23s. macOS has no `timeout(1)`; Python's subprocess timeout
was used instead.

## Code inspection (duplicates, dead code, vocabulary)

The TUI is a thin layer: it calls `profiles`, `switch.use` / `switch.status`,
`adopt.find` / `adopt.resolve` / `adopt.adopt` and `unknown`. It has no copy of
switch, adopt or digest logic. Pyflakes found no unused imports or variables.

Findings (none blocking):

1. **Add-back clash for an edited copy (cross-ticket UX, fix-1 × 004, surfaced
   by 010).** Under fix-1, an edited copy of an item the active profile already
   has counts as unknown. The adopt dialog (and `respec adopt --add`) offers
   "Add to profile <active>", but that always fails on the name clash in
   `items.add_local`. It fails safely and nothing is lost, but the user has no
   one-step way to fold the edit back into the profile. Product decision, not
   a regression. The TUI could disable or relabel that choice, or adopt could
   offer "update the profile's copy".
2. **Duplicated presentation helpers (minor).** `tui._resolution_text`
   duplicates `cli._report_resolution`, and `tui._profile_rows` re-implements
   `cli._profile_summary` plus the list loop. Both are wording and formatting,
   not core logic, so the 010 criterion "no logic duplicated" is met. They
   could share a small formatter module.
3. **Vocabulary drift (minor).** A replaced entry is described two ways:
   "replaced a managed item" (CLI `status`, TUI status panel) and "replaced an
   item respec installed" (CLI prompt, `UnknownEntries` message, TUI dialog).
   The TUI uses both on one screen. The CLI quotes profile names
   (`to profile 'beta'`). The TUI does not (`to profile beta`).
4. **Redundant check (trivial).** On the bare-`respec` path, `cli.main` checks
   `_interactive()` and then `_open_tui` checks it again. The second check is
   needed for `respec tui`, so this is not dead code.

No dead code was found in the change range.

## Not done

No ticket updates, commits, merges, pushes or PRs. No guard denials occurred.
