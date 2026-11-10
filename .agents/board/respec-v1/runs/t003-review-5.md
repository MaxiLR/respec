# t003 review 5 (fresh, independent)

- Range: `3e563b6f96fbe9a7b9e3af1eae941c10cc795127..5532d01f28ed335d7733c42f06cf0cb833bbb0d0`
  - Focus: round 4, `4cb420b..5532d01`.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t003`, clean, HEAD = 5532d01.
- Method: real CLI (`.venv/bin/respec`) in temp homes under the scratchpad
  (`RESPEC_HOME`, `RESPEC_USER_HOME`), plus scratch pytest files in a copy of
  `tests/`. No repository file was edited.
- Guards: no action was denied.

## Verdicts

- spec-compliance: FAIL (1 blocking: a bare restore after a rebuild is not
  truthful)
- code-quality: PASS
- tests-rerun: PASS

## Gates rerun

| Gate                                                                                                                                    | Result                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `uv sync --frozen`                                                                                                                      | ok                                                                     |
| `uv run pytest -q`                                                                                                                      | 513 passed (172.6s)                                                    |
| `-k "killed or kill or sigkill or interrupted"`                                                                                         | 133 passed                                                             |
| `black --check src tests`                                                                                                               | 40 files unchanged                                                     |
| `prettier --check README.md "src/respec/**/*.md"`                                                                                       | clean                                                                  |
| `pyflakes` on changed files                                                                                                             | 2 `handler` redefinitions in `cli.py:565,1281`, both outside this diff |
| Scratch SIGKILL matrix, real `os.kill(SIGKILL)` at every fault point: `use b` from none and from `a` (18 points), `restore --overwrite` | 3 passed; consistent, no journal left, user entries kept               |

## Blocking

### B1. A bare `respec restore` after a rebuild releases folders without restoring them and reports something false

- Location: `src/respec/journal.py` `rebuild_state` writes
  `Owned(backup=None)` for every folder.
  - `src/respec/restore.py` `_plan`, around lines 208-220, reads
    `backup is None` as "the folder did not exist at takeover".
  - `_restore_folder` (`plan.source is None`) then calls `rmdir` on the
    folder once it is empty.
- Scenario (real CLI, temp home `h2`):
  1. `~/.claude/skills/orig1` and `~/.agents/skills/orig2` exist. Run
     `respec use a`; the takeover run `20261110T051214Z` holds both.
  2. Run `respec adopt --all remove`; an adopt run holds both.
  3. Truncate `state.json`, then run `respec recover`: the result is
     `rebuilt`.
  4. Run `respec restore`.
- Output:
  ```
  Removed 8 respec skills
  Restored claude-code from nothing (folder did not exist)
  Restored agents from nothing (folder did not exist)
  ```
  The exit code is 0. `~/.claude/skills` and `~/.agents/skills` are
  removed, because they were empty. Neither `orig1` nor `orig2` is put back.
- What is lost: no data.
  - The originals are still in the takeover run and the adopt run.
  - A later `respec restore 20261110T051214Z` puts them back. This was
    verified, both with the originals already removed (`h2`) and with them
    still in place (`h4`).
- When the originals were still in the folders (`h1`), the bare restore
  refused with a conflict instead. Its wording, "would be overwritten by the
  backup", is also wrong, because no backup was picked.
- Impact: this breaks the requirement to recover "truthfully, nothing
  silently lost".
  - The command claims the folders did not exist, which is false.
  - It deletes folders the user owned before respec, although they were
    empty.
  - It leaves the user with no skills and no hint that a takeover backup was
    skipped. To the user, the originals look gone.
  - The rebuild message mentions `restore --list` only in passing, and a
    user may run `respec restore` long after the rebuild.
- Judgment on the implementer's concern (b): yes, the bare restore should
  refuse. Suggested fix:
  - `rebuild_state` marks each owned folder as having an unknown takeover
    backup (a distinct sentinel or flag in `Owned`, not `None`).
  - `restore` without a run name then raises a `RespecError` like this:
    "state.json was rebuilt; respec no longer knows which backup is each
    folder's takeover backup. Name one: `respec restore <run>` (see `respec
