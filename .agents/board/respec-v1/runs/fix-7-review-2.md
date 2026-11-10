# fix-7 review 2 (fresh, independent)

- Diff: `9c8f59f..b28c295` (8ae979e behavior, 04ee6d9 refactor, b28c295
  round-1 fixes). Focus: b28c295 and regressions.
- Worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-7`, clean tree,
  HEAD `b28c295`. AGENTS.md / CONTEXT.md: none in the repository.
- Read-only. Temp homes only, under the session scratchpad
  (`.../scratchpad/r2/`). No guard denials.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking: 0

## Gates rerun

| Gate                                                                        | Result                     |
| --------------------------------------------------------------------------- | -------------------------- |
| `uv run --frozen pytest -q -rs`                                             | PASS, 462 passed in 105.2s |
| `uv run --frozen black --check .`                                           | PASS, 38 files unchanged   |
| `npx --no-install prettier --check README.md src/respec/shipped/*/SKILL.md` | PASS                       |
| `uvx --offline ruff check src tests --select F`                             | PASS                       |
| `git status --short`                                                        | clean                      |

## (a) B1: null-only JSON fields (resolved)

Real CLI sweep (`scratchpad/r2/scripts/sweep.py`, in-process `CliRunner`,
temp homes, local `file://` git upstream). It ran 47 invocations with `--json`:
profile new/list/show, status (3 states), use (fail, unknown refusal,
`--unknown add`, switch), add (local, git, failing git), enable/disable/remove,
every layer command including repair, `update --check`/`update` (before and
after an upstream commit), adopt (list, add, remove, failing add), `restore
--list`, restore (refused by an unknown entry, and `--unknown remove`).

- Undocumented nulls in output: none. Success and failure key sets match the
  README vocabulary; `use`, `adopt` and `restore` failures carry the full key
  set plus `error`. Change commands still print nothing on stdout on failure,
  as documented (review-1 N1, deferred).
- To answer whether the filter can drop something meaningful, I wrapped
  `cli._without_nulls` and logged every field it removed from the raw payload.
  The full list: `resolved[].backup`, `resolved[].profile`,
  `resolved[].replaced_copy`, layer-change `skill`, `profile show`
  `skills[].source`, `remove` `enabled`, restore `backup`, `update --check`
  `skills[].error`. Each is a "does not apply" field and matches the README
  sentence (README.md:229-239) and SKILL.md:22-24.
- Documented nullable values survive: `active_profile`/`previous_profile`
  (`null` before any profile), `same_as: null` in status, and `restored` values
  (exempted by parent key).
- Falsy non-null values are safe: the filter tests `is not None`, so `false`,
  `0`, `""` and `[]` are kept (seen in output: `active: false`, `linked: []`,
  `unlinked: []`, `leftovers: []`).
- Other nullable model fields I checked by reading: `Owned.backup` never
  reaches `backups` (`switch.new_backups` filters falsy, switch.py:549-553);
  `UpdateRow.latest/update_available/modified` are null only on an error row,
  where `error` carries the meaning; `Spec.path` is not printed. No list in any
  output contained a `null` element, so the list branch drops nothing today.

## (b) B2: edited copy that is a member of the conflicted layer (resolved)

Scenario (`scratchpad/r2/b2.sh`, real CLI): active `work`, exclusive layer
`lay` = {a, b}, both enabled by hand; `~/.claude/skills/b` replaced by an
edited folder (`SKILL.md` plus an extra file). Also repeated with two targets
(claude-code + agents, `b2m.sh`).

- `adopt --add b` is refused up front by the layer-conflict rule (unchanged,
  as intended).
- `layer repair lay --keep b`: rc 0. `disabled [a]`, `unlinked` = a's links,
  `linked []`, `unresolved [b]`. profile.yaml diff: only `a.enabled` true to
  false. state.json diff: exactly the removal of a's records. The edited copy is
  byte-identical. With two targets, agents' `b` link stays.
- `layer repair lay --keep a`: rc 0. `disabled [b]`, `unlinked []` with one
  target, and with two targets `unlinked` holds only agents' `b` link (still
  respec's). The claude-code `b` record stays in state.json while its path holds
  the edited copy. That matches disk as before the repair and is reported
  under `unresolved`. The edited copy is untouched.
- Then, in both cases: `use work` refuses only on the edited `b`;
  `adopt --add b` puts the edit into the profile (prior profile copy backed up
  as `replaced_copy`), links it when b is enabled or leaves it unlinked when b
  is disabled; `use work` then succeeds and state matches disk.
- No partial apply: `switch.use` checks layer conflicts, missing folders and
  `config.yaml` before unknown entries (switch.py:596-606), so the fallback in
  `layers.repair` only runs when unknown entries are the sole refusal. The
  fallback saves profile.yaml first. A link failure after that says "Profile
  … keeps the repair" (covered by
  `test_repair_link_failure_says_the_repair_was_kept`).

## (c) Retargeted refusal tests (legitimate)

- `test_repair_refused_by_switch_preflight_leaves_profile_unchanged` now uses a
  missing folder of enabled skill `c` (`SwitchBlocked`).
  `test_repair_refused_for_another_reason_beside_an_edited_copy_changes_nothing`
  uses an invalid `config.yaml` while an edited copy is present. It asserts
  that profile.yaml and state.json are byte-identical and the copy is intact.
  Both refusals are still real refusals of repair. The old unknown-entry
  refusal is exactly what criterion 3 / B2 removes, so retargeting is a
  correct update, not a weakening.
- The general refusal guarantee for unknown entries is still covered for the
  other change commands: `test_layers.py::test_switch_refused_when_preflight_blocks_leaves_profile_unchanged`
  (layer enable), `test_items.py:136-150` (add rolls back),
  `test_adopt.py:508-525` (disable with a replaced link says "left unchanged").

## (d) Data-safety rerun (no regression)

- Forced link failure during an overwriting `adopt --add` of an edited copy
  (`scratchpad/r2/scripts/ds2-s2.sh`, second target chmod 555): exit 1, JSON
  keys `error, linked, resolved, unresolved, warnings`. The edited copy and the
  profile's previous copy are byte-, mode- and mtime-identical. profile.yaml
  is byte-identical. No staging leftovers in the profile's skills folder.

## Non-blocking

- **N1** `src/respec/cli.py:117-132` `_without_nulls`: the exemptions match
  key names anywhere in the tree (`NULLABLE`, and any child of a key named
  `restored`), and `null` list elements are dropped silently. This is correct
  for today's payloads. A future payload that uses a nullable key name with
  another meaning, or a list that holds `null` on purpose, would be filtered
  without warning. The library `to_dict` values still hold `None` (the
  implementer disclosed this).
- **N2** `src/respec/layers.py:348` `if not change.active: raise` cannot be
  reached: `items._refresh` returns before switching when the profile is not
  active, so `UnknownEntries` never comes back for an inactive profile. This
  is a harmless defensive branch.
- **N3** `src/respec/global_skills.py:176` `origin`: Sync used to report a
  recorded non-link (copy) as `profile`. It now uses the name for copies, the
  same as `status`. This is intended consistency (review-1 N2). It only
  changes the label for a copy named like a shipped or global skill.
- **N4** (pre-existing, not from this diff) Saving profile.yaml after a repair
  moves the layer's `description` key after `skills`. This is cosmetic
  serializer churn.
- Review-1 N1 (change commands print no JSON on failure) and N4 (partial
  `.respec-new` after a hard kill blocks the next add) are still deferred, as
  the implementer recorded.
