# fix-7 implementation 1: consistency and cleanup

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-7`
- Branch: `codex/respec-v1-fix-7`, base `9c8f59f`
- Head: `04ee6d9`. Commits:
  - `8ae979e` Unify JSON keys; mark shipped and global skills; unblock repair
    (the behavior changes for criteria 1-5, plus the small cleanups they
    touched)
  - `04ee6d9` Consolidate copy, compare and naming helpers; drop dead code
    (refactor, criteria 6 and 7)
- AGENTS.md: none in the repository. I followed the global CLAUDE.md.
- Not pushed. No PR. Board records, ledger, spec.md and ticket files were not
  edited. No guard denials.
- Baseline before any change: 434 passed. Now: 455 passed.

## Changes

### Criterion 1: one JSON vocabulary

- `resolved`: the choices applied. `restore` now uses `resolved`, not
  `unknown`.
- `unresolved`: unknown entries still waiting for a decision, as Unknown
  dicts (`name`, `path`, `kind`, `targets`, `replaced`). It appears in `use`,
  `adopt` (was `unknown`), `restore`, `status` (top level, replacing
  `folders[].unknown`) and every change command (`add`, `remove`, `enable`,
  `disable`, `update`, the `layer` changes). A refused `use` or `restore` also
  lists the blocking entries there, including entries outside owned folders
  (first takeover).
- `warnings`: a typed list. `unknown-entry` warnings are gone (no alias),
  which leaves `layer-conflict` as the only type. The stderr warning lines for
  unknown entries stay.
- `error`: `adopt` and `restore` failures now carry every success key plus
  `error`. `restore(..., progress=RestoreResult)` fills in what it did before
  a failure, and `overwritten` collects through `done=`. `use` already did
  this.
- Null-only fields are left out: `installed[]` uses `Installed.to_dict()` (no
  `digest` on symlinks), and `restore` gives `backup` only when a run was
  named. The remaining meaningful nulls are documented.
- README "JSON" section rewritten. The shipped `respec` SKILL.md ground rules
  and `status` line are updated. `test_help` and `test_shipped_skill_docs`
  pass.
- Change commands still print errors on stderr only. This is now documented
  ("Other commands print their error on stderr only").

### Criterion 2: status marks shipped and global skills

- `status --json` `folders[].skills[]` gives `origin`: `profile`, `shipped`
  or `global`.
- Text `status` appends `shipped` or `global` after the mode.
- The TUI status panel reads the same `origin` field. The TUI's
  `_lasting_kinds` duplicate was replaced by `global_skills.lasting_or_shipped`.

### Criterion 3: Sync deadlock (t011-review-2 N1)

- Rule chosen: `layers.repair` first tries the normal full refresh. If that
  refresh is refused by `UnknownEntries`, and none of the entries in the way
  is named like the kept skill or a disabled skill, the repair goes ahead
  without the refresh (`_repair_links`). It saves `profile.yaml`, unlinks only
  the managed installs of the disabled skills, and links the kept skill
  through `switch.link_skills`. The entries stay for `respec adopt`.
- Otherwise the old refusal stands, and the profile and state are unchanged.
  So there is no partial apply on refusal.
- After the repair, adopt's existing up-front conflict check no longer
  applies, so the edited copy can be added. This works from the CLI and from
  Sync.
- I left the fix-5 "adopt refuses a conflicted profile up front" rule as it
  was. Three existing tests encode that decision.
- One existing test, `test_repair_refused_by_switch_preflight_leaves_profile_unchanged`,
  used an unrelated edited copy (`c`). That is the exact case criterion 3
  unblocks. I retargeted it to an edited copy of the skill being disabled
  (`a`), which is still refused, and its assertions are unchanged.
- README and SKILL.md document the rule.

### Criterion 4: Sync rows for global skills (N2)

- `LinkProblem` now records `origin`, `config` and `source_gone`.
- `NOT_LINKED` for a global skill reads "is a global skill listed in
  <config.yaml> but is not linked". When its folder is missing, it adds "its
  folder <global/skills/name> is missing; add it there, or take 'name' out of
  <config.yaml>".
- `NOT_ENABLED` for a link into the global folder reads "is linked but no
  longer listed as a global skill in <config.yaml>". For shipped skills it
  reads "respec no longer ships it".
- `folder_gone` (which drives the TUI "Disable" buttons) applies only to
  profile skills, as before.

### Criterion 5: reserved-name clash at first takeover

- `UnknownEntries` takes `clashes` (path to reason), filled in by
  `switch._clashes` through `global_skills.clash`. `items._refresh` passes it
  through.
- Example (real CLI smoke run, no active profile):
  `- …/.agents/skills/respec (folder): respec ships a skill named 'respec', so it can only be removed`.
  A global skill gives "'notes' is a global skill listed in <config.yaml>, so
  it can only be removed".
- `cli._prompt_choice` uses the same reason, also when no profile is active.
  It now takes `homes.respec_home` instead of calling `paths.respec_home()`
  (int-9c8f59f item 5).

### Criterion 6: dead code and duplicates (behavior-preserving)

- Removed `profiles.exclusivity_problems`, `sources.BASE_URL_ENV`, and the
  aliases `cli._source_label` and `cli._short`.
- New `respec/trees.py` holds `real`, `digest` (with an `ignore` parameter),
  `modes`, `same_content`, `same_entry` and `copy_entry`.
  - `switch._real` and `unknown.real/digest` are now `trees.real/digest`.
  - `adopt._copy_entry` and `restore._put_back` are thin wrappers over
    `trees.copy_entry`. Each keeps its own error text. `adopt`'s
    parent-mkdir-before-copy is kept.
  - `adopt._same_content` is now `trees.same_content`. `restore._same/_modes`
    are now `trees.same_entry` (digest plus modes, the stricter of the two,
    as before).
  - `global_skills._same_tree` (filecmp) is now
    `trees.same_content(..., ignore=())`. It is exact: hidden files count,
    and links are compared by target rather than followed. That is at least
    as strict as before.
- `restore._respec_link` uses `global_skills.source_roots(resolve=False)` and
  `source_roots()`, so written and resolved roots are checked as before.
- Reserved and lasting names now come from one place:
  - `global_skills.kinds/lasting/lasting_or_shipped/reserved/clash`;
  - `adopt._reserved` is removed;
  - `switch._check_global`, `relink_lasting` and `_kept` use the shared
    helpers;
  - the TUI `_lasting_kinds` is removed.
- `sync.check` reads `state.json` once and passes it to `_link_problems`.
- `layers.add_skill` uses `profiles.enabled_members`.
- Not done, on purpose: `messages.sourced_change` still builds its own
  `linked` lines. Switching to `link_lines` would also print `unlinked`,
  which would change behavior.

### Criterion 7 (optional)

- `items._load_with_item` is renamed to `_load_with_skill`. No `ItemChange`
  remained.

## Criterion -> test / evidence

| #   | Test(s)                                                                                                                                                                                                                                                                                                                                                                       | Red before fix                                                                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `tests/test_json_contract.py` (11 tests: use keys/unresolved/no digest/failure lists blocking entry; adopt success+failure same keys; adopt unresolved; restore resolved/failure keys+blocking/no null backup; status unresolved; change commands unresolved)                                                                                                                 | 7 of 11 failed (KeyError `unresolved`, key-set mismatches, `digest`/`backup` present); the other 4 failed after shape change                                                              |
| 2   | `test_global_skills.py::test_status_json_says_where_each_installed_skill_comes_from`, `::test_status_text_marks_shipped_and_global_skills`                                                                                                                                                                                                                                    | failed (`KeyError: 'origin'`; line lacked `shipped`)                                                                                                                                      |
| 3   | `test_layer_repair.py::test_repair_goes_ahead_while_an_unrelated_edited_copy_waits` (repair, then `adopt --add c`, then `use work`), `::test_repair_json_reports_what_it_unlinked_beside_the_waiting_entry`, `::test_repair_that_would_unlink_an_edited_copy_still_changes_nothing`; `test_tui_sync.py::test_sync_repairs_a_conflict_while_an_edited_copy_waits_then_adds_it` | first two failed with "cannot refresh profile 'work' … not managed by respec"; the Sync test failed the same way against the base `layers.py`; the third (safety) passed before and after |
| 4   | `test_tui_sync.py::test_link_row_of_a_global_skill_without_a_folder_points_to_config_yaml`, `::test_link_row_of_a_global_skill_dropped_from_config_yaml_says_so`                                                                                                                                                                                                              | failed ("is enabled in the active profile …")                                                                                                                                             |
| 5   | `test_global_skills.py::test_first_takeover_says_an_entry_clashes_with_a_shipped_skill`, `::test_first_takeover_says_an_entry_clashes_with_a_global_skill`                                                                                                                                                                                                                    | failed (message lacked the reason)                                                                                                                                                        |
| 6   | Full suite green before (434) and after the refactor commit (455). The refactor commit changes one test import only (`unknown.digest` to `trees.digest` in `test_sources.py`). `vulture --min-confidence 60` shows only Typer and Textual hooks                                                                                                                               | n/a                                                                                                                                                                                       |

Red output is saved in the scratchpad
(`/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/`):
`fix7-red-json.txt`, `fix7-red-2-4-5.txt` and `fix7-red-n1.txt`.

### Existing tests updated for the new JSON shape (renames, not weakened)

- `test_adopt.py`:
  - `folder_report` now derives a folder's entries from the top-level
    `unresolved`;
  - the `data["unknown"]` and `unknown-entry` assertions moved to
    `unresolved`;
  - one test was renamed to
    `test_switch_json_lists_unknown_entries_as_unresolved` (it checks the
    stderr hint instead of the removed warning `message`).
- `test_layer_repair.py::test_json_has_layer_conflict_warnings_beside_unresolved_entries`
  (renamed).
- Exact-shape tests in `test_use_status.py`, `test_items.py`, `test_tui.py`,
  `test_tui_sync.py` and `test_global_skills.py` now expect `origin` and
  `unresolved`.

## Verification (fresh, at 04ee6d9)

| Gate                                                                        | Result                            |
| --------------------------------------------------------------------------- | --------------------------------- |
| `UV_OFFLINE=1 uv sync --frozen`                                             | PASS (Audited 27 packages)        |
| `UV_OFFLINE=1 uv lock --check`                                              | PASS, rc 0 (Resolved 28 packages) |
| `uv run --frozen pytest -q -rs`                                             | PASS, 455 passed in 104.67s       |
| `uv run --frozen black --check .`                                           | PASS, 38 files unchanged          |
| `npx --no-install prettier --check README.md src/respec/shipped/*/SKILL.md` | PASS                              |
| `uvx --offline ruff check src tests --select F`                             | PASS                              |
| `git status --short`                                                        | clean                             |

## Data safety

- fix-5 "never delete the only copy" rollback (`_undo_adds`, `_put_back`
  verification, `_clean_leftovers`) is unchanged apart from calling
  `trees.same_content` and `trees.digest`. Its tests pass.
- fix-6 every-exit-path reporting: `use` is unchanged and now also lists
  blocking entries. `adopt` and `restore` failures report more than before
  (full keys, restore progress).
- `trees.copy_entry` keeps the cleanup of the duplicates: a partial folder is
  removed, and the source is never touched.

## Concerns

- Repair fallback: when the full refresh is refused, the repair changes only
  the links of the layer's skills. Other drift in the active profile is put
  right by the next `respec use` or Re-apply, once the waiting entries are
  resolved. An I/O failure part way through the fallback leaves the repaired
  `profile.yaml` and the links removed so far recorded, and says so. This
  matches how the switch engine reports its own partial failures.
- Pre-release breaking JSON change: `unknown-entry` warnings, adopt's and
  restore's `unknown`, and status's `folders[].unknown` are gone, with no
  aliases.
- `adopt`'s backup copy now turns a failure to create the backup's parent
  folder into the clean "could not back up" error instead of a raw `OSError`.
  This is only an error path.
