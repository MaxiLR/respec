# fix-5 review 5: adopt rollback data safety (B3)

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Diff: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb..46aea65bc11a273a22f07a4f02472386d193a857`.
  The focus is `c044824..46aea65`: `src/respec/adopt.py` (`_put_back`,
  `_undo_adds`, adopt's error notes), `src/respec/switch.py`
  (`refuse_layer_conflicts(action=...)`) and `tests/test_layer_repair.py`.
- Verdicts: spec-compliance **PASS**, code-quality **PASS**, tests-rerun
  **PASS**. There are 0 blocking findings.

## Gates rerun (head 46aea65, clean tree)

| Gate                                            | Result                                             |
| ----------------------------------------------- | -------------------------------------------------- |
| `uv sync --frozen`                              | `Audited 27 packages`                              |
| `uv run pytest -q`                              | `281 passed in 48.21s`                             |
| `uv run black --check src tests`                | `29 files would be left unchanged.`                |
| `npx prettier@3 --check README.md`              | `All matched files use Prettier code style!`       |
| `grep -ci item` over `respec --help`, `layer *` | 0                                                  |
| Red check: the 5 round-5 tests on c044824 `src` | all 5 fail for the intended reasons (listed below) |

For the red check, `git archive c044824 src` was put on `PYTHONPATH`, and I
confirmed that `respec.__file__` pointed at the archive. These are the failures:

- partway: "the adopted content was deleted";
- "cannot switch" message;
- backup not mentioned;
- copy mode: the original is still recorded in `state.json` as installed;
- occupied path: the profile copy is gone.

## Data-safety scenarios (real CLI, temp `HOME`/`RESPEC_HOME`/`RESPEC_USER_HOME`)

The setup is an active profile `two` on `claude-code` and `agents`. To make the
relink fail partway, `~/.agents/skills` is `chmod 555` (empty). The CLI ran
through a small driver that can apply a monkeypatch before `respec.cli.app()`.
Each run used a fresh tree. A snapshot (paths, link targets, sha1 of each file)
was taken before and after.

| Scenario                                                                                                                                                                       | Result                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **B3 exact**: `adopt --add foreign` (nested `sub/x.txt`), agents read-only                                                                                                     | rc 1 ("did not complete"). `foreign` is back as a real folder with every file, and its bytes are identical. `profile.yaml` is byte-identical. `state.json` has no record for it. `grep precious` finds the original. **Fixed.**                     |
| Symlink original (relative `lnk -> ../../../ext/real`) together with a folder                                                                                                  | Both are back. `lnk` is a symlink with the same relative target, and the target is untouched. The only snapshot difference is in `state.json`, where `active_profile` is null. That comes from the pre-existing partial-switch behavior.            |
| Copy mode (`os.symlink` refused for profile sources), folder and symlink entries                                                                                               | The folder is recognized by digest and kept as the original. Its state record is dropped, and the profile copy and entry are removed. `lnk` is recreated as a symlink. A later `use two --unknown keep` leaves `foreign` in place with its content. |
| Path occupied by unrelated content (respec's link replaced by another folder after the failure)                                                                                | The profile copy is kept and listed as `enabled: true`. The error names the copy's path. The unrelated content is untouched. A later `use` refuses ("already exists and is not managed"). Nothing is lost.                                          |
| Failure in the middle of moving back (A): the profile `skills/` dir is made read-only before rollback, so `rename` fails and `shutil.move` falls back to `copytree` + `rmtree` | The original is restored completely (all 3 files). The profile copy is left as an **empty** folder, because `rmdir` failed. See N1: no data is lost, but the note is misleading.                                                                    |
| Failure in the middle of moving back (B): as in A, plus one file in the copy is unreadable, so `copytree` fails partway                                                        | The original is partial (2 of 3 files). The profile copy is complete and kept, and the note points at it. Nothing is lost.                                                                                                                          |
| Refusal before any change (`switch.use` patched to raise `SwitchBlocked`), with a hand comment in the yaml, a folder and a relative symlink                                    | The snapshot is **identical**. The yaml is byte-exact with the comment, `state.json` is identical, and the link target is the same.                                                                                                                 |

## Earlier blockers (no regression)

These checks used a conflicted active profile: `layers.design-principles.skills: [a, b]`
plus a hand comment.

- **No-change refusals.** Each of these exits 1 and leaves the snapshot
  unchanged:
  - `adopt --add foreign`, `--json` and `--all add` (now worded "cannot adopt
    into profile 'two'");
  - `use two`, `add`, `remove c` and `disable c`;
  - `layer on design-principles`.
- **Still allowed.** `adopt --keep foreign` succeeds.
- **Round-3 B2 (layer on/off).** Each case behaves correctly:
  - `layer off output-style` and `layer on output-style` succeed and warn;
  - `layer off design-principles` succeeds;
  - `layer on design-principles` refuses with its own `(a, b)` message.
- **Inactive layer repair (`items:` fallback).** An inactive profile written
  with `items: [x, y]` warns. `layer repair design-principles -p other --keep y`
  then succeeds and rewrites the profile with the `skills:` key.

`profile install` and `update` were not retested. Neither `sources.py` nor
`profiles.py` changed in c044824..46aea65, and round 3 verified both.

## Review of the invariant (`src/respec/adopt.py` `_put_back` / `_undo_adds`)

The profile copy is deleted only in two cases:

- `_put_back` returned True after verifying the original: a moved real folder
  with the copy gone, an identical digest, or the same `readlink`;
- `shutil.move` itself removed the copy's contents after a complete `copytree`
  to the original (N1).

Every exception or False result keeps the copy, together with its profile
entry. A symlink original's target is never touched. `add_local` copies the
link target (resolving it), so the copy holds real content. No path was found
in which the only copy is lost.

## Blocking findings

None.

## Non-blocking findings

- **N1. A cleanup failure during `shutil.move` leaves an empty profile copy and
  a misleading note.**
  - Location: `adopt.py` `_put_back`, the
    `shutil.move(str(copy), str(original))` call, and its handling in
    `_undo_adds`.
  - Scenario: `rename` fails, for example when `RESPEC_HOME` is on another
    filesystem or the profile `skills/` folder is not writable. `move` then
    copies to the original and runs `rmtree(copy)`, and that `rmtree` fails
    partway.
  - Result: the original is complete. However, `_undo_adds` reports "its
    content is kept in profile 'two' at …/skills/foreign", and that folder is
    empty or partial. The profile lists it as `enabled: true`, and `state.json`
    still records the original as respec's symlink, so `status` shows "replaced
    a managed skill".
  - Impact: no data is lost, but the message could lead a user to delete the
    complete original. The trigger is rare.
  - Suggested fix: after an exception, check whether the original's digest
    matches the copy's (or treat the original as restored when the copy is
    gone or empty), and word the note to match.
- **N2. Rollback after a partial move (scenario B) leaves a partial folder at
  the original path.** This is safe, because the full copy is kept and named.
  The note could add that the partial original can be discarded.
- **N3. Restored folders lose their internal symlinks.** `items.add_local`
  calls `shutil.copytree` without `symlinks=True`, so a symlink inside an
  adopted folder becomes a regular file in the profile copy. A rollback then
  restores that dereferenced copy. The bytes are kept, but the structure is
  not exact. This is pre-existing `add_local` behavior and outside fix-5.
- **N4. If `_undo_adds` itself raises, for example when `save_profile` fails,
  the original switch error is masked.** The data is still safe.
- **N5 (carried over, pre-existing).** After a partial switch failure, no
  profile is active, and backups taken in the same run are reported but not
  undone. This is documented in impl-5.

## Scope and tests

- The changes stay within fix-5's acceptance scope (6: a refused or failed
  adopt never partly applies and never loses data).
- The new tests are behavioral: real exit codes, file contents, `state.json`
  and the yaml. They use `chmod 555` to cause a real partial failure. The
  copy-mode and occupied-path tests use monkeypatches.
- There are no source-text or mirror assertions.
- The `two_targets` fixture restores permissions at teardown.
