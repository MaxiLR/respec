# fix-5 implementation 1: layer exclusivity repair and the `skills:` key

- Status: DONE
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-5`
- Branch: `codex/respec-v1-fix-5`
- Base: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb`
- Head: `da670cb1d7060be0c247ff564cf8af44df040173` (one commit, not pushed)

## Changes

- `src/respec/profiles.py`
  - `parse_profile` no longer fails on exclusivity.
  - New `LayerConflict` (profile, layer, skills, `message`, `fix`) and
    `exclusivity_conflicts()`. `exclusivity_problems()` is kept as a message
    wrapper; `layer on` still uses it.
  - `load_profile` records each conflict in a process-level, deduplicated
    collector. Accessors: `take_warnings()`, `peek_warnings()` and
    `discard_warning()`.
  - Layer member key: reads `skills:`, falls back to the legacy `items:`, and
    errors when a layer has both. It always writes `skills:`. Messages say
    `layers.<name>.skills`. Module docstring schema updated.
- `src/respec/cli.py`
  - The root callback clears the collector and registers
    `ctx.call_on_close(_print_warnings)`. Every command, including failing
    ones, prints `warning: ...` to stderr for each conflict it loaded.
  - `_print_json` adds `"warnings": [...]` (structured dicts) to every
    object payload. It is always present and `[]` when there are none. List
    payloads (`restore --list`) are unchanged.
  - `_fail` drops warnings whose text the error already contains, so the
    `use` refusal is not printed twice.
  - New `respec layer repair <layer> [--keep <skill>] [-p] [--json]`. In a
    terminal it prompts (name or number) and defaults to the first skill.
    Otherwise it keeps the first listed skill. It reports `kept` and each
    `disabled` skill.
- `src/respec/layers.py`
  - `repair()` uses `with_enabled` and then `_apply`, which calls
    `items.commit`. That path is `save_profile` plus the active-profile
    refresh via `switch.use`, so unknown-entry blocking and rollback apply.
    `--keep` must be one of the conflicting enabled skills. With no conflict,
    the action is `nothing` and no write happens.
  - `LayerChange` gained `disabled: list[str]`.
  - `_check_accepts_items` was renamed to `_check_accepts_skills`.
- `src/respec/switch.py` (minimal, 11 lines):
  `_refuse_layer_conflicts(profile)` runs right after the first load in
  `use()`, before unknown-entry handling. It raises `SwitchBlocked` with the
  conflict and the repair hint. Nothing changes on disk.
- `src/respec/items.py`: `ItemChange` was renamed to `SkillChange`.
- `README.md`: Layers section describes `skills:`, the warning, the `use`
  refusal and `layer repair`.
- Tests:
  - New `tests/test_layer_repair.py` with 23 tests.
  - The existing exact-JSON and `["items"]` assertions are updated in
    `test_items.py`, `test_layers.py`, `test_profile_list_show.py` and
    `test_use_status.py`. The updates cover the new `warnings` field and the
    `skills` key.

## Criterion -> evidence

| #   | Criterion                                                                                                    | Evidence (tests/test_layer_repair.py unless noted)                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | No load error; stderr warning names layer, skills, fix; not in `--json` stdout; `warnings` field             | `test_conflict_loads_and_warns_on_stderr[layer list, layer show, profile show, status]`, `test_conflict_json_has_structured_warnings_and_clean_stdout[same 4]`, `test_json_without_conflict_has_empty_warnings`, `test_profile_list_shows_conflicted_profile_as_valid_with_warning`                                                                                                                                                                                 |
| 2   | `layer repair` with `--keep`, TTY prompt, non-interactive first, reports disabled, save + refresh + rollback | `test_repair_keep_disables_the_others_and_relinks`, `test_repair_without_keep_noninteractive_keeps_first_listed`, `test_repair_without_keep_in_terminal_prompts_for_the_skill`, `test_repair_keep_must_be_a_conflicting_skill`, `test_repair_without_conflict_changes_nothing`, `test_repair_of_named_inactive_profile_does_not_touch_targets`, `test_repair_refused_by_switch_preflight_leaves_profile_unchanged` (unknown entry blocks, yaml and links unchanged) |
| 3   | `use` refuses, non-zero, changes nothing                                                                     | `test_use_refuses_conflicted_profile_and_changes_nothing` (state.json, links and profile.yaml byte-identical), `test_use_works_after_repair`                                                                                                                                                                                                                                                                                                                        |
| 4   | `skills:` key; legacy `items:` read; both is an error; always write `skills:`; messages say `.skills`        | `test_layer_writes_use_the_skills_key`, `test_legacy_items_key_is_read_and_rewritten_as_skills`, `test_layer_with_both_skills_and_items_is_an_error`, `test_validation_messages_name_the_skills_key`; existing `test_schema_rejects_bad_layers` still passes on legacy input                                                                                                                                                                                        |
| 5   | Optional rename                                                                                              | Done: `SkillChange`, `_check_accepts_skills`                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 6   | Red-first tests; help has no "item"                                                                          | All 23 new tests failed before implementation, for two intended reasons: `skills` was an unknown layer key, and the `repair` command did not exist. `tests/test_help.py` passes and includes `layer repair --help`.                                                                                                                                                                                                                                                 |

Criteria met: 6/6.

Smoke run in a scratch temp home, with a hand-edited `skills: [a, b]` added to
an active profile:

- `layer list` succeeds and prints this to stderr:
  `warning: layer 'design-principles' of profile 'work' is exclusive but has 2 enabled skills (a, b); fix it with 'respec layer repair design-principles -p work' (keeps 'a') or 'respec layer repair design-principles -p work --keep <skill>'`.
- `use work` exits 1 with the same text and no duplicate warning.
- `layer repair design-principles </dev/null` keeps `a`, prints
  `disabled 'b'` and unlinks `b`. `profile.yaml` then lists
  `skills: [a, b]`, and only `a` is linked.

## Verification (fresh, head da670cb)

| Gate                               | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `261 passed in 50.26s`                       |
| `uv run black --check src tests`   | `29 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

## Concerns

- JSON contract change: every object `--json` payload now carries
  `"warnings": []`, and every layer change carries `"disabled": []`. These
  are additive keys. Consumers that compare exact payloads will see them. I
  chose an always-present field for a stable schema.
- Other commands on an active conflicted profile are also refused when they
  need a refresh, such as `respec enable x` (the switch is refused and the
  profile is rolled back). The refusal carries the repair hint. `layer off`,
  `layer use` and `disable` all resolve the conflict, so they still succeed.
- The TUI does not show the warnings. Its profile loads no longer fail on a
  conflict, and switching from the TUI is refused with the same message. The
  collector grows by at most one entry per profile and layer in a TUI
  process. TUI work was left alone because fix-6 owns that area.
- `switch.py` gains one helper and one call at the top of `use()`. fix-6 also
  edits this file, so a small textual merge is possible.
