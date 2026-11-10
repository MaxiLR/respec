# fix-5 review 4: layer exclusivity repair and the `skills:` key

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Diff: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb..c044824d1e01a1b699b39e57988fff725725317c`
  (da670cb, a50e03d, f38b0d6, c044824)
- Verdicts: spec-compliance **FAIL** (1 blocking), code-quality **FAIL** (the same
  defect), tests-rerun **PASS**

## Gates rerun (head c044824, clean tree)

| Gate                                               | Result                                                |
| -------------------------------------------------- | ----------------------------------------------------- |
| `uv sync --frozen`                                 | `Audited 27 packages`                                 |
| `uv run pytest -q`                                 | `276 passed in 46.97s`                                |
| `uv run black --check src tests`                   | `29 files would be left unchanged.`                   |
| `npx prettier@3 --check README.md`                 | `All matched files use Prettier code style!`          |
| `grep -i item` over `--help` of all 29 commands    | no match                                              |
| Red check: round-4 tests against the f38b0d6 `src` | all 6 new tests fail for the intended reasons (below) |

Red-check failures on f38b0d6: both adopt tests fail because `foreign/SKILL.md`
was deleted; the four layer on/off tests fail with "cannot turn layer
'output-style' on: layer 'design-principles' ...", or blame the other layer
('mine').

## Latest blockers (real CLI, temp `HOME`/`RESPEC_HOME`/`RESPEC_USER_HOME`)

Setup: active `work` (claude-code; a, b, c linked), inactive `imp` (agents;
a, b, c). Both were hand-edited to `layers.design-principles.skills: [a, b]` plus a
`# hand note` comment. The whole tree was snapshotted (paths, link targets,
sha1 of each file) before and after.

- **Round-3 B1 is fixed.** `adopt --add foreign`, `--json`,
  `--add foreign --add lnk` (symlink entry), `--add foreign -p work`, `--all add`
  and `--add foreign --backup other` all exit 1 with the repair hint. The
  snapshot is identical: `~/.claude/skills` is unchanged, `profile.yaml` is
  byte-identical (comment kept) and `state.json` is unchanged. A backup in the
  same call is not applied either. `adopt --keep foreign`, `adopt --add foreign -p
imp` and `adopt --backup other` still succeed.
- **Round-3 B2 is fixed.**
  - `layer off output-style` succeeds and warns about design-principles. This
    holds for the active profile, for `-p imp` and with `--json`
    (`warnings` is structured).
  - `layer on output-style` succeeds and warns.
  - `layer on design-principles` fails with its own `(a, b)` message.
  - `layer off design-principles` succeeds with no warning.
  - The unit test with two conflicted layers passes.

## Mutating-command matrix (conflicted active `work`; fresh setup per command)

`changes` counts the snapshot diff lines.

| Command                                                | rc  | changes | Note                            |
| ------------------------------------------------------ | --- | ------- | ------------------------------- |
| `add <d>`, `remove c`, `disable c`                     | 1   | 0       | switch refusal; nothing changed |
| `layer add-skill design-principles c`                  | 1   | 0       | switch refusal                  |
| `use work`, `use imp`                                  | 1   | 0       | refuses                         |
| `layer enable design-principles`, `layer rm d-p`       | 1   | 0       | their own errors                |
| `layer on design-principles`                           | 1   | 0       | its own conflict                |
| `enable c` (no-op), `layer on output-style` (no-op)    | 0   | 0       | warns                           |
| `disable a`, `layer use d-p a`, `layer disable d-p`    | 0   | 5-6     | resolves the conflict; relinks  |
| `layer remove-skill d-p a`, `layer repair --keep b`    | 0   | 2-5     | resolves                        |
| `layer add mine`, `layer off output-style` / `d-p`     | 0   | 2       | yaml only                       |
| `update` (no sources); `enable c -p imp`; `off -p imp` | 0   | 0-2     | warns                           |

Every refusal changed nothing. `update` with a real upstream change, and `profile
install`, were verified in round 3. c044824 does not touch `sources.py` or
`profiles.py`, so I did not repeat those. `restore --unknown add` adds to the
profile without relinking, so it cannot be refused by a conflict.

## Forced rollback (`_undo_adds`)

- **Pre-change refusal: rollback is correct.** `switch.use` was monkeypatched to
  raise `RespecError` before it changes anything. `adopt --add foreign --add lnk`
  (a folder and a symlink) left the snapshot identical: the folder was copied
  back, the symlink was recreated with the same target, and the yaml and
  `state.json` were identical.