restore --list`)."
  - It must not remove any folder.
  - A named restore already works (verified), and so does `--json`, through
    `_fail`.
  - Add a test: rebuild, then bare restore, expecting exit 1, the folders
    untouched, and the message naming `--list`.

## Non-blocking

- N23. After a rebuild, respec forgets which folders it created
  (`Owned.created`).
  - Location: `journal.rebuild_state` sets no `created`.
  - Scenario: `oh-my-pi`'s `~/.omp/agent/skills` was created by respec at
    takeover. After a rebuild and a named restore, the empty
    `~/.omp/agent/skills` stays (verified in `h4`).
  - Impact: empty leftover folders. Nothing is lost. A leftover folder can
    make an agent look "installed".
- N24. `restore --list` after a rebuild is misleading in two ways.
  - It no longer labels takeover runs, because `takeover` comes from
    `Owned.backup`.
  - It lists the run that holds only the damaged `state.json` as a run with
    no targets. Naming that run fails with "holds no target folder".
  - Impact: the user has to guess which run is the takeover. This matters
    more once B1 asks them to name one. Consider labelling the `state.json`
    run, or leaving it out of the list.
- N25. An unrecorded `.x.dropping` folder whose content is unique is kept
  (correct), but two paths handle it badly.
  - Location: `sources._replace` and `_settle_foreign_old`.
  - Scenario A (scratch test): add a unique `.up.dropping` and a redundant
    `.up.old`, then run `respec update -p work`.
    - The skill fails with a raw
      `[Errno 66] Directory not empty: '.up.old' -> '.up.dropping'`, exit 1.
    - Every later update of that skill fails the same way until the user
      removes one folder by hand.
    - Data is kept, and the profile stays active and linked.
  - Scenario B: a unique `.up.dropping` alone. Update reports `updated`, and
    the kept folder is not mentioned. Only the recovery path (N21) reports it.
  - Impact: the error is opaque, and the only copy is not reported.
    - Suggestion: when the `.dropping` name is taken, delete the redundant
      `.old` in place, or pick a unique name.
    - Suggestion: report kept `.dropping` folders in the update result.
- N26. A `state.json` with a valid but different `version` (for example
  written by a newer respec) also raises `StateInvalid`.
  - The message tells the user to run `respec recover`, which moves the file
    aside and rebuilds it as version 1.
  - Impact: a downgrade silently discards newer state. The file is kept in a
    backup run, so nothing is lost, but the hint is wrong for this case.
  - Suggestion: give a version mismatch its own error that does not offer a
    rebuild.

## Focus items

- (a) Empty and corrupt `state.json`: PASS.
  - Tested an empty file and a cut-off JSON file.
  - These commands exit 1 with "invalid state file …" and the line "Run
    'respec recover' to rebuild it…": `status`, `status --json`, `use b`,
    `restore`, `restore --list`, `adopt`, `update`.
  - The error goes to stderr; `--json` prints no stdout.
  - `profile list` still works.
  - The TUI (`respec tui` under a pty) opens and shows the same error and
    hint, with no traceback.
  - `respec recover --json` returns `operation: state`, `outcome: rebuilt`
    and `set_aside` set to the damaged file, which is kept byte for byte in a
    new backup run.
  - The folders are untouched, respec's links are recorded, `orig*` is
    unknown, and no profile is active.
  - A later `use b` succeeds.
- (b) A bare restore after a rebuild: FAIL. See B1. Nothing is lost on disk,
  and a named run restores the originals, but the bare restore should refuse.
- (c) N21: PASS on the recovery path. An unrecorded unique `.notes.dropping`
  is kept and named in the recovery message; the test passes, and the
  journaled `dropping` note is used. The `_replace` path is weaker; see N25.
- (d) N22: PASS. The test passes, and `_put_back_old` now runs before the
  up-to-date check (`sources.py:698`). N19: verified in the code only
  (`journal.py` `_recover_use`). The note keeps the full indented error
  instead of its first line, and the change is trivially correct. I did not
  reproduce it with the CLI.
- (e) `use` timing, 20 skills per profile, 3 targets, links mode, real CLI:

  | Run                 | Time  |
  | ------------------- | ----- |
  | first `use a`       | 0.18s |
  | `use b`             | 0.25s |
  | `use a`             | 0.24s |
  | `use b`             | 0.25s |
  | `use a`             | 0.25s |
  | `status` (baseline) | 0.12s |

  This matches the claim of about 0.25s, so `use` stays fast. The added
  temp-file `fsync` costs nothing measurable.

- (f) SIGKILL matrix: no regressions.
  - The suite's real-SIGKILL tests for adopt, update and add pass, as do the
    in-process matrices for use and restore.
  - My scratch real-SIGKILL matrices for `use` and `restore --overwrite`
    pass at every fault point.

## Scope and quality

- The round-4 diff stays in scope: state, journal, sources, cli, README,
  the shipped SKILL.md and tests.
- `StateInvalid` subclasses `RespecError`, so existing handlers still catch
  it.
- Using `adopt._backed_up` across modules (a private helper) is existing
  practice.
- The new tests check observable behaviour, not source text.
- The flush guard now has a lower bound (N20 resolved).
- The README and the shipped SKILL.md describe the rebuild accurately.
  - They do not warn that a bare `restore` after a rebuild restores nothing,
    which is B1.
