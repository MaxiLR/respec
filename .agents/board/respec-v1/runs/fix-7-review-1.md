# fix-7 review 1 (fresh, independent)

- Diff: `9c8f59f..04ee6d9` (8ae979e behavior, 04ee6d9 refactor), worktree
  `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-7`, clean tree.
- AGENTS.md / CONTEXT.md: none in the repository.
- Read-only review. Temp homes only, under the session scratchpad
  (`.../scratchpad/fix7rv/h.*`). No guard denials.

## Verdicts

- spec-compliance: FAIL (2 blocking, criteria 1 and 3)
- code-quality: PASS
- tests-rerun: PASS

## Gates rerun

| Gate                                                                        | Result                       |
| --------------------------------------------------------------------------- | ---------------------------- |
| `uv run --frozen pytest -q -rs`                                             | PASS, 455 passed in 105.5s   |
| `uv run --frozen black --check .`                                           | PASS, 38 files unchanged     |
| `npx --no-install prettier --check README.md src/respec/shipped/*/SKILL.md` | PASS                         |
| `uvx --offline ruff check src tests --select F`                             | PASS                         |
| Doc tests (`test_help`, `test_shipped_skill_docs`)                          | PASS (inside the full suite) |

## Blocking

### B1. `resolved[]` and other objects still carry null-only fields; README says they do not

- Where: `src/respec/adopt.py` `Resolution.to_dict` (lines 103-111). Also
  `LayerChange.to_dict` (`skill: null` on `layer add`) and `profile show --json`
  (`skills[].source: null`). README "JSON" section: "A field that does not
  apply is left out rather than given as `null` … Where `null` remains it
  means none: `active_profile`, `previous_profile`, `restored`, `same_as`."
- Scenario (real CLI, temp home): `respec adopt --add stray --json` gives
  `resolved[0].backup: null` and `replaced_copy: null`.
  `respec adopt --remove stray2 --json` and `respec restore --unknown remove
--json` give `resolved[0].profile: null` and `replaced_copy: null`.
  `respec layer add lay --exclusive -d L --json` gives `skill: null`.
- Impact: criterion 1 asks for "no null-only noise" and docs that match the
  real output. `resolved` is one of the five named vocabulary keys, and its
  entries carry the same kind of noise as the `backup: null` that was removed
  from `restore`. The README describes `resolved` entries as having "the
  `profile` … or the `backup`", so an agent reading the docs cannot expect
  both keys with `null`. Fix: leave out `profile`/`backup`/`replaced_copy`
  when unset (and `skill` on layer changes), or list them in the README's
  "null remains" sentence.

### B2. The deadlock remains when the edited copy belongs to a skill of the conflicted layer

- Where: `src/respec/layers.py` `repair`, fallback guard
  `entry.name == keep or entry.name in disabled` (lines ~347-349).
