# fix-10 review 1: `respec profile remove`

- Reviewer: fresh, independent (did not implement)
- Diff: `4092c83fc1d41bd68a9cc763b1fe36694b5d0f00..b3b1fb35a747f2137831a285415f26c92dcaf144`
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-10` (clean)
- Verdicts: spec-compliance **FAIL**, code-quality **FAIL** (one blocking defect),
  tests-rerun **PASS**

## Gates rerun (fresh, in the worktree)

- `uv sync --frozen`: ok. `uv lock --check`: `Resolved 28 packages`.
- `uv run black --check .`: `45 files would be left unchanged.`
- `npx --yes prettier@3.3.3 --check README.md src/respec/shipped/respec/SKILL.md src/respec/shipped/profile-maker/SKILL.md src/respec/targets.yaml`:
  `All matched files use Prettier code style!`
- `uv run pytest -q -p no:cacheprovider`: `583 passed in 208.19s`

## Blocking findings

### B1. The active profile can be removed through a case variant of its name (macOS)

- Location: `src/respec/removal.py`, `remove_profile`. The checks are
  `folder.is_dir()` (where `folder = profiles_dir / name`) and
  `state.active_profile == name`.
- Failing scenario: real CLI in a temp home on the default APFS volume, which
  is case-insensitive:
  `respec profile new work -t claude-code; respec add <dir>/tdd -p work; respec use work; respec profile remove WORK`
  exits 0 and prints `Removed profile 'WORK'`. `profiles/work` moves to
  `removed-profiles/<run>/WORK`. `status` still says `Active profile: work`.
  The `tdd` link in `~/.claude/skills` now dangles, and `respec use work`
  fails with `profile 'work' does not exist`. `respec restore` still works.
- Impact: this breaks acceptance criterion 2 (refuse the active profile) on
  macOS, the platform the project mainly targets. The active profile's skills
  stop working in every agent folder and nothing is reported. The data can be
  recovered with a manual move, but the result is wrong. The TUI is not
  affected because it passes exact listed names.
- Fix direction: resolve `name` against the exact on-disk names
  (`profiles.list_profile_names`) and refuse a name that is not listed
  exactly. Alternatively, refuse when `os.path.samefile(folder, profiles_dir / active)`.
  Add a test for the case variant.

## Non-blocking findings

### N1. After `respec recover` rebuilds `state.json`, a profile whose links are still installed can be removed

- Location: `src/respec/removal.py`. Only `state.active_profile` is checked.
  `state.installed` is not.
- Scenario: `use work`, corrupt `state.json`, `respec recover`. The record is
  rebuilt with no profile active, and the links into `profiles/work` stay
  recorded. `profile remove work` then succeeds, and the recorded
  `~/.claude/skills/tdd` link dangles. `status` lists it as an ordinary
  `symlink`. A later `restore` or `use <other>` cleans it up correctly.
- Impact: this is a rare path and nothing is lost, but the user's agents
  silently get a broken skill entry. Suggestion: also refuse while any
  `state.installed` path links into the profile folder, or at least warn.

### N2. The Remove button and `d` stay enabled for the active profile

- Location: `src/respec/tui.py`, `_update_activate`. Remove is disabled only
  when nothing is selected.
- Scenario: select the active profile, press `d`, then confirm. The refusal
  appears only after the confirmation. After a successful removal, selection
  falls back to the active profile, so a second `d` opens the dialog for it.
- Impact: UX only. The refusal is correct and matches the CLI. Disabling the
  button for the active profile, as `#activate` already does, would avoid a
  confirm-then-refuse step.

### N3. Wording of the pending-journal refusal

- The `journal.pending_message` text in the refusal ends with "any respec
  command that changes skills finishes it first", but `profile remove`
  refuses instead. The implementer flagged this too. It is cosmetic.

### N4. A kill before the rename leaves an empty run folder

- A kill at `profile-remove:move` or right after `mkdir` leaves an empty
  `removed-profiles/<stamp>/`. It is harmless. The README's crash sentence is
  accurate about the profile, but it does not mention the empty folder.

## Acceptance evidence (independent, real CLI `.venv/bin/respec`, temp homes under scratchpad)

1. The command exists with `--json`. `profile remove --help` renders, and the
   `profile --help` list includes it. JSON success has the keys
   `{name, path, backup, warnings}`.
2. The exact-name refusal of the active profile works in text and JSON (exit
   1; the message points to `respec use <other>` and `respec restore`). The
   case variant fails (B1).
3. No hard delete. `spare` moved to
   `removed-profiles/20261110T153934Z/spare`. I moved it back by hand to
   `profiles/spare` as the README documents, and `profile list` showed it.
   `respec use spare` linked its `tdd`. Removing twice in the same second
   produced the `-2` suffixed run.
4. Lock: with another process holding `.lock`, the command printed
   `another respec is running…`, exit 1, JSON
   `{name, error, warnings}`, and the profile stayed. Pending journal:
   `use work` was SIGKILLed at `backed-up`. The remove was refused in text
   and JSON and pointed to `respec recover`. The journal and profile were
   unchanged. SIGKILL (real `os.kill(SIGKILL)` in-process) at
   `profile-remove:move`, after `mkdir`, right after `os.rename`, after the
   first `sync_folder`, and at `profile-remove:moved`. In every case the
   profile was intact in `profiles/` or complete in the backup (sha
   comparison identical). `status` exited 0 and `use work` worked.
5. `..`, `../other`, `/`, `/etc`, an absolute profile path, `a/b`, `./spare`,
   `spare/` and `''` were all refused as invalid names, exit 1. `nope` was
   refused as not existing. Nothing outside `profiles/` moved, and no
   `removed-profiles/` folder was created.
6. TUI (headless Textual pilot, real `RespecApp`): the dialog opens with
   Cancel focused. The Cancel button, Esc and Enter on the default focus all
   keep the profile. Confirming removes it and shows the backup path in the
   feedback, and the list refreshes. The active profile is refused after
   confirmation. All of this uses `removal.remove_profile` under `_changing`.
   The repo tests also cover the lock and pending-journal refusals.
7. The README (usage, paragraph, lock list, busy shapes, JSON section, TUI)
   and the shipped SKILL.md are updated. `test_help.py` walks every command,
   so the new one is covered. The JSON contract tests include the success,
   failure and busy shapes.
8. The new text says "skills". A grep of the added lines found no "item".

Interactions:

- Layers live inside `profile.yaml`, so they move with the profile. Global
  skills (`config.yaml`, `global/skills/`) never reference a profile, so they
  are unaffected.
- Removing the profile that made the takeover backup (`work`) and then running
  `respec restore` worked: `claude-code` was restored from the takeover run.
  Removing a profile after a restore also worked. `restore` judges respec links
  by written path, so a takeover backup that holds links into a removed
  profile is still skipped.
- `removed-profiles/` vs `backups/`: removed profiles do not appear in
  `restore --list`. This is acceptable. `backups/<run>/` holds target
  folders, and a profile there would be listed as a run that `restore <run>`
  cannot apply. The README and SKILL.md name the location and the manual way
  back. Not stated explicitly: `restore` never brings a profile back, and
  nothing prunes `removed-profiles/`. A one-line note is suggested but not
  required.

## Scope

The diff is limited to the feature: core module, CLI, TUI, docs, tests, and
an optional `parent` argument for `switch.new_backup_run`, whose default
behavior is unchanged. There is no unrelated churn.
