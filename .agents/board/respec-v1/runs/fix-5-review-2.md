# fix-5 review 2: layer exclusivity repair and the `skills:` key

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Diff: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb..a50e03df41977ff35ec130bc88234430d4878c70`
  (da670cb plus the round-1 fix a50e03d)
- Verdicts: spec-compliance **FAIL** (1 blocking), code-quality **PASS**, tests-rerun
  **PASS**

## Gates rerun (head a50e03d)

| Gate                                                  | Result                                       |
| ----------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                    | `Audited 27 packages`                        |
| `uv run pytest -q`                                    | `267 passed in 63.83s`                       |
| `uv run black --check src tests`                      | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md`                    | `All matched files use Prettier code style!` |
| Red check: head `test_layer_repair.py` on da670cb src | `6 failed, 23 passed`                        |
| `grep -i item` over `respec --help`                   | no match                                     |

The red check ran the head test file against the da670cb tree (git archive in
scratch). The six round-2 tests fail for the intended reasons. The implementer's
report says "6 failed, 24 passed". I count 29 tests in total (29 passed at head), so
that is a counting slip and not a defect.

## Real CLI reproduction (temp homes, `RESPEC_HOME`/`RESPEC_USER_HOME`)

Setup: an active profile `work` (claude-code) with skills a, b and c, all linked. A
hand edit set `layers.design-principles.skills: [b, a]`.

- **B1 (round 1) is fixed.** Turn the layer off, then run `layer on
design-principles`. It exits 1, names `respec layer repair design-principles -p
work`, and no longer adds the "(disable the others first)" suffix. `layer repair
design-principles </dev/null` on the inactive layer keeps b, disables a and unlinks a
  (links are now `b c`). After that, `layer on` succeeds and `status --json` gives
  `warnings: []`. Repair on an additive layer prints "it is additive" and makes no
  write. Repair on an exclusive layer with one enabled skill prints the accurate
  "at most one skill is enabled".
- **B2 (round 1) is fixed.** `disable a` exits 0 with no stale warning on stderr.
  `layer off design-principles --json` and `layer use design-principles a --json` both
  return `"warnings": []`, and stderr is empty.
- `status`, `profile show work`, `profile list` (text): exit 0, with one warning line on
  stderr. `status --json` and `profile show work --json`: stdout parses as JSON and
  holds the structured entry (profile, layer, skills, message, fix). The warning goes
  only to stderr.
- `use work` and `use work --json`: exit 1, one error, no duplicated warning, empty
  stdout. `profile.yaml` (cmp), `state.json` and the link listing are unchanged.
- Repair modes:
  - `--keep a --json`: `skill: a`, `disabled: ["b"]`, b unlinked, `warnings: []`. The
    file is written as `skills:`. A second run gives "Nothing to repair".
  - `--keep c` and `--keep zz`: `error: cannot keep ...`, exit 1. The remaining
    conflict is still warned (correct, since it is still there).
  - Non-interactive, `--json </dev/null`: keeps the first listed skill (b) and
    disables a.
  - Interactive, under a real pty (`pty.fork`): it lists `1. b`, `2. a`. The answer `x`
    is re-asked and `2` keeps a, disables b and unlinks b. `--json` never prompts
    (`choose` is None when `as_json`).
  - `-p imp` on an inactive profile: `active: false`, keeps b, no link changes.
- Refused repair: the setup is an active conflict, a legacy `items:` key, a trailing
  `# hand note` comment and a foreign folder in `~/.claude/skills`. Then
  `layer repair --keep a` (text and `--json`) exits 1 with the switch refusal and
  "Profile 'work' was left unchanged". The file is byte-identical (cmp, comment and
  `items:` key kept). `state.json` is byte-identical, `ls -la` of the links is
  identical, and no `.profile.yaml.tmp` is left. Nothing deadlocks: `adopt --keep
foreign` works while the profile is conflicted, and repair then succeeds.

## Rollback and 007 security behavior

- `profiles.restore_profile` writes `loaded_text` through the same
  `.profile.yaml.tmp` + `os.replace` path into the same `profile.path` as
  `save_profile`. It adds no new write location and no new input. When `loaded_text`
  is None (for example a profile built by `profile install` via `parse_profile`), it
  falls back to `save_profile`.
- Every call site passes the profile exactly as loaded at the start of the command,
  never a derived copy: `items.commit` (`before` from `layers._load` or
  `_load_with_item`), the `items.add` undo, `items.remove` (`profile`), `sources.add`
  `_forget(before)` (loaded before `add_local` saves) and `sources.update`
  `_restore(profile)` (loaded at the top and never rebound). Restoring the original
  bytes is therefore semantically the same as the old `save_profile(before)`, minus
  the normalization.
