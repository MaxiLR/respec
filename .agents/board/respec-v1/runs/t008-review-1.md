# t008 fresh review 1: Layers (built-in and custom)

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t008`
- Diff: `35cad160ce8cb6a87396383c0656cb3370ee8a4c..bc6a3f90ef506295d729c67fa1eab281c6b610d4`
  (one commit; 6 files, +1065/-13)
- Inputs: ticket 008, spec decision 10 (plus 12 and testing seams), implementer
  claims `runs/t008-impl-1.md`. No AGENTS.md or CONTEXT.md in the worktree.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- blocking findings: 0

## Gates rerun independently (worktree clean, head bc6a3f9)

| Gate                               | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv run pytest -q`                 | `86 passed in 1.78s`                         |
| `uv run black --check src tests`   | `18 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

Manual smoke in a scratch temp home (`HOME`, `RESPEC_HOME`, `RESPEC_USER_HOME`
all under the scratchpad), active profile on `claude-code` + `agents`:
`layer use design-principles a` -> `add-item design-principles b` (b unlinked
from both targets, a kept) -> `layer use design-principles b`. Result: only `b`
linked in `~/.claude/skills` and `~/.agents/skills`; `state.json` `installed`
lists exactly `b` for both targets; `profile.yaml` shows `a: enabled: false`,
`b: enabled: true`, `layers.design-principles.items: [a, b]`. `layer use
output-style a` exits 1 with `output styles are not supported yet; the
'output-style' layer accepts no items until they are`. Adding an item already in
another layer is refused with a clear message.

## Acceptance criteria

| Criterion                                                                                                                                                           | Verdict | Evidence                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Built-ins `design-principles`, `output-style`, exclusive, shipped descriptions (principles only, no component libraries/tokens); each can be turned off per profile | Met     | `profiles.BUILTIN_LAYERS`, `builtin_layers()`; `layer off/on` -> YAML `active: false`; tests `test_new_profile_lists_builtin_layers_with_descriptions`, `test_builtin_layer_cannot_be_removed_but_can_be_turned_off` |
| Custom layers (name, exclusive, description); `layer add/rm/list/show`, `layer use`, add item                                                                       | Met     | `layers.py` add/remove/list/show/use/add_item; `cli.py` `layer_app`; custom layers require `exclusive` + `description` in schema and CLI                                                                             |
| Exclusive: at most one enabled, enabling another disables previous; additive group enable/disable                                                                   | Met     | `profiles.with_enabled` used by both `layer use` and plain `respec enable` (`items.set_enabled`); `layer enable/disable`; load-time `exclusivity_problems`                                                           |
| Layers never change install locations; items outside layers additive; layers off -> exclusivity lapses                                                              | Met     | Layer code only edits `enabled` flags and membership, then reuses `items._refresh` -> `switch.use`; no target path logic touched; inactive layers skipped by `with_enabled`/`exclusivity_problems`                   |
| `output-style` accepts no items, clear message                                                                                                                      | Met     | `_check_accepts_items` (use, add-item) and schema rejection of `output-style.items`                                                                                                                                  |

## Requested checks

- **output-style accepts no items:** confirmed in CLI (use, add-item) and in
  schema (hand-edited items rejected). `layer enable/disable/on/off` on the empty
  layer are harmless no-ops.
- **Layers never change install locations:** confirmed. No change to
  `targets`/`switch`; links stay `<target>/<item>`; test
  `test_layers_never_change_install_locations` plus smoke.
- **Reuse of items/switch paths, state.json consistency:** every enabled-flag
  mutation goes through `items.commit` -> `save_profile` + `_refresh`
  (`switch.use` for the active profile, undo on `SwitchBlocked`). `layer add`
  and `layer rm` write YAML directly but change no enabled flags, so no refresh
  is needed. Smoke confirmed `state.json.installed` matches the links on disk.
  Refusal path covered by `test_switch_refused_when_preflight_blocks_leaves_profile_unchanged`.
- **Schema extension minimal:** one optional top-level key `layers`; custom layer
  keys `exclusive`, `description`, `items`, `active`; built-ins accept only
  `items`, `active`. Untouched built-ins are not serialized, so existing
  `profile.yaml` output is byte-identical (existing schema tests still pass).
  `active` rather than `off` avoids the YAML 1.1 boolean trap; reasonable.
- **Temp-home isolation:** `tests/conftest.py` `isolated_homes` is
  `autouse=True` and sets `HOME`, `RESPEC_HOME`, `RESPEC_USER_HOME` to
  `tmp_path`; `test_layers.py` uses it and asserts `profile.yaml` and target
  links per the testing seam.

## Open design choices

1. **Per-layer "off" (`active: false`), no profile-wide switch.** The ticket's
   "Each can be turned off per profile" and spec "Built-ins can be turned off per
   profile" are satisfied by per-layer off; the spec settles that each built-in
   is individually switchable. "With layers off, a profile is a flat additive
   list" / "exclusivity lapses" is also satisfied: turning every layer off yields
   a flat additive profile. The spec neither requires nor forbids a single
   profile-wide "all layers off" toggle, so that convenience is genuinely open
   for the engineer, not a defect. Allowing custom layers to be turned off too is
   an extension consistent with the spec.
2. **`add-item` into an exclusive layer disables the new item, keeps the current
   choice.** Not settled. The spec user story says "choosing one item turns the
   others off"; adding to a group is not obviously "choosing", and `layer use`
   is the choose verb. The behaviour preserves the invariant either way.
   Genuinely open (alternatives: refuse, or make the added item the choice).
3. **Hand-edited profile.yaml breaking exclusivity fails to load.** Consistent
   with the spec (decision 12: agents mutate through the CLI, not by hand-editing
   YAML; seam: "exclusive layer enforces a single enabled item") and with the
   existing strict unknown-key policy. Side effect: the broken profile cannot be
   repaired through `respec layer off`/`disable`, only by editing YAML again
   (the error names the layer and items). Strictness is spec-consistent; whether
   to add a repair path or lenient load is an open engineer preference, low
   stakes.

## Non-blocking findings

1. `src/respec/layers.py` `add()` / `profiles._parse_layer`: an empty
   description is accepted (`respec layer add x --additive -d ""` succeeded in
   smoke). Spec decision 10 says the description explains what belongs there.
   Impact: low; a layer can exist with no guidance for agents. Optional: reject
   blank descriptions.
2. `src/respec/cli.py` `layer_add`: omitting the flag gives Typer's
   `Missing option '--exclusive'.`, which does not mention `--additive`.
   Impact: minor UX; the user may not realise additive is the alternative.
3. Tests assert `profile.yaml` and links but never `state.json`; consistency
   relies on reuse of the existing `_refresh`/`switch.use` path (verified by
   smoke above). Impact: low; a future regression in state recording on layer
   commands would not be caught by `test_layers.py` (existing switch tests do
   cover `state.json`).
4. Plain `respec enable b` that displaces `a` in an exclusive layer reports `a`'s
   links only under `unlinked`, with no explicit "disabled a" message (by design,
   to keep `ItemChange` JSON stable). Impact: minor discoverability.

## Scope

Within ticket scope. No changes to targets, switching engine, TUI, or
`--home`. README section is accurate. No security-relevant changes (no new path
construction from layer names; layer names validated with `NAME_PATTERN`).