- **Mid-switch failure: data is lost.** This is a real `OSError` while
  `switch.use` is installing. See B3.

## Blocking findings

### B3. `_undo_adds` deletes the only copy of an adopted folder when the relink fails partway

- **Location:**
  - `src/respec/adopt.py` `_undo_adds`, which runs
    `if not os.path.lexists(original): ...` and then
    `shutil.rmtree(copy, ignore_errors=True)` unconditionally.
  - `adopt`, which runs `except RespecError: _undo_adds(...)`.
- **Why it happens:**
  - `switch.use` turns an `OSError` during installs into a `RespecError`
    ("switch to profile 'work' did not complete ...").
  - By then it may already have linked the adopted skill at the original path.
  - `_undo_adds` sees that `original` exists (it is respec's new link to the
    profile copy), so it puts nothing back.
  - It then deletes the profile copy, which is the only remaining copy of the
    user's data.
- **Scenario (real CLI, reproduced):**
  1. Use a non-conflicted active `work` with targets `claude-code, agents`.
     Make `~/.agents/skills` empty and `chmod 555`.
  2. Create `~/.claude/skills/foreign/SKILL.md` containing `precious`.
  3. Run `respec adopt --add foreign`. It exits 1 with "switch to profile 'work'
     did not complete: ... Permission denied".
  4. Afterwards `~/.claude/skills/foreign` is a dangling symlink to
     `profiles/work/skills/foreign`, which no longer exists.
     `profile.yaml` no longer lists it, and `state.json` records the dangling
     link as installed.
  5. `grep -r precious` over the whole temp tree finds nothing.
  - The same run against the f38b0d6 sources keeps
    `profiles/work/skills/foreign/SKILL.md`.
  - In copy mode (symlinks refused) the copy at the original path survives, but
    it is recorded as respec-installed, so the next `respec use` deletes it.
- **Impact:**
  - Permanent loss of user skill content, introduced by c044824.
  - It breaks adopt's documented invariant: "An original is only removed after
    its copy ... is complete, so nothing is lost".
  - The trigger is uncommon (an I/O or permission failure during the relink).
    After the early guard, though, this is the main way `_undo_adds` can be
    reached.
- **Suggested fix:**
  - Run `_undo_adds` only for refusals raised before any change (for example,
    catch `SwitchBlocked` only).
  - Otherwise, never delete the profile copy unless the original was put back.
    If `original` is respec's link or copy of `copy`, remove it first, then
    restore. Otherwise keep the copy and the profile entry.
  - Add a test that fails the relink with an `OSError` after the adopted skill
    is linked, and asserts that the content still exists.

## Non-blocking findings

- **N1. A forced refusal does not undo backups taken in the same call.**
  With `adopt --add foreign --add lnk --backup other` and a refusing
  `switch.use`, `other` stays moved to `backups/` and its state change is kept.
  - The data is safe, so this is only a partial apply.
  - It cannot be reached through a conflict, because the early guard refuses
    first.
- **N2. A failure later in `resolve` leaves earlier adds applied (pre-existing).**
  Example: `adopt --add foreign --add zed`, where `zed` is a replaced entry
  whose name is already in the profile.
  - `foreign` is copied into the profile and removed from the folder, but not
    linked.
  - The behavior is the same at base, the data is kept, and it is outside
    fix-5's scope.
- **N3. The adopt refusal is worded as "cannot switch to profile 'work':".** The
  repair hint is correct, but the wording reads oddly for `adopt`. It is
  consistent with `add`/`remove`.
- **N4. `layer on`/`off` now save without a switch refresh.** Correct, because
  the change never alters which skills are enabled. JSON reports
  `linked: []`/`unlinked: []`. A no-op `on` does not rewrite the file:
  `loaded_text` uses `compare=False`.
- **N5. The upfront `decide` pass asks every prompt before applying any of
  them.** The prompt order is unchanged. Earlier rounds' N-items (TUI shows no
  warnings, README wrap) are unchanged.

## Scope and tests

The changes stay within fix-5. The new tests are behavioral: CLI exit codes,
file bytes and YAML. The rollback test monkeypatches `switch.use`, which is
acceptable, but it only covers a refusal before any change. That is why it
misses B3. There are no source-text assertions.
