# t008 implementation run 1: Layers (built-in and custom)

- Status: DONE
- Branch: `codex/respec-v1-t008`, base `35cad16`, head `bc6a3f9`
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t008`

## Changes

- `src/respec/profiles.py`: `layers` added to `TOP_LEVEL_KEYS`; new `Layer`
  dataclass, `BUILTIN_LAYERS` (shipped descriptions), `builtin_layers()`,
  `Profile.layers` (always holds the built-ins), `Profile.layer_of()`,
  `exclusivity_problems()`, `with_enabled()` (applies the exclusive rule).
  Schema: built-in layers allow only `items`, `active`; custom layers require
  `exclusive` (bool) and `description` (str), optional `items`, `active`. An
  item may be in at most one layer and must be a profile skill; `output-style`
  rejects items; an active exclusive layer with more than one enabled item is
  a schema problem. Empty, active built-ins are not written to YAML, so
  existing `profile.yaml` output is unchanged.
- `src/respec/layers.py` (new): list/show/add/rm, add-item, remove-item, use,
  group enable/disable, on/off. Every mutation goes through
  `items.commit` -> `profiles.save_profile` plus the existing `_refresh`
  (re-runs `switch.use` for the active profile and undoes the profile change
  when its preflight refuses).
- `src/respec/items.py`: new `commit()` helper; `set_enabled` uses
  `profiles.with_enabled`, so plain `respec enable` respects exclusive layers;
  `remove` drops the item from its layer. `ItemChange` JSON is unchanged.
- `src/respec/cli.py`: `respec layer` sub-app (appended, plus one import).
- `README.md`: Layers section. `tests/test_layers.py`: 13 tests.

## Acceptance criteria -> evidence (tests/test_layers.py)

| Criterion                                                                                                          | Evidence                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Built-ins `design-principles`, `output-style`, exclusive, shipped descriptions; each can be turned off per profile | `test_new_profile_lists_builtin_layers_with_descriptions`, `test_builtin_layer_cannot_be_removed_but_can_be_turned_off`                                                                                                                                                            |
| Custom layers (name, exclusive, description); `layer add/rm/list/show`, `layer use`, add item                      | `test_custom_additive_layer_enables_and_disables_as_a_group`, `test_custom_exclusive_layer_show_and_rm`, `test_adding_enabled_item_to_exclusive_layer_keeps_current_choice`, `test_layer_commands_target_named_profile_without_touching_targets`, `test_schema_rejects_bad_layers` |
| Exclusive: at most one enabled, enabling another disables previous; additive group enable/disable                  | `test_layer_use_in_exclusive_layer_keeps_one_item_enabled_and_linked`, `test_plain_enable_of_exclusive_member_disables_the_previous_one`, `test_custom_additive_layer_enables_and_disables_as_a_group`                                                                             |
| Layers never change install locations; items outside layers additive; layers off -> exclusivity lapses             | `test_layers_never_change_install_locations`, `test_builtin_layer_cannot_be_removed_but_can_be_turned_off` (enable both members after `off`), item `c` stays enabled throughout                                                                                                    |
| `output-style` accepts no items, clear message                                                                     | `test_output_style_layer_accepts_no_items`, schema case in `test_schema_rejects_bad_layers`                                                                                                                                                                                        |
| State consistency on refusal                                                                                       | `test_switch_refused_when_preflight_blocks_leaves_profile_unchanged`, `test_removing_an_item_drops_it_from_its_layer`                                                                                                                                                              |

Tests assert `profile.yaml` and the active target links in a temp home, per
the testing seam. Red first: all 13 failed with exit code 2 (no `layer`
command). Mutation check: disabling the exclusive branch in `with_enabled`
fails 3 exclusivity tests.

## Verification

- `uv run pytest -q` -> `86 passed` (73 baseline + 13 new)
- `uv run black --check src tests` -> `18 files would be left unchanged.`
- `npx prettier@3 --check README.md` -> `All matched files use Prettier code style!`
- Smoke: `respec layer list -p w` lists both built-ins; `respec layer use
output-style x` exits 1 with `output styles are not supported yet; the
'output-style' layer accepts no items until they are`.

## Design choices for review (not specified by ticket)

- "Turn off" is per layer (`respec layer off <layer>`, YAML `active: false`);
  there is no single profile-wide "all layers off" switch. Key is `active`
  (not `off`, which YAML 1.1 parses as a boolean).
- `layer add-item` into an active exclusive layer that already has an enabled
  member disables the added item (keeps the current choice); `layer use`
  switches the choice.
- `layer enable` on an exclusive layer with more than one member is refused
  (use `layer use`). `layer on` is refused while two members are enabled.
- `layer rm` keeps items in the profile with their enabled flags; built-ins
  cannot be removed.
- A hand-edited profile violating exclusivity fails to load (strict schema,
  consistent with the existing unknown-key policy).
- Plain `respec enable` of a displaced item reports displaced links only in
  `unlinked`; `ItemChange` gained no field to keep the existing JSON contract.

## Concerns

- Rebase: `cli.py` changes are an import line plus an appended block;
  `profiles.py` touches `TOP_LEVEL_KEYS`, `Profile` and the end of
  `parse_profile`, which may conflict textually with 004/007 if they extend
  the same spots.
- No change to `--home` / `RESPEC_USER_HOME`.
