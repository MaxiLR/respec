# fix-3 review 1: rename "item" to "skill"

- Reviewer: fresh independent reviewer. I did not implement this work.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-3`
- Diff: `1d8ef84d84109d68f642d6cd10a0dcbd8bf3119d..47cc4e5fd916af27999699f8864422992407df8c`
  (HEAD is this commit, and the tree is clean)
- Decision under review: the engineer chose "skill" over "item" in all
  user-facing text, JSON keys, command arguments, help and docs.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking findings: 0

## Rerun evidence (fresh, in the worktree)

- `uv run pytest -q` gave `238 passed in 45.47s`.
- `uv run black --check .` gave "28 files would be left unchanged."
- `npx prettier --check README.md` gave "All matched files use Prettier code
  style!"
- `uv lock --check` gave "Resolved 28 packages".
- Red check for the help test: I exported the base `src` with `git archive`
  to a scratch folder and ran `tests/test_help.py` against it with
  `PYTHONPATH`. I confirmed that `respec.__file__` resolved to the scratch
  copy. Both tests failed:
  - The guard failed because `("layer", "add-skill")` was missing.
  - The `remove` usage was `Usage: root remove [OPTIONS] {item}`.

  On HEAD, both tests pass.

## Acceptance criteria

1. **User-facing strings.** I walked the AST of every module in
   `src/respec/*.py` and listed each non-docstring string literal that
   contains "item". The only hits are:
   - `profile.yaml` schema keys and the errors that quote them (finding N1)
   - an internal scratch directory name, `sources.py:278`
     `Path(scratch) / "item"`. It is a tempdir path, and `_check_links`
     labels symlinks relative to the folder, so users never see it.
   - Textual CSS selectors in `tui.py:55` (`ListItem`), which are not text.

   The CLI help, messages and errors all say skill. So do the TUI labels
   ("no managed skills", "replaced a managed skill") and the adopt dialog
   ("replaced a skill respec installed"). `README.md` has no "item" left.
   Command docstrings, which become help text, are all updated.
   Internal-helper docstrings in `items.py`, `layers.py` and `sources.py`
   still say item. They are not user-facing (criterion 4).

2. **JSON keys.** These are renamed:
   - `ItemChange.skill`
   - `LayerChange.skill`, whose action values are now `add-skill` and
     `remove-skill`
   - layer `list`/`show` `skills`
   - the status folder's `skills`
   - `SourceChange.skills`
   - `UpdateResult.skills`, with each row's `skill`
   - the `update --check` `skills`, with `Row.skill`

   All of these are serialized through `dataclasses.asdict` or built
   explicitly. A grep for `["item"]`, `["items"]` and `.item` in `src` finds
   no consumer left on the old keys. The TUI reads `folder["skills"]`.
   Persisted state (`state.json`, the backup manifest and `profile.yaml`) is
   unchanged, so there was no compatibility risk.

3. **Subcommands.** `layer add-item` and `remove-item` are now `add-skill`
   and `remove-skill`. No aliases remain; the base command tree check shows
   the old names are gone.
4. **Internal identifiers.** Only trivial renames: `layers.add_skill` and
   `remove_skill`, `SkillArgument`, and `_layer_skill_command`.
   `ItemChange`, `items.py` and `Layer.items` are kept. That is acceptable.
5. **Help test.** `tests/test_help.py::test_no_help_page_says_item` builds
   the real Click command tree and runs `--help` through the CLI runner for
   every path. It then checks the rendered output. This is observable
   behavior, not a source-text assertion, and the walk guard stops it from
   passing vacuously. Tests were updated to the new keys, messages and
   commands.
6. **Behavior unchanged otherwise.** The diff only renames strings, keys,
   identifiers and commands. The one non-rename edit is a Black reflow in
   `items.remove`'s `ItemChange(...)` call. The full suite passes.

## Findings

### N1 (non-blocking): the `profile.yaml` layer key is still `items:`

- Location:
  - `src/respec/profiles.py:52-53` (`LAYER_KEYS` and `BUILTIN_LAYER_KEYS`)
  - `:120` (the writer emits `items`)
  - `:391-401` (the reader and its errors)
  - the module docstring schema at `:16-25`. It also still says "only items
    and active allowed" and "Layers only decide which items are enabled".
- Failing scenario: a user hand-edits `profile.yaml` and puts
  `items: [a, a]` under a layer. respec reports
  `layers.<name>.items: 'a' is listed more than once`. If the user follows
  the "skill" wording and writes `skills: [a]` instead, `_unknown_keys`
  rejects it as an unknown key in that layer.
- Impact: the file users can see and edit uses a different word from the
  rest of the UI. But the error messages are accurate, because they quote
  the literal key that exists on disk. Criterion 2 makes persisted-key
  changes conditional ("only with backward-compatible reading"), not
  required. The README does not document the key. The spec says agents
  change profiles through the CLI rather than by hand-editing YAML. So this
  does not clearly contradict the decision. It is a residual inconsistency
  for the engineer to decide on.
- A compatible change, if the engineer wants one:
  - In `_parse_layer`, accept `skills:` as the canonical key and still read
    a legacy `items:`.
  - If a layer has both keys, report a schema error such as
    `layers.<name>: use skills (items is the old name), not both`.
  - Add `skills` to `LAYER_KEYS` and `BUILTIN_LAYER_KEYS`.
  - Have `Layer.to_dict` write `skills:`, so files migrate on their next
    CLI write.
  - Quote `skills` in the errors.
  - Update the module docstring schema.
  - Add tests that a legacy `items:` file still loads and gets rewritten as
    `skills:`, and that a file with both keys is rejected.

  Profiles installed by `profile install` from repositories that still use
  `items:` would keep working, through the same fallback read.

### N2 (non-blocking, cosmetic): stale internal docstrings

- Location:
  - `src/respec/items.py:214`, `:238`
  - `src/respec/layers.py:123`, `:197`, `:237`, `:258`
  - `src/respec/sources.py:369`, `:496`, `:512`, `:615`
  - `src/respec/profiles.py:164`
- Scenario and impact: developers read "item" here. None of these reach
  help or output, because they are not Typer command callbacks. This is in
  scope under criterion 4 only as a trivial change. There is no user
  impact.

### N3 (observation): the base red run stops at the guard

On the base code, `test_no_help_page_says_item` fails at the walk guard,
because `add-skill` does not exist there, before it scans any help output.
The second test independently proves that the help text changed, so the
evidence is enough. I am not asking for a change.

## Scope

The diff touches only the README, the source files and the tests listed in
the implementation run. No spec or ticket files were edited, and nothing was
added beyond the rename.
