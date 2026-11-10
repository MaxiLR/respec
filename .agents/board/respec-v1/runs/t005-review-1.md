# t005 review 1: restore backups and release ownership

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t005`
- Diff: `eeca3cb13e94608ea86451782c87a96f32810adb..02458e6932d6da9c309bc5267b343d6cfa0c32a4`
  (HEAD verified, clean tree)
- Verdicts: spec-compliance FAIL, code-quality PASS, tests-rerun PASS

## Gates rerun

- `uv run pytest -q`: 149 passed
- `uv run black --check src tests`: 25 files would be left unchanged
- `npx prettier@3 --check README.md`: all files use Prettier code style
- `grep -rn "_new_backup_run|_utc_now|switch._remove|_remove(" src tests`: no hits
- Scratch probes (temp-home `isolated_homes`, copied conftest, outside the
  worktree): 2 passed, 1 failed (finding B1)

## Blocking

### B1: named restore of a pre-respec takeover run can silently drop the user's original

- Location: `src/respec/restore.py` `_plan` (`pre_respec = earliest[key] == str(source)`,
  and the `_oldest_run_holding` fallback), with `_entries`/`_respec_copy`.
- Scenario (reproduced):
  1. `~/.claude/skills/mine` exists. `use a`, which writes takeover run1.
  2. `adopt --add mine`, then `restore`. `mine` comes back. Correct.
  3. Remove `mine`. `use a` again, which writes takeover run2.
  4. `restore <run1>`.

  Result: `~/.claude/skills` is empty. run1 holds `mine`, and the command reports
  success.

- Cause: a backup only counts as "pre-respec" when it is the current owner's
  earliest takeover, or, after a release, the oldest run of all. Every other run,
  including real pre-respec takeovers from earlier ownership cycles, goes through
  the copy heuristic. Any backed-up entry whose content matches _any_ profile's
  item of the same name gets skipped. The match ignores whether that item is
  enabled and which targets it has. `adopt --add` naturally makes such matches,
  because it copies the user's original into a profile. The same failure occurs
  for `restore <run2>` after a release, when run2 is a cycle-2 takeover.
- Impact: this violates "Restored folders match backup contents exactly" and the
  spec testing decision "restore returns exact backup contents". Nothing is
  deleted from disk: the content survives in the backup and in the profile. But
  the user gets a silently incomplete restore of the backup they named.
- Suggested direction: decide whether a run is pre-respec from the run itself,
  not from its position in history. For example, record at takeover time whether
  the folder was already owned (a marker in the run, or in state history). Or
  restrict the copy rule to digests respec recorded when the run was taken. At
  minimum, add a test for named restore across two ownership cycles.

## Non-blocking

- N1 (mode drift on kept entries): `_conflicts`/`_restore_folder` treat an entry
  as identical to the backup when `unknown.digest` matches, and the digest ignores
  permissions. Probe: kept `s/run.sh` is 0755 in the backup. After a chmod to
  0600, `restore` succeeds and leaves 0600. The restore is exact for bytes, empty
  directories, symlinks (including broken ones), modes and mtimes of entries it
  puts back (probe: zero diffs, including the folder's own mode). The gap is only
  in entries it decides to leave in place.
- N2 (inexact by design, `_conflicts`): kept entries missing from the backup stay,
  and so do hidden entries. Judged acceptable. Deleting a kept entry would discard
  content without asking, which the ticket's refuse-to-overwrite rule and adopt
  `keep` semantics argue against. However, the CLI does not report which kept
  entries remain, so a user expecting an exact restore is not told. Consider
  printing them.
- N3 (parents left behind, `_restore_folder` with `source is None`): only the
  empty skills folder is removed. Parents that `switch._install` created
  (`~/.omp/agent`) stay. Judged acceptable: respec does not record which parents
  it created, and the spec scopes ownership to target folders. Document it, or
  record created parents in a later ticket.
- N4 (copy heuristic false negatives, `_respec_copy`): in a backup taken after
  ownership, a respec copy is recognised only if its digest matches a current
  `state.installed` record or a current profile item. Suppose the profile item
  was later edited (for example by `respec update`) or the profile was deleted.
  The old respec copy is then restored as user content. Links are always skipped,
  so (b)'s "no untracked links recreated" holds. Copies are best-effort.
- N5 (test seam): `test_failed_restore_keeps_state_true_to_disk_and_can_be_rerun`
  patches the private `restore._put_back`. This is acceptable for fault
  injection, but it is coupled to internals.
- N6 (test coverage): no test covers modes, binary content or empty
  subdirectories. `snapshot` reads text and ignores modes. The probe showed this
  works for put-back entries, but nothing in the suite would catch a regression.

## Investigation points

- (a) PASS. Unknown entries in a folder being restored go through `on_unknown`,
  which is `adopt.resolve`. Anything left over raises `RestoreBlocked` before any
  change. Only `--overwrite` or an interactive confirmation sets entries aside,
  through adopt's `backup`, into a fresh run, and only after a complete copy.
  Edited or replaced copies are not managed (digest mismatch), so they become
  conflicts. `remove_installed` returns False for them and never deletes them.
  This is tested in `test_edited_copy_is_never_deleted_silently`. Unknown
  entries in owned folders that a named run does not cover are left untouched.
- (b) PASS for links: `_respec_link` skips every symlink into `profiles/` in any
  backup. Default restore of a shared folder uses the earliest takeover. Both
  are tested. Copies follow a heuristic (N4, and B1 is its false-positive side).
- (c) FAIL due to B1. Put-back fidelity is otherwise byte-exact, including
  symlinks, broken symlinks, empty directories, modes and mtimes (copy2 and
  copytree with `symlinks=True`). N1 is a minor gap.
- (d) PASS. `_apply` saves state after each removal. On `OSError` it keeps
  ownership, so a rerun resolves the same plan and finishes. Nothing deletes
  backup runs. Set-aside writes to a new run. A half-removed copy would become a
  `replaced` conflict on rerun, which is safe, not lossy.
- (e) Both behaviours are acceptable against the spec (N2, N3). Surfacing kept
  leftovers is recommended.
- (f) PASS. `switch.py` and `adopt.py` are updated. `tui.py` uses none of the
  renamed helpers. No old names remain in `src` or `tests`.
- (g) PASS. The autouse `isolated_homes` fixture guards real-home resolution.
  Tests assert on filesystem snapshots compared with fixtures captured before
  respec ran. They are not mirror tests.
