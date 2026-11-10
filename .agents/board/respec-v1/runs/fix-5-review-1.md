# fix-5 review 1: layer exclusivity repair and the `skills:` key

- Reviewer: fresh, independent, read-only (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Diff: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb..da670cb1d7060be0c247ff564cf8af44df040173`
- Verdicts: spec-compliance **FAIL** (2 blocking), code-quality **PASS**, tests-rerun
  **PASS**

## Gates rerun (head da670cb)

| Gate                                                  | Result                                       |
| ----------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                    | `Audited 27 packages`                        |
| `uv run pytest -q`                                    | `261 passed in 48.48s`                       |
| `uv run black --check src tests`                      | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md`                    | `All matched files use Prettier code style!` |
| Red check: new tests against base `src` (git archive) | `23 failed` for the intended reasons         |

The red check ran the head `tests/test_layer_repair.py` against the base `src`
(extracted to scratch). All 23 fail: `skills` is an unknown layer key, the warning is
absent, and `repair` does not exist. This confirms the red-first claim.

## Real CLI reproduction (temp homes, `RESPEC_HOME`/`RESPEC_USER_HOME`)

Setup: an active profile `work` with skills a, b and c, all linked. A hand edit set
`layers.design-principles.skills: [b, a]`.

- `status`, `profile show work`, `layer list` (text): exit 0, normal stdout, one
  `warning: layer 'design-principles' of profile 'work' is exclusive but has 2 enabled
skills (b, a); fix it with 'respec layer repair design-principles -p work' (keeps 'b')
or ... --keep <skill>'` on stderr. Criterion 1 holds.
- The same commands with `--json` give stdout that parses with `json.load`. It holds a
  structured `warnings` entry (profile, layer, skills, message, fix). The warning is on
  stderr only, so `--json` stdout is never corrupted.
- `use work` and `use work --json`: exit 1, a single error with no duplicated warning,
  and empty stdout. Empty stdout on a `--json` failure is the existing `_fail`
  convention, not a regression. Links, state and yaml are unchanged; the test confirms
  this byte-for-byte. Criterion 3 holds.
- `layer repair design-principles --keep a --json`: keeps a, `disabled: ["b"]`, unlinks
  b, `warnings: []`.
- `layer repair design-principles </dev/null` (non-interactive): keeps the first
  listed skill (b) and disables a.
- Interactive repair under a real pty (python `pty.fork`): it lists `1. b`, `2. a`. The
  answer `x` is re-asked and `2` keeps a. Criterion 2 holds.
- `--keep c` (c is not conflicting) gives `error: cannot keep 'c' ...` and exit 1.
- Repair on a layer with no conflict gives `Nothing to repair`, exit 0, and no write.
- A legacy `items: [b, a]` loads and warns. Read-only commands leave the file
  byte-identical. A write rewrites the key as `skills:`. Having both keys is an error:
  `layers.design-principles: has both 'skills' and the legacy 'items' key`. Messages
  say `layers.<name>.skills`. Criterion 4 holds.
- `grep -i item` over `--help`, `layer --help` and `layer repair --help` returns
  nothing.

## Blocking findings

### B1. `layer on` error points to a repair that does nothing and says something false

- Location: `src/respec/layers.py` `set_active` (`problems =
profiles.exclusivity_problems(after)`), with `profiles.LayerConflict.message` and
  `layers.repair`.
- Scenario: in profile `work`, turn `design-principles` off, add a and b, and keep
  both enabled. Then run `respec layer on design-principles`. The error says
  `... fix it with 'respec layer repair design-principles -p work' (keeps 'a') ...
(disable the others first)`. Running that command gives `Nothing to repair in layer
'design-principles' of profile 'work': at most one skill is enabled`. It exits 0, and
  two skills are still enabled.
- Cause: the new message always recommends `layer repair`. `exclusivity_conflicts` only
  counts layers that are on, so repair sees no conflict while the layer is off. The
  "nothing" text also claims "at most one skill is enabled", which is false here.
- Impact: this is a regression from the base message (`keep at most one enabled`). A
  user or agent who follows the printed fix gets a success exit and no change. The
  user can only escape by guessing `disable`.
- Suggested fix: in `set_active`, give a message without the repair hint (for example
  `use 'respec layer use <layer> <skill>'` or disable the others). Alternatively, let
  repair work on an inactive exclusive layer when it is called explicitly. Reword the
  "nothing" text to be accurate.

### B2. A command that resolves the conflict still reports it, including in JSON `warnings`

- Location: `src/respec/cli.py` `_print_json` and `_print_warnings`, which read the
  load-time collector in `profiles._warnings`. Only `layers.repair` calls
  `discard_warning`.
- Scenario: with the conflict `[b, a]` active, run `respec disable a` or
  `respec layer off design-principles --json`. Both succeed and remove the conflict.
  Each still prints the stale `warning: ... has 2 enabled skills (b, a)` to stderr. The
  JSON payload of `layer off` also carries
  `"warnings": [{"layer": "design-principles", "skills": ["b","a"], ...}]`.
- Impact: the structured `warnings` field (criterion 1) is wrong after a successful
  fix. An agent that parses the JSON will see an unresolved conflict and run
  `layer repair`, which answers "Nothing to repair". The text warning tells a human to
  repair something already fixed.
- Suggested fix: when a profile is saved, drop its recorded conflicts and record its
  fresh ones (for example in `save_profile`, or in `items.commit` after success). The
  output then reflects the state after the command.

## Non-blocking findings and judgments

- N1. `enable`/`disable` on an unrelated skill is refused while the active profile is
  conflicted. Reproduced: `enable d` and `disable c` (neither in the layer) exit 1
  with the switch refusal and "Profile 'work' was left unchanged." Changes that
  resolve the conflict (`disable a`, `layer off`, `layer use`, `repair`) succeed. The
  rule is "no refresh may produce a conflicted install", and it is coherent: the
  refusal names the exact fix, and the refresh goes through `switch.use` like `use`.
  I judge it reasonable and conservative for v1, given decision 10 and the "warn, offer
  repair" scope. The current links already contain the conflict, so a later
  improvement could allow a refresh that does not touch the conflicted layer. That is
  a product decision, not a defect.
- N2. A refused write rewrites a legacy file. In a profile with `items:` and an active
  conflict, `layer add-skill design-principles c` is refused and says "Profile 'work'
  was left unchanged". The rollback (`items.commit` → `save_profile(before)`) has
  already rewritten the file as `skills:`, with key order normalized. The content is
  equal, so no data is lost. Still, "migration happens only on a successful save" is
  not strictly true. The rollback via `save_profile` predates this diff.
- N3. `"warnings": []` is now in every object `--json` payload, success and repair
  alike, and it is consistent across the commands tried (`status`, `profile show`,
  `profile list`, `layer list`, `layer *`, `enable`). List payloads such as
  `restore --list` do not get it, and nothing documents that exception. The README
  says warnings appear "in a `warnings` field of `--json` output" but does not say the
  field is always present, or that `layer` change payloads gained `disabled`. Add one
  sentence to the README or the shipped respec skill reference.
- N4. The TUI does not show warnings. TUI loads no longer fail on a conflict, and a TUI
  switch is refused with the same message. The collector is process-global, and with
  `ctx.call_on_close`, conflicts collected during a TUI session are printed to stderr
  after the TUI exits. This is acceptable until ticket 011's Sync action covers it.
- N5. `_fail` removes duplicates by substring (`conflict.message in str(error)`). That
  works but is fragile. It is acceptable.
- N6. `switch.py` changes by 11 lines, which overlaps with fix-6. The merge risk is
  noted by the implementer.

## Scope

The changes are within fix-5: profile parsing, CLI warnings, `layer repair`, the `use`
refusal, the `skills:` key, the `SkillChange`/`_check_accepts_skills` renames, and the
README. The tests are behavioral, CLI-level, and use independent expectations. None
assert on source text.
