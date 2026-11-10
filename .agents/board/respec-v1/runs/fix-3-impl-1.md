# fix-3 implementation 1: rename "item" to "skill"

- Status: DONE
- Branch: `codex/respec-v1-fix-3`. Base `1d8ef84`, head `47cc4e5`.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-3`

## Changes

- `src/respec/cli.py`: the argument is now `skill` (help "Skill name.") for
  `remove`, `enable`, `disable`, `layer use`, `layer add-skill` and
  `layer remove-skill`. `update [skill]` is renamed the same way. Docstrings,
  option help, and human output all say skill now: `use` counts, `status`
  "(no managed skills)", `layer show` "Skills:", the layer change messages,
  restore "respec skills", `update` "no skills with a source", and the
  `profile install` count. The unknown-entry prompt is updated too.
- `src/respec/items.py`, `layers.py`, `sources.py`, `switch.py`,
  `restore.py`, `profiles.py`: the error and success messages say skill.
  JSON fields are renamed:
  - `ItemChange.item` → `skill`
  - `LayerChange.item` → `skill`, and the actions are now `add-skill` and
    `remove-skill`
  - layer `list`/`show` `items` → `skills`
  - `status` folder `items` → `skills`
  - add-from-git `items` → `skills`
  - `update` and `update --check` `items`/`item` → `skills`/`skill`

  `layers.add_item` and `remove_item` are renamed to `add_skill` and
  `remove_skill`. This was a trivial, local change.

- `src/respec/tui.py`: "no managed skills", "replaced a managed skill", and
  "replaced a skill respec installed".
- `README.md`: all uses of "item" now say skill, and the example uses
  `layer add-skill`.
- Tests are updated to the new keys, messages and commands. New
  `tests/test_help.py`.

### Renamed subcommands (no aliases)

- `respec layer add-item` → `respec layer add-skill`
- `respec layer remove-item` → `respec layer remove-skill`

### Persisted keys

None changed. The layer `items:` key in `profile.yaml` stays as it is. The
README does not document it; only internal module docs mention it. The schema
errors that quote that literal key, such as `layers.x.items must be a list of
skill names`, still name the key. Keys in `state.json` and the backup
`manifest.json` are not affected.

## Criterion → evidence

1. User-facing strings say skill. Evidence: `tests/test_help.py` and the
   updated message assertions in `tests/test_layers.py`. These include
   "accepts no skills". A grep of `src` finds no user-facing "item" strings
   left, apart from the `.items` key quoted in schema errors.
2. JSON keys are `skill`/`skills`. Evidence: `test_items.py` (`"skill": "tdd"`),
   `test_layers.py` (`skills`), `test_use_status.py` and `test_adopt.py` (status
   `skills`), and `test_sources.py` (`skills`/`skill` rows).
3. Subcommands are renamed. Evidence: `test_layers.py` and `test_adopt.py` run
   `layer add-skill`. `test_help.py` checks that `("layer", "add-skill")` is in
   the command tree and checks the usage of `layer add-skill` and
   `layer remove-skill`.
4. Internal churn is minimal. `ItemChange`, `items.py`, the local `item`
   variables and the internal `Layer.items` field are kept.
5. `test_no_help_page_says_item` walks the CLI's command tree and runs
   `--help` for the root and every subcommand. It asserts that no output
   contains "item" in any case. `test_skill_arguments_are_named_skill_in_usage`
   checks that each usage line names `skill`. Red/green: against the base
   `src`, run from a scratch copy, the scan listed offenders for 18 pages,
   and `remove` usage was `{item}`. On HEAD both tests pass.
6. Full suite: 238 passed. That is 236 existing tests plus the 2 new ones.

## Verification

- `uv sync --frozen` → ok
- `uv lock --check` → "Resolved 28 packages"
- `uv run pytest -q` → `238 passed in 45.06s`
- `uv run black --check .` → "28 files would be left unchanged"
- `npx prettier --check README.md` → "All matched files use Prettier code
  style!"

## Concerns

- The spec and ticket files still say "item". The task said to leave them
  alone.
- Schema errors for `profile.yaml` still print the literal key, as in
  `layers.<name>.items`. They have to, because the on-disk key is unchanged.
  Renaming it to `skills:` with a fallback read of the old key would be a
  separate decision.
