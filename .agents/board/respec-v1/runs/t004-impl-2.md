# t004 implementation run 2: rebase onto 5136097 (ticket 008 layers)

- Branch: `codex/respec-v1-t004` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t004`)
- Base: `51360971f75febdccd61baab22dd4b977eee298e` (feature tip with ticket 008 layers; run 1 was on `35cad16`)
- Head: `64e9ba5` "Detect unknown entries in owned folders and add respec adopt" (rebased from `dbc1e14`)
- Status: DONE (not pushed, no PR)

## Rebase onto 5136097: conflicts and resolutions

- `README.md`: conflict. 008 added a `### Layers` section where t004 added the
  unknown-entries paragraph. Both are kept. The unknown-entries paragraph now sits
  before `### Layers`, so it is not filed under the layers heading. Prettier is
  clean.
- `src/respec/cli.py` import line: conflict. The two import lines are merged into
  `from respec import adopt as adopt_entries` plus
  `from respec import items, layers, paths, profiles, switch, targets, unknown`.
- `src/respec/cli.py` commands: conflict. 008's `layer_app` and its commands are
  kept unchanged, and t004's `adopt` command follows them. Both sides only
  appended code.
- `src/respec/items.py`: merged automatically. 008's `commit()` / `_refresh()`
  path is kept unchanged. The merged `add_local` docstring was rewrapped to fit
  88 columns. The `name` parameter is intact.
- No other conflicts. `switch.py`, `state.py`, `profiles.py` and `layers.py` need
  no t004 changes beyond those already in run 1. profile.yaml is still written
  only by `profiles.save_profile`. Adopt `add` writes through `items.add_local`,
  which calls `save_profile`.

How it interacts with layers: `layers._apply` calls `items.commit` for every
layer command (`use`, `enable`, `disable`, `on`, `off`, `add-item`, and others).
`items.commit` calls `_refresh`, which calls `switch.use` without an unknown
handler. When an unknown entry waits, `switch.use` raises `UnknownEntries` (a
`SwitchBlocked` subclass), so `_refresh` restores the earlier profile.yaml and
the layer change is rolled back. The new parametrized test
`test_layer_change_is_rolled_back_while_an_unknown_entry_waits` covers `layer use`
and `layer disable`. Each case fails, and profile.yaml and the target folder are
unchanged. After `adopt --keep`, the same command succeeds. The test failed for
both cases when the `UnknownEntries` raise was disabled, then passed with it
restored. 008's existing
`test_switch_refused_when_preflight_blocks_leaves_profile_unchanged` still
passes; its foreign folder now meets the unknown-entry block first, and the
message still says "not managed by respec".

## Changes

- `src/respec/unknown.py` (new): detection only. An entry in an owned folder is
  managed when `state.json` records it and it is still what respec created. A
  symlink must still point into the profiles folder, and a copy must still exist.
  Any other entry is `Unknown(name, path, kind, targets, replaced)`. Kept entries
  (`state.unmanaged`) and hidden dot-entries are skipped. Owned folders that
  resolve to one real directory are scanned once, under the first target in
  registry order. `folder_report` feeds `status`.
- `src/respec/adopt.py` (new): `resolve()` applies `add` / `backup` / `keep` per
  entry. `add` goes through `items.add_local(..., name=entry.name)`, then removes
  the original. `backup` copies the entry to
  `backups/<run>/<target>/<name>` (a symlink is backed up as a link) and only then
  removes the original. `keep` records the entry in `state.unmanaged`. Every choice
  drops any stale `installed` record for that path. `adopt()` resolves entries
  outside a switch and re-applies the active profile when something was added to
  it. Backup run folders use the existing `switch._new_backup_run`, which takes an
  injectable clock and adds a `-N` suffix, so names cannot collide within one
  second.
- `src/respec/switch.py`: `use(..., on_unknown=None)`. Unknown entries raise
  `UnknownEntries` (a `SwitchBlocked` subclass) before anything changes, unless a
  handler is given. After the handler runs, records of entries that are still
  "replaced" are dropped (`_forget_replaced`), so a foreign entry is never
  unlinked or overwritten, and preflight then blocks cleanly if it collides with
  an install. `status` adds `same_as`, `unknown` and `unmanaged` per folder. Shared
  items are listed under the first target of an aliased group, whatever the
  profile's target order, and only items still managed are listed.
- `src/respec/state.py`: optional `unmanaged: [paths]`. Older files without it
  still load.
- `src/respec/items.py`: `add_local(..., name=None)` keeps the entry's own name
  for symlinked entries.
