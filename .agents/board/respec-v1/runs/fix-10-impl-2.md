# fix-10 implementation 2: fix round 1 (review 1)

- Status: DONE
- Branch: `codex/respec-v1-fix-10`, previous head `b3b1fb3`, new head `b25f79c`
  (no rebase; base `4092c83`)

## Changes

- **B1 (blocking), case-variant names.** A new function,
  `profiles.existing_folder(respec_home, name)`, returns a profile folder only
  when `name` is listed exactly by `os.listdir(profiles/)`. A case variant is
  refused with `profile 'WORK' does not exist (names are case-sensitive; did
you mean 'work'?)`. `profiles.load_profile` now uses this function.
- **B1 audit.** Every profile-name lookup that acts on a profile goes through
  `load_profile`: `use`, `profile show`, `add`/`remove`/`enable`/`disable`/
  `update -p`, the `layer` commands, and adopt add. Before this fix,
  `disable tdd -p WORK` on macOS edited the active `work` profile but treated
  it as inactive, because the code compares names with `active_profile ==
profile.name`, so the links fell out of line. `use WORK` would have recorded
  `WORK` as the active profile. All of these now refuse.
  `profile new` and `profile install` already refused a case variant because
  their exists checks fold case. The TUI passes exact listed names.
  `remove_profile` uses `existing_folder` and also refuses when
  `os.path.samefile(folder, profiles/<active>)` is true. This covers a
  `state.json` whose active name differs only in case.
- **N1, links still installed.** `remove_profile` scans every registered
  target folder and every folder `state.json` records as owned (deduplicated
  by realpath). It refuses when any symlink there resolves into the profile
  folder, checked by path and by samefile, whatever state says. The error
  lists those links and points to `respec use <other>` / `respec restore`.
  `remove_profile` now takes `user_home`, and the CLI and TUI pass it.
- **N2, TUI.** `#remove` is disabled when the active profile is selected. If
  `d` is pressed on the active profile, a refusal appears in the feedback line
  and no dialog opens. The core function still refuses as well.
- **N3, wording.** The pending-journal refusal has its own text: "cannot
  remove profile 'x' while an interrupted change waits; nothing was changed.
  <What> (started …) did not complete. Run 'respec recover' … then remove the
  profile." It no longer claims that the command finishes the change.
- **N4, empty runs.** Under the lock, before it creates a run, the next
  removal runs `rmdir` on empty run folders in `removed-profiles/`. It never
  deletes content.
- **Docs.** The README and shipped SKILL.md now cover the linked-profile
  refusal and case-sensitive names. The README also says that `restore` never
  brings a removed profile back, that nothing prunes `removed-profiles/`, and
  that the next removal clears the empty folder a kill can leave.

## Tests (red first)

All of these failed for the intended reason on `b3b1fb3`. The test file system
(APFS) is case-insensitive, so the case tests ran rather than skipped.

- `test_a_case_variant_of_the_active_profile_is_refused`: real filesystem.
  It skips with a reason when the filesystem is case-sensitive. On `b3b1fb3` it
  failed with exit 0.
- `test_only_the_exact_listed_name_is_a_profile`: logic-level. It
  monkeypatches `Path.is_dir` to fold case, then checks that both
  `removal.remove_profile` and `profiles.load_profile` refuse `WORK`. On
  `b3b1fb3` it failed with "DID NOT RAISE".
- `test_a_case_variant_does_not_change_the_active_profile`: `disable -p
WORK` and `use WORK` refuse, and the `work` profile and the active profile
  are unchanged. On `b3b1fb3`, `disable` exited 0.
- `test_a_profile_whose_links_are_still_installed_is_refused` (N1):
  `use work`, empty `state.json`, then `recover` (rebuilt, no active profile).
  `profile remove work --json` exits 1, the error names the link, and the link
  still works.
- `test_the_pending_refusal_does_not_claim_the_command_recovers` (N3).
- `test_an_empty_run_left_by_a_kill_is_cleaned_up` (N4, real SIGKILL).
- `tests/test_tui.py::test_removing_the_active_profile_is_refused` was
  retargeted for N2. It checks that the button is disabled, that `d` shows the
  refusal without the dialog, and that the button is enabled for `beta`. It
  failed against `b3b1fb3`'s `tui.py`.

## Verification (after the last change)

- `uv sync --frozen`: ok. `uv lock --check`: `Resolved 28 packages`.
- `uv run black --check .`: `45 files would be left unchanged.`
- `npx --yes prettier@3.3.3 --check README.md src/respec/shipped/respec/SKILL.md src/respec/shipped/profile-maker/SKILL.md src/respec/targets.yaml`:
  all pass.
- `uv run pytest -q -p no:cacheprovider`: `589 passed in 207.53s`.
- Real CLI smoke test (`.venv/bin/respec`, scratch homes, APFS):
  `profile remove WORK` and `disable tdd -p WORK` both exit 1 with the
  did-you-mean message. After emptying `state.json` and running `recover`,
  `profile remove work` exits 1 and names `~/.claude/skills/tdd`, and the link
  still works.

## Concerns

- The N1 scan covers each target folder's top-level entries, which is where
  respec puts its links. Links that a user nested deeper or placed elsewhere
  are not detected.
- Case-variant names are refused even when the input is clearly the same
  profile. This is deliberate: names stay exact everywhere.
