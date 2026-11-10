# t005 review 2: restore backups and release ownership (after fix round 1)

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t005`
- Diff: `eeca3cb13e94608ea86451782c87a96f32810adb..b0fd1fe901c5879eeb317bd25891def8e1448e69`
  (HEAD verified, clean tree)
- Verdicts: spec-compliance PASS, code-quality PASS, tests-rerun PASS
- Blocking findings: 0

## Gates rerun

- `uv run pytest -q`: 154 passed
- `uv run black --check src tests`: 25 files would be left unchanged
- `npx prettier@3 --check README.md`: all files use Prettier code style
- `uv lock --check`: Resolved 28 packages
- `git diff --check eeca3cb..b0fd1fe`: clean
- Scratch probes: 16 tests in a temp dir outside the worktree, using a copied
  conftest and test helpers. 13 passed. The 3 failures are the
  non-blocking findings N1 and N3 below. One probe I had built wrong was
  rewritten and then passed.

## Investigation points

### (a) B1 is fixed

`_plan` no longer guesses from history position or current profiles. `_entries`
skips only two kinds of entry: symlinks into `profiles/`, and copies whose digest
matches a `mode: copy` item that the run's own `manifest.json` lists under that
target. The probes all passed:

- The prior repro: named restore of run1 while cycle 2 owns the folder. The
  restore is exact and `skipped == []`.
- Three ownership cycles with different `mine` content each time. A named
  restore of each run returns that run's exact snapshot.
- A cycle-2 run holds `mine` with content identical to the profile item that
  `adopt --add` created. Restoring it while owned, and again after release,
  is exact with `skipped == []`.
- Pre-respec content identical to a profile item comes back, and no manifest is
  written for that run.
- Every skip appears in `RestoreResult.skipped`, in JSON `skipped`, and in
  human output as `Skipped <path>`. Tested in
  `test_restoring_a_backup_holding_respec_links_does_not_recreate_them` and
  `test_restoring_a_backup_holding_respec_copies_does_not_recreate_them`.

### (b) Manifest

- A manifest is written only when the folder already held respec items at
  takeover. In practice that is an alias of an owned folder. A probe checked
  the content: it lists the copy and its digest under the new target's key.
  The earlier run has no manifest. `--list` never shows `manifest.json` as a
  target, because only directories count.
- Missing manifest, or a legacy run: respec copies come back as user content,
  so nothing is dropped. Links are still skipped. This was probed. It errs on
  the side of keeping data.
- Corrupt manifest: see N1. Corruption is caught before any change, so the
  restore fails closed. Some shapes crash with a raw `TypeError`.
- The manifest write is not atomic. See N2.
- Tampered manifest: a forged entry whose name and digest match the backup's
  user entry makes restore skip it. The skip is reported, and the content stays
  in the backup. Forging an entry needs write access to the respec home, and
  that access already allows deleting backups. Not treated as a security
  boundary. Noted as N4.

### (c) Fidelity

- `snapshot` now records permission bits and raw bytes. The `populate` fixture
  includes a 0755 script, a 0600 file, binary data, an empty directory, and a
  user symlink.
- `test_restore_puts_back_modes_binary_content_and_empty_folders` and every
  exact-snapshot test cover these.
- `_same` compares digest plus lstat modes. Kept entries that differ only in
  permissions now count as conflicts
  (`test_kept_entry_with_changed_permissions_is_not_identical`).
- Put-back uses `copy2` and `copytree(symlinks=True)`.
- The private `_put_back` patch is gone. The replacement test chmods a backed-up
  file to 000, so a real copy fails. It asserts that state matches disk, then
  reruns the restore and checks the result is exact.
- An extra probe ran the same failure and rerun on a named run. It passed.

### (d) Regressions

- The unknown-entry and adopt flow is unchanged. The refuse, `--unknown`,
  interactive and `--overwrite` tests pass.
- Copy digests from fix 1 still guard `remove_installed`
  (`test_edited_copy_is_never_deleted_silently`).
- Untracked respec links are not recreated, both by default and by name
  (`shared_folder` tests).
- `state.json` stays consistent on partial failure: no active profile, installed
  items cleared, ownership kept, and a rerun finishes.
- No callers of the renamed helpers remain.

## Non-blocking

- **N1: malformed manifest crashes instead of giving a `RespecError`.**
  - Location: `src/respec/restore.py` `_recorded_at_backup` and `_entries`.
  - Scenario: a manifest of `[]`, `{"installed": {"<t>": 5}}`, or an item whose
    `name` is a list. These raise `TypeError`, which the `except` tuple misses.
    `RespecError` subclasses are not involved. The CLI exits 1 with no message
    in `CliRunner`, and a real run shows a traceback.
  - Truncated JSON, and `installed` given as a list, do produce
    `invalid backup manifest`.
  - Impact: only the error message. Nothing has changed on disk yet.
  - Fix: catch `TypeError`, or validate the shape before use.
- **N2: the manifest write is not atomic.**
  - Location: `src/respec/switch.py` `_record_backed_up_items`
    (`manifest.write_text`).
  - Scenario: a crash during the write leaves truncated JSON. A later named
    restore of that run then fails with `invalid backup manifest`, and there is
    no override.
  - Default restore is unaffected, because an alias run is never a folder's
    earliest takeover.
  - Impact: low. Fix: write to a temp file, then `os.replace`.
- **N3: link skip is judged by the current profiles path, not by the manifest.**
  - Location: `src/respec/restore.py` `_respec_link`.
  - Scenario (probed): before takeover, the user had their own symlink
    `~/.claude/skills/x -> <respec home>/profiles/lib/skills/x`. Default
    `restore` skips it in the backup. It then treats the live link as an
    unknown conflict, and the restore is blocked until the user runs
    `--unknown keep` or `--overwrite`.
  - Impact: a rare edge case. Restore is not exact for that entry, but it is
    reported and nothing is lost.
  - Why it stays: this rule keeps legacy runs, which have no manifest, from
    recreating respec links. The manifest does record symlink items, so a
    later change could prefer manifest facts when a manifest is present.
- **N4: forged manifest entries.** See (b). Acceptable, because the manifest
  sits in respec's own private store.
- **Carried over: prior N3.** Parent folders that respec created are left
  behind on restore. The orchestrator accepted this.

## Scope

The diff touches `restore.py`, `switch.py` (manifest, and public `utc_now`,
`new_backup_run` and `remove_installed`), `adopt.py` (renames), `cli.py`
(restore command and output), `README.md` and tests. All of it is in scope for
ticket 005 and spec decision 6. There are no unrelated changes.