- `src/respec/cli.py`: `respec use --unknown add|backup|keep`. Without the option,
  a TTY prompts once per entry; non-TTY and `--json` runs stop with the entry list
  and a hint. New `respec adopt` takes `--add/--backup/--keep <name|path>`
  (repeatable), `--all <choice>`, `-p`, and `--json`. Without choices it prompts on
  a TTY and otherwise only lists entries. Unmatched or conflicting selectors fail
  before anything changes. Human `status` shows unknown and kept entries plus
  "(same folder as X)".
- `README.md`: documents adopt and unknown entries (Prettier clean).
- `tests/conftest.py`: the `run` fixture accepts `input=` for prompt tests.
- `tests/test_use_status.py`: three tests now resolve an entry that stays in an
  owned folder after takeover or after it was dropped in. Two use
  `--unknown keep`, and one uses `on_unknown=lambda e: None`. The exact status
  JSON expectation gains the three new keys.

## Acceptance criteria -> evidence (tests/test_adopt.py)

| Criterion                                                                       | Tests                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unknown entries reported by `status` and `--json`                               | `test_status_json_reports_foreign_entry_dropped_after_activation`, `test_status_human_lists_unknown_entries_with_a_hint`, `test_replaced_link_is_reported_as_unknown`, `test_status_shows_alias_for_targets_sharing_one_real_folder`, `test_hidden_files_are_not_reported`                                                                                                                                    |
| Prompt per entry before a switch, three choices, non-interactive needs a policy | `test_interactive_switch_prompts_once_per_entry`, `test_switch_policy_add_copies_entry_into_new_profile_and_links_it`, `test_switch_policy_backup_moves_entry_to_backups_then_switches`, `test_switch_policy_keep_leaves_entry_and_stops_asking`, `test_non_interactive_switch_with_unknown_entry_fails_and_changes_nothing`                                                                                  |
| `respec adopt` with `--json` and per-entry flags                                | `test_adopt_json_without_choices_lists_entries_and_changes_nothing`, `test_adopt_backup_flag_backs_up_and_removes_only_that_entry`, `test_adopt_add_into_active_profile_links_it_at_once`, `test_adopt_add_of_a_symlinked_entry_keeps_the_entry_name`, `test_adopt_keep_flag_records_entry_as_unmanaged`, `test_adopt_all_applies_one_choice_to_every_entry`, `test_adopt_interactive_prompts_for_each_entry` |
| Nothing removed without adoption or backup                                      | Backup tests assert the backup contents; `test_add_choice_on_a_file_fails_and_keeps_the_file`, `test_adopt_unknown_selector_fails_before_changing_anything`, `test_non_interactive_switch_with_unknown_entry_fails_and_changes_nothing`                                                                                                                                                                       |

Orchestrator findings handled:

- Replaced recorded link: covered by
  `test_replaced_link_blocks_switch_cleanly_then_backup_resolves_it` and
  `test_item_change_is_rolled_back_when_replaced_link_blocks_refresh`. Before the
  fix, the first test's switch succeeded with the foreign entry left recorded, and
  the second test's `disable` was not rolled back. Both were confirmed red.
- Alias: covered by `test_status_shows_alias_for_targets_sharing_one_real_folder`
  and `test_status_lists_shared_items_once_whatever_the_profile_target_order`.
- add_local name: covered by `test_adopt_add_of_a_symlinked_entry_keeps_the_entry_name`.

TDD: the new test file was written first. All 21 initial tests failed for the
missing behavior. The alias-order test was added later and confirmed red without
the `switch.py` change.

## Verification

- `uv run pytest -q`: `110 passed` (after rebase, includes 008 tests and the 2 new layer cases)
- `uv run black --check .`: `21 files would be left unchanged.`
- `npx prettier@3 --check README.md`: `All matched files use Prettier code style!`
- CLI smoke test in a scratch home: `status` lists `foo  unknown folder`. A
  non-TTY `use a` exits 1 and lists the entry. `adopt --add foo` adds and links
  it, and `status` then shows `foo  symlink`.

## Concerns / decisions to confirm

- Entries that existed before first takeover stay in the folder and become
  unknown after it. The next switch asks about them; this matches decision 5 and
  is why three existing tests needed a choice.
- During `use`, `add` copies into the profile being activated, not the
  previously active one. `respec adopt --add` uses `-p` or the active profile.
- Hidden dot-entries (for example `.DS_Store`) are never reported.
- Any unknown entry also blocks the profile refresh inside `add`, `enable`,
  `disable` and `remove`, and those changes are rolled back. The user resolves
  the entry with `respec adopt` first.
- Edge case: `adopt --add` into the active profile removes the original before
  relinking. If an unresolved replaced entry then blocks the relink, the item
  stays in the profile but is not linked until the next switch.
- Typer bundles its own click, so `click.Choice` and `click_type` do not work.
  The CLI uses an `Enum` and a manual prompt loop.
- The `--home` / `RESPEC_USER_HOME` semantics are unchanged.
