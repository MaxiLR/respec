# fix-9 implementation 1

- **Status:** DONE
- **Branch:** `codex/respec-v1-fix-9`
- **Base:** 374b7f2
- **Head:** 55362bc

## Changes

- **New `src/respec/lock.py`:** an exclusive `fcntl.flock` on
  `<respec home>/.lock`.
  - It is reentrant per process.
  - `acquire` waits up to `WAIT = 1.0` s, polling every 20 ms. It then raises
    `lock.Busy`, a `RespecError`: "another respec is running and changing
    skills ...; nothing was changed."
  - `busy()` is a read-only probe. It takes a shared non-blocking lock for an
    instant, and `holds()` reports whether this process holds the lock.
  - **Chosen policy:** wait briefly, then fail. It is documented in the
    README section "Running two at once".
- **CLI (`cli.py`):** `_hold_lock` runs at the start of every mutating
  command:
  - `use`, `add`, `remove`, `enable`, `disable`, `update` (not `--check`),
    every `layer` change, `adopt`, `restore` (not `--list`), `recover`,
    `profile new` and `profile install`.
  - With `--json`, a busy failure prints the command's usual keys, empty,
    plus `error`. `use`, `adopt`, `restore` (with `kept` for release-only) and
    `recover` keep their documented failure shapes. Other commands print
    `{error, warnings}`. The exit code is 1.
  - The lock is released by `ctx.call_on_close(lock.release_all)`. It is
    registered before `_print_warnings`, so it runs after the warnings.
  - Read-only commands never take the lock.
- **Journal (`journal.py`):**
  - These hold the lock as a safety net, so no journal is written without
    it: `begin` (outermost only), `ready` (its check and auto-recover),
    `recover` and `rebuild_state`.
  - `pending()` returns None while another process holds the lock. Status,
    warnings, JSON and the TUI Sync screen therefore never call a live change
    "interrupted".
- **TUI (`tui.py`):** each change runs under `lock.exclusive`:
  - create profile, toggle, layer choice, add from folder, git add (inside the
    worker thread, via `_changing`), Sync resolve/repair/relink/disable,
    activate (`switch.use`), the takeover resolve with its link, and adopt.
  - `recover` locks itself.
  - A `Busy` error shows up as ordinary error feedback.
- **`state.py`:** the temp file is now `.state.json.<pid>.<uuid>.tmp`, and it
  is unlinked if the write fails. It is opened normally, so the umask
  permissions are unchanged.
- **N3 (`sources.py`):** `UpdateResult.active` is filled from `state.json`
  at the start of `_update`, so it is also right when nothing was swapped.
- **N4:**
  - New helpers `messages.plural` and `messages.skills_placed` produce output
    such as "2 skills (4 links)", "1 skill (1 link)" and "(3 links, 1 copy)".
  - They are used for `use`'s Removed/installed lines, for restore and
    release-only ("Removed N skills (M links) placed by respec"), and for the
    TUI switch feedback.
  - README: "Every command except `tui` accepts `--json`". It also documents
    the lock and the `active` field.
- **int-374b7f2 minor findings:**
  - `switch.status` calls the new `takeovers.inspect`. That reports an
    unreadable log as `unreadable-takeover-log` (JSON warning and stderr) and
    leaves the file as it is. A newer-version log is ignored there.
  - `adopt._delete` and `journal._delete` are merged into
    `trees.delete_entry` with an identical body, so behavior is preserved.

## Criteria → evidence

1. **N1 concurrency:** `tests/test_concurrency.py`. Each test was red on
   base unless noted.
   - `test_a_second_use_while_one_runs_fails_cleanly_and_the_first_wins` is
     the real two-process test.
     - Process A is a subprocess paused at the `use:begin` checkpoint while it
       holds the lock. Process B is a second subprocess running `use b`.
     - B fails with rc 1, a clear message and no traceback. A then succeeds.
     - Links and the `state.json` records are consistent across all 3
       targets, with no journal left.
   - `..._json_gives_an_error_and_changes_nothing`: JSON `error`, empty
     warnings, `state.json` unchanged.
   - `test_status_while_a_change_runs_does_not_call_it_interrupted`: status
     with `--json` and as text.
   - `test_recover_is_refused_while_the_change_it_would_recover_runs`.
   - `test_read_only_commands_run_while_a_change_runs` (guard; green on
     base).
   - `test_a_kill_while_running_leaves_no_lock_behind`: SIGKILL inside `use`,
     then the next `use` succeeds well within 10 s. This confirms that flock
     is released when the process dies. Green on base, as expected.
   - `test_racing_switches_never_crash_and_leave_one_profile_whole`: 4 rounds
     of truly concurrent `use b` and `use a`. There is no traceback, every run
     either succeeds or gives the clear message, and the state stays
     consistent. Base showed the `.state.json.tmp` FileNotFoundError.
   - `test_state_saves_from_several_threads_never_collide`: the unique temp
     name, and no leftovers.
   - TUI: `test_tui_editing.py::test_toggle_while_another_respec_changes_skills_is_refused_cleanly`.
     On base it said "was interrupted"; it now says "another respec is
     running", and the profile is unchanged.
   - The `holder` fixture lives in `tests/conftest.py`.
2. **N3:** `test_sources.py::test_update_json_says_the_profile_is_active_also_when_nothing_changed`
   covers skipped-local-edits and up-to-date (red on base). The companion
   test checks that an inactive profile gives `false`.
3. **N4:** `test_use_status.py::test_use_reports_skills_and_links_separately_with_plurals`
   and `test_restore.py::test_restore_counts_the_removed_skills_and_their_links`
   were both red on base. The README was corrected.
4. **int minor findings:** `test_journal.py::test_status_warns_about_a_corrupt_takeover_log_and_leaves_it`
   (red on base). The `_delete` merge is a pure refactor and is covered by
   the existing journal and adopt suites.

Data safety: the SIGKILL matrix and JSON contract tests are unchanged and
pass.

## Verification (after the last change)

- `uv sync --frozen`: ok.
- `uv lock --check`: "Resolved 28 packages".
- `uv run pytest -q`: **553 passed** in 195 s. The base had 539; 14 tests
  were added.
- `uv run black --check src tests`: 43 files unchanged.
- `npx prettier@3 --check README.md`: clean.
- `use` timing, measured in-process on 40 skills × 3 targets with shipped
  skills: new 0.30–0.31 s, base 0.30–0.31 s, so no regression. The
  review's 0.15 s figure came from a different setup.

## Concerns

- **TUI wait:** the 1 s wait runs on the TUI's UI thread when another
  process holds the lock, so the UI can freeze for up to 1 s.
- **Long git operations:** a TUI git add holds the lock for the whole fetch.
  A CLI command started during it fails after 1 s.
- **Leftover temp files:** a SIGKILL between the temp write and the rename
  can leave a uniquely named `.state.json.*.tmp`. These are not cleaned up
  (harmless).
- **Lock file location:** `.lock` is created in the respec home, and the
  folder is created if it is missing, on the first mutating command.
- **Not addressed:** N4's third bullet (the shared-folder backup/restore
  wording) was not among the acceptance criteria, so it is unchanged.