- Scenario (real CLI, `kb.sh`): active `work` with exclusive layer `lay`
  enabling `a` and `b`; `~/.claude/skills/b` replaced by an edited folder.
  - `respec adopt --add b`: refused by the up-front layer-conflict rule.
  - `respec layer repair lay --keep b`: refused ("cannot refresh profile
    'work' … b (an edited or replaced copy …)"), because `b` is the kept name.
  - `respec layer repair lay --keep a`: refused, because `b` would be
    disabled and its edited copy unlinked (this refusal is correct).
  - Only "remove" (backup) works. Keeping the edited `b` in the profile needs
    a hand edit, which is the N1 deadlock definition ("add and repair each
    refuse").
- Impact: criterion 3 is met for an edited copy of an unrelated skill (the
  original N1 scenario) but not for an edited copy of a layer member. The
  keep-name refusal is stricter than needed: keeping `b` changes nothing at
  `b`'s path. `switch.link_skills` already leaves an unmanaged destination
  alone and reports it in `blocked`, so the fallback could keep `b`, disable
  `a`, and leave `b`'s copy waiting for `respec adopt --add b`. If the
  engineer accepts "remove" as the way out for this case, record that
  decision and document it; otherwise relax the keep rule and add a test.

## (a) Refactor 04ee6d9: behavior preserved

I compared each consolidated helper with the original it replaces:

- `trees.real` and `trees.digest` are byte-for-byte `unknown.real` and
  `unknown.digest`. `ignore` defaults to `{.DS_Store}`. fix-1 digests are
  unchanged. `test_sources` compares the recorded digest with `trees.digest`.
- `trees.copy_entry` is the old `adopt._copy_entry` body. `restore._put_back`
  had the same body without `mkdir(parents)`. `_restore_folder` already
  creates the folder (restore.py:300), so nothing changes there. Both wrappers
  keep their own error text. `shutil.Error` becomes `OSError`, which both
  callers catch.
- `trees.same_content` is the old `adopt._same_content`. `trees.same_entry` is
  the old `restore._same` (digest plus modes, the stricter one).
- `global_skills._same_tree` (filecmp, which follows links) became
  `same_content(ignore=())`: exact names, bytes and link targets. That is at
  least as strict, so at worst the shipped skills are refreshed more often.
- `restore._respec_link` checks the same written and resolved roots through
  `source_roots(resolve=False)` and `source_roots()`.
- `adopt._reserved` became `global_skills.lasting_or_shipped`, with the same
  fallback to shipped names. In `switch._check_global`, `relink_lasting` and
  `_kept`, the shipped-first precedence and the raise-on-bad-config behavior
  are both unchanged.
- The fix-5 rollback (`_undo_adds`, `_put_back` verification) and fix-6
  `_clean_leftovers` changed only the helper names they call.

Real-CLI data-safety runs (temp homes, scripts in the scratchpad `fix7rv/`):

- **S1, read-only second target during `adopt --add`** (`ds.sh`): the profile
  has targets claude-code and agents, and `~/.agents/skills` is chmod 555.
  The command exits 1. The JSON has the full key set plus `error`, and
  `unresolved` lists `s`. The original `s` is byte- and mode-identical
  (including a 640 file in a subfolder). `profile.yaml` and `state.json` are
  byte-identical. Nothing is left in the profile.
- **S2, forced link failure after an overwriting add of an edited copy**
  (`ds2.sh`): exit 1 with the full JSON keys. The edited copy and the
  profile's previous copy are both byte-identical, and `profile.yaml` is
  unchanged.
- **S3, leftovers**: an only-copy `.o.respec-old` beside a live `o` is kept
  and reported. A redundant `.o.respec-new` is removed. A `.g.respec-old` with
  no live folder is restored to `g`.
- **S3b, a real hard kill** (`kill -9` during `adopt --add` of a 60 MB edited
  copy, `s3c.sh`): the live edited copy and the profile copy are both intact.
  The partial `.big.respec-new` makes the next add refuse ("may hold the only
  copy"). After it is moved away, the add succeeds and the profile copy equals
  the edited copy. The base `9c8f59f`, run from a `git archive` extract,
  refuses the same way, so this is not a regression (see N4).
- **S4, restore** (`s4.sh`): a pre-existing `~/.claude` with a 750 script, a
  700 folder, a 600 file, a relative symlink, a dangling symlink, a hidden
  folder and `.DS_Store` goes through `use`, `add` and `restore`. Every name,
  mode, size, link target and file hash is identical afterwards. No
  `~/.agents` folder is left behind.

## (b) Retargeted test

- `test_repair_refused_by_switch_preflight_leaves_profile_unchanged` used an
  edited copy of the unrelated skill `c`. That is the case criterion 3
  unblocks, so retargeting it is a legitimate behavior update. Its assertions
  (failure, `profile.yaml` unchanged) were kept, and it now uses an edited copy
  of the disabled skill `a`, which must still refuse.
- `test_repair_that_would_unlink_an_edited_copy_still_changes_nothing` adds
  byte-equality checks of `profile.yaml` and `state.json`.
- Gap: the keep-name refusal branch and the inactive-profile branch have no
  test. I verified the keep-name branch from the CLI: refused, with
  `profile.yaml` and `state.json` byte-identical (see B2 on whether it should
  refuse at all).

## (c) Repair fallback consistency

- Real CLI (`c3.sh`): the conflict is a+b, `c` is an edited copy, and `d` was
  disabled by hand while still linked. `layer repair lay --keep b --json`
  returns 0, `disabled [a]`, `unlinked [.../a]`, and `unresolved [c]`.
- The `state.json` diff before and after is exactly the removal of the `a`
  record. The edited `c` is untouched. `d` stays linked and recorded, which
  matches disk; that drift is left for the next `use`, as documented.
- Then `adopt --add c` succeeds, and `use work` succeeds and removes `d`.
- No partial apply on refusal: `_apply` raises before the save, and the
  fallback runs only when every entry in the way belongs to an unchanged
  skill.
- Minor: a `LinkFailed` raised by `link_skills` inside `_repair_links` comes
  after `profile.yaml` was saved. Its message does not say the repair was
  kept (only the unlink loop says that). See N5.

## (d) JSON contract (real CLI, every command, success and failure)

| Command                           | Success keys                                                                                                 | Failure                          |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------- |
| `use`                             | active_profile, backups, installed, linked, previous_profile, removed, resolved, unresolved, warnings        | same + error                     |
| `adopt`                           | linked, resolved, unresolved, warnings                                                                       | same + error                     |
| `restore`                         | left, overwritten, released, removed, resolved, restored, skipped, unresolved, warnings (+backup when named) | same + error (blocked, bad name) |
| `status`                          | active_profile, folders, targets, unresolved, warnings; `folders[].skills[].origin`                          | n/a                              |
| `add`/`remove`/`enable`/`disable` | action, active, enabled, linked, path, profile, skill, unlinked, unresolved, warnings                        | no stdout, stderr only           |
| `layer *`                         | action, active, disabled, layer, linked, profile, skill, unlinked, unresolved, warnings                      | no stdout, stderr only           |
| `update`                          | active, linked, profile, skills, unlinked, unresolved, warnings                                              | (not exercised)                  |

- There is no `digest: null` in `installed[]`. `restore` leaves out `backup`
  unless a backup run was named. The `unknown-entry` warning type is gone.
- `status` text marks `shipped`, and the `origin` field is present.
- The first takeover with a pre-existing `~/.claude/skills/respec` says
  "respec ships a skill named 'respec', so it can only be removed", in both the
  text and the JSON `error`.
- Null noise remains (B1).

## (e) Tests deleted or weakened

- I listed every removed line in `tests/`. Each one was renamed or moved to
  the new key (`unknown` → `unresolved`, `unknown-entry` warning →
  `unresolved` entry plus a stderr hint check). No test function was deleted,
  and no assertion was dropped without a replacement.
- One message assertion moved from JSON `warning.message` to `result.stderr`,
  because that field no longer exists.

## Non-blocking

- **N1**: change commands (`add`, `remove`, `enable`, `disable`, `layer *`,
  `profile new`) print nothing on stdout with `--json` when they fail. This is
  documented, but criterion 1 lists the change commands under the `error`
  vocabulary. An agent using `--json` gets no payload on failure. Consider
  `{..., "error"}` for them in a later ticket.
- **N2**: `switch.status` takes `origin` from the skill name
  (`lasting.get(item.name, "profile")`), while Sync uses the link target
  (`_origin_of_link`). A profile skill linked before the same name was added
  to `config.yaml` is shown as `global`. This is rare, because the next switch
  refuses that profile.
- **N3**: `src/respec/cli.py` `_update_line` and `_update_check` have two new
  f-string lines over 88 columns. Black leaves them, but they could be split
  into variables.
- **N4** (pre-existing on 9c8f59f): after a hard kill during an overwriting
  add, a partial `.<skill>.respec-new` blocks the next add of that skill until
  it is moved by hand. This is safe, but it is a manual step. A staged
  `.respec-new` can never be the only copy, because its source is the live
  entry.
- **N5**: `layers._repair_links` passes a `LinkFailed` from `link_skills` up
  without the "Profile keeps the repair" note.
- **N6**: no test covers the keep-name refusal or the fallback's
  `LinkFailed` path.