- 007's option-injection and symlink checks live in `parse_spec`, `copy_fetched`,
  `_within` and `inside`. This diff does not touch them, and `file://` URLs are still
  refused. In `_restore`, the folder move-back order is unchanged. The existing
  source and install tests pass.

## Blocking findings

### B1. `profile install` of a conflicted profile reports no warning, and its JSON says `warnings: []`

- Location: `src/respec/sources.py` profile install (about lines 665–700: the profile
  is built with `profiles.parse_profile(...)` + `dataclasses.replace(path=...)` and
  written with `save_profile`), together with `src/respec/profiles.py` `_loaded`,
  which only `load_profile` fills. `peek_warnings` therefore never sees the
  installed profile.
- Scenario: a repository whose `profile.yaml` has
  `layers.design-principles.skills: [b, a]` with both enabled. Serve it through
  `RESPEC_GIT_BASE_URL=file://<dir>` as `me/prof`. Then:
  - `respec profile install me/prof --name imp` prints "Installed profile 'imp' ... (3
    skills)", exits 0, and puts nothing on stderr.
  - `--json` returns `"warnings": []`.
  - The installed `profiles/imp/profile.yaml` keeps the conflict. A later `respec use
imp` refuses, and `layer repair -p imp` repairs it.
- Impact: the README contract added by this diff says "every command that reads the
  profile warns on stderr" and that `warnings` reflects "the profile as the command
  left it". Install reads a profile (an externally authored one, which is the most
  likely source of a hand-edited conflict) and creates it locally, yet it gives a
  false negative in both text and structured output. An agent that trusts `warnings:
[]` after an install will hit an unexpected refusal on `use`. This was already
  true at da670cb (round 1 did not cover install).
- Suggested fix: record the installed profile so the post-command reread covers it. For
  example, call `profiles.load_profile(respec_home, name)` after the
  `save_profile(profile)` at the end of install, or expose a small `profiles.track(...)`
  helper. Add a CLI test: install a conflicted profile, then assert the stderr warning
  and the JSON `warnings` entry.

## Non-blocking findings

- N1. `layer use design-principles a --json` reports `"disabled": []` even though it
  implicitly disabled b (b appears in `unlinked`). The `disabled` field on
  `LayerChange` is new in this diff and only `repair` fills it. Either fill it for
  `use`, or document that it is repair-only. (Location: `src/respec/layers.py` `use`
  path; `cli._report_layer_change`.)
- N2. A latent hazard: `loaded_text` survives `dataclasses.replace`, so every derived
  profile (`after`, `with_enabled(...)`, `_with_layer(...)`) carries the original
  bytes. A future `restore_profile(after)` would silently write the old file instead
  of `after`. No current call site does this (verified above). Consider clearing
  `loaded_text` in derived copies, or stating the "only pass the loaded profile" rule
  in the `restore_profile` docstring.
- N3. `restore_profile` repeats the temp-file/replace body of `save_profile`. A shared
  `_write_text(file, text)` helper would keep the single-writer guarantee in one place.
  This is cosmetic.
- N4. Round-1 judgments N1 (unrelated `enable`/`disable` are refused while the profile
  is conflicted), N4 (the TUI shows no warnings) and N6 (switch.py overlaps with
  fix-6) are unchanged and still acceptable. N5's dedup now uses substring matching on
  the printed error text (`_failure`), which works. N2 (a refused write rewrites a
  legacy file) is fixed by `restore_profile` and covered by
  `test_refused_change_restores_legacy_file_bytes`. N3 (README documents `warnings`
  and `disabled`) is fixed.

## Warnings reflect post-command state

`peek_warnings` and `take_warnings` reread every profile that `load_profile` touched
in the command and compute the conflicts from disk. I confirmed this for `disable`,
`layer off`, `layer use`, `layer repair` (all modes), failed `--keep`, refused repair
(the conflict stays and is warned), `status`, `profile show` and `profile list`.
Profiles that are created or installed without `load_profile` are not covered: B1
above (install), while `profile new` cannot produce a conflict. `restore --list
--json` reads no profile, as the README says.

## Scope and tests

The changes stay within fix-5. The extension to `sources.py` touches only the undo
writer, and the brief asked for exactly that. The round-2 tests are behavioral CLI
tests with independent expectations: exit codes, parsed JSON, file bytes and link
listings. None of them assert on source text.
