# fix-5 review 3: layer exclusivity repair and the `skills:` key (final round)

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Diff: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb..f38b0d6e30e86de191255a7d81e4d1b7c30ba675`
  (da670cb, a50e03d, f38b0d6)
- Verdicts: spec-compliance **FAIL** (2 blocking), code-quality **FAIL** (the same
  two defects), tests-rerun **PASS**

## Gates rerun (head f38b0d6)

| Gate                                                 | Result                                            |
| ---------------------------------------------------- | ------------------------------------------------- |
| `uv sync --frozen`                                   | `Audited 27 packages`                             |
| `uv run pytest -q`                                   | `270 passed in 50.59s`                            |
| `uv run black --check src tests`                     | `29 files would be left unchanged.`               |
| `npx prettier@3 --check README.md`                   | `All matched files use Prettier code style!`      |
| `grep -i item` over `--help` of every command        | no match                                          |
| Red check: head tests on the a50e03d tree (scratch)  | the 3 new round-3 tests fail for intended reasons |
| 007 subset (`-k inject/symlink/option/file_url/...`) | `20 passed`                                       |

Red-check failures on a50e03d: `disabled` was `[]`; the edited copy's targets were
rolled back to `claude-code`; install stderr was `''`.

## Command matrix (real CLI, temp `RESPEC_HOME`/`RESPEC_USER_HOME`)

Setup per case, built fresh: active `work` (claude-code; skills a, b, c, linked), an
inactive `imp` (agents; a, b, c) and an inactive `other`. A hand edit set
`layers.design-principles.skills: [a, b]` in both `work` and `imp`. Every command was
run in text and with `--json`. "Warns" means one `warning:` line on stderr and a
matching `warnings` entry in parsed JSON stdout.

| Command                                                                    | Result                                                                                                      |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `status`                                                                   | rc 0, warns                                                                                                 |
| `use work`                                                                 | rc 1, refusal names the repair, empty stdout, nothing changed                                               |
| `use other`                                                                | rc 0, `warnings: []` (`work` is not read; acceptable)                                                       |
| `profile new zz`                                                           | rc 0, `warnings: []` (a new profile cannot conflict)                                                        |
| `profile list` / `profile show work` / `profile show imp`                  | rc 0, warns (list warns for both)                                                                           |
| `profile install` (legacy `items:` source, `file://` remote)               | rc 0, warns in text and JSON; written as `skills:`; later `use imp` refuses. **Round-2 B1 fixed.**          |
| `add` / `remove` / `disable c` on active `work`                            | rc 1, switch refusal + "left unchanged"; yaml, links, skills folder unchanged                               |
| `add -p imp`, `remove -p imp c`, `disable -p imp c`                        | rc 0, warns                                                                                                 |
| `enable c` (no-op) / `disable a` / `disable -p imp a`                      | rc 0; warns / `[]` / `[]` (the last two resolve the conflict)                                               |
| `add me/sk2` (git) on active; `add -p imp me/sk2` (git)                    | rc 1 + byte-identical yaml / rc 0 warns, written as `skills:`                                               |
| `update`, `update -p imp`, `update --check --json`                         | rc 0, warns                                                                                                 |
| `update` with a real upstream change, active conflicted                    | rc 1, refusal; yaml byte-identical (legacy `items:` + `# hand note` kept), state and skill folder identical |
| `layer list` / `show` (active and `-p imp`)                                | rc 0, warns                                                                                                 |
| `layer add mine --exclusive -d x` (and `-p imp --additive`)                | rc 0, warns                                                                                                 |
| `layer rm`, `layer enable design-principles`, `use/add-skill output-style` | rc 1 with their own (correct) errors, and the warning is still printed                                      |
| `layer use design-principles a` (active, `-p imp`)                         | rc 0, `warnings: []`, `disabled: ["b"]`; text prints `disabled 'b'`. **Round-2 N1 fixed.**                  |
| `layer add-skill design-principles c` active / `-p imp`                    | rc 1 switch refusal / rc 0 warns, prints `disabled 'c'`                                                     |
| `layer remove-skill`, `layer disable design-principles`                    | rc 0, `[]` (conflict resolved), `disabled` lists a, b                                                       |
| `layer disable output-style`                                               | rc 0, warns                                                                                                 |
| `layer on design-principles`                                               | rc 1, names the repair                                                                                      |
| `layer off design-principles` (active and `-p imp`)                        | rc 0, `[]`                                                                                                  |
| `layer off output-style` (active and `-p imp`)                             | **rc 1, "cannot turn layer 'output-style' on: ..."** (B2)                                                   |
| `layer repair` (default, `--keep b`, `-p imp --keep b`)                    | rc 0, `[]`, correct `disabled`, active one unlinks the dropped skill                                        |
| `layer repair output-style`                                                | rc 0, "Nothing to repair", still warns about design-principles                                              |
| `adopt` (no unknowns / unknowns, no choice)                                | rc 0, `[]` (no profile read)                                                                                |
| `adopt --keep foreign`                                                     | rc 0, `[]`                                                                                                  |
| `adopt --add foreign -p imp`                                               | rc 0, warns                                                                                                 |
| `adopt --add foreign` into the active conflicted `work`                    | **rc 1, refused, but partially applied** (B1)                                                               |
| `restore`, `restore --list`                                                | rc 0, `[]` / bare list (no profile read; as documented)                                                     |
| `restore --unknown add` (backup present, `pre` unknown)                    | rc 0, warns in text and JSON                                                                                |

## Rollback of an edited copy

Through the library: `load_profile(imp)` has `loaded_text`; `dataclasses.replace(p,
targets=[...])` and `with_enabled(...)` both have `loaded_text=None`.
`restore_profile(copy)` writes the copy's data; `restore_profile(loaded)` restores
the original bytes exactly. A copy re-pointed at another profile's path therefore
cannot carry the other profile's bytes. **Round-2 N2 fixed.** `_write` is now shared
(N3 fixed).

## 007 rollback and security

`sources._forget` and `sources._restore` now call `restore_profile` with the profile
as loaded; folder move-back order unchanged. No change to `parse_spec`,
`copy_fetched`, `_within` or `inside`. The 007 subset and the full suite pass. The
real-CLI refused `update` restored yaml, state and the replaced skill folder
byte-for-byte. Install still validates against the fetched file and removes the
destination on failure (a removed folder is simply skipped by `peek_warnings`). No
regression found.

## Blocking findings

### B1. A refused `adopt --add` into the active conflicted profile is partially applied

- Location: `src/respec/adopt.py` `_add` (about lines 75–80: `items.add_local`, then
  `_delete(entry.path)`, then `_settle`) and `adopt` (about lines 160–166:
  `switch.use(...)` after `resolve`, with no rollback). The diff exposes it:
  `profiles.load_profile` no longer fails on a conflict, and
  `switch._refuse_layer_conflicts` now refuses only at the final `switch.use`.
- Scenario: active `work` with the hand-edited conflict; an unknown folder
  `~/.claude/skills/foreign`. `respec adopt --add foreign` (and `--json`) exits 1 with
  "cannot switch to profile 'work': ...". Afterwards:
  - `~/.claude/skills/foreign` is gone (deleted by `_delete`);
  - `profiles/work/skills/foreign` exists and `profile.yaml` gained
    `foreign: {enabled: true}` (cmp differs);
  - nothing links it, `state.json` is unchanged; JSON stdout is empty.
    At base f6296447 the same scenario (with `items:`) failed at load and left
    `~/.claude/skills/foreign` and the profile untouched.
- Impact: violates criterion 3/4's rule that a refused command changes nothing and
  restores the exact bytes. The user's skill silently disappears from the agent's
  folder, while the error suggests a no-op refusal. Every other active-profile write
  (`add`, `remove`, `disable`, `update`, `layer add-skill`, `layer repair`) rolls back
  and says "left unchanged"; adopt does not. Data is recoverable (it sits in the
  profile and is linked after `layer repair`), but the state is inconsistent.
- Suggested fix: when any entry is added to the active profile, check
  `profiles.exclusivity_conflicts(load_profile(active))` before `resolve` runs and
  refuse up front, or undo the add (remove the copied folder, `restore_profile` the
  loaded profile, put the entry back) when `switch.use` raises. Add a CLI test:
  conflicted active profile + unknown folder, `adopt --add` fails, the folder and
  `profile.yaml` bytes are unchanged.

### B2. `layer off` / `layer on` of one layer is refused because of another layer's conflict, with the wrong verb

- Location: `src/respec/layers.py` `set_active` (about lines 268–275):
  `problems = profiles.exclusivity_problems(after)` checks every layer and always
  raises `cannot turn layer {name!r} on: ...`.
- Scenarios:
  - `respec layer off output-style` (active `work`) and `respec layer off
output-style -p imp` (inactive): rc 1, "error: cannot turn layer 'output-style'
    on: layer 'design-principles' ... exclusive but has 2 enabled skills".
  - Inactive `imp` with two conflicted exclusive layers (`design-principles: [a,
b]`, custom `mine: [c, d]`): `layer off design-principles -p imp` and `layer off
mine -p imp` both fail, each blaming the other layer, each saying "turn ... on".
    `layer on output-style -p imp` fails the same way.
- Impact: criterion 1 says commands warn on a conflicted profile instead of failing;
  every other write to an inactive conflicted profile (`add`, `remove`, `disable`,
  `layer add`, `layer add-skill`, `update`) succeeds and warns. Turning a layer off
  can never create a conflict, and `layer off` is the spec's (decision 10) way to let
  exclusivity lapse, yet here it is refused. The message says "on" for an `off`
  command, which misleads users and agents. Not a deadlock (`layer repair` still
  works).
- Suggested fix: when `active` is False, skip the check; when True, only check the
  conflicts of the layer `name` (e.g. filter `exclusivity_conflicts(after)` by
  `conflict.layer == name`) and leave the rest to the warnings. Add CLI tests for
  `layer off output-style -p imp` on a conflicted profile (succeeds, warns) and for
  the error text.

## Non-blocking findings

- N1. Round-1/2 judgment unchanged: unrelated writes to the active conflicted profile
  (`add d`, `remove c`, `disable c`, `layer add-skill`) are refused by the switch
  preflight, each with "left unchanged" and verified unchanged. Consistent with
  criterion 3; documented behavior is acceptable.
- N2. `use other` from a conflicted active `work` returns `warnings: []`; `work` is
  not read, which matches the README contract.
- N3. README line "installs the profile warns on stderr, and `respec use` refuses the
  profile. The warning reflects the" is longer than the surrounding wrap. Prettier
  passes (prose wrap preserved); cosmetic.
- N4. `layer disable <group>` now prints one `disabled '<skill>'` line per skill, as
  the implementer noted; accurate.
- N5. The TUI still shows no warnings (round-1 N4), and `_touched` grows for a TUI
  session without clearing; harmless.

## Scope and tests

Changes stay within fix-5. The three new tests are behavioral (CLI exit codes, parsed
JSON, YAML contents); the edited-copy test drives the library API directly, which
is appropriate for an internal rollback invariant. No source-text assertions.
