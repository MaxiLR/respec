# t009 implementation 2 (fix round 1)

Fix round 1 for t009: the review-1 finding F1 and the restore parent-folder cleanup.

- Branch: `codex/respec-v1-t009`
- Base: `b8d1aee`; previous head: `5dc0cd1`; new head: `7ee413f`. No rebase.
- Status: DONE

## Changes

### F1: one shared check that no path that adds a skill can bypass

- **Core check.** `global_skills.reserved(respec_home)` maps each reserved name (shipped skills and the skills listed in `config.yaml`) to a reason. `global_skills.refuse_reserved(respec_home, names, profile, hint)` raises before anything changes. It is called from:
  - `items.add_local`. Every local add, adopt's add of a new skill and each skill of a git add pass through it, as would any TUI add (ticket 011) built on `items`/`sources`.
  - `sources.add`, for all found skills up front, before anything is fetched into the profile.
  - `sources.install_profile`, for every skill listed in the fetched `profile.yaml`, before the profile folder is created.
  - `adopt._add`, which also covers the edited-copy overwrite branch.
- **Adopt: refusal before any change.**
  - `adopt.resolve` first asks about entries with reserved names, before applying any choice.
  - An `add` of one of them raises with the hint "Choose remove instead ('respec adopt --remove <name>')...", before any entry changes.
  - This covers `adopt --add`, `adopt --all add`, the adopt prompt, `use --unknown add`, takeover prompts and the TUI dialog, which all go through `resolve`/`adopt`.
- **Choices offered.**
  - `adopt.choices(profile, entry=None, respec_home=None)` returns only `remove` for a reserved entry.
  - The CLI prompt passes the entry and explains why add is not offered.
  - `tui.py` is unchanged: its dialog still lists add. Choosing it gets the core refusal and nothing changes. Ticket 011 can pass the entry to `choices`.
- **Remove puts the shipped skill back.**
  - `switch.relink_lasting(respec_home, user_home)` links missing shipped and global skills of the active profile's switch into owned folders where nothing is in the way. It records each link in `state.json` and saves after every install.
  - `adopt.link_added` calls it after any resolution. That covers `adopt`, the switch and takeover flows, and the TUI.

### Restore removes the empty folders respec created

- **Recording.** `Owned.created` (in `state.json`, left out when empty) lists the folders that were missing at takeover: the skills folder and each missing parent up to the user home, deepest first. It is recorded by `switch._take_over` and loads as empty from older state files.
- **Cleanup.**
  - After a successful restore, `restore._remove_created` runs `rmdir` on those folders, deepest first. A folder that is not empty, or is a symlink, stays.
  - It only applies to targets that no backup restores: the folder did not exist at takeover, or the named run does not hold it.
  - Folders that existed before takeover are never in `created`.

### Docs

- The `respec` skill and the README now say:
  - every path that adds a skill refuses reserved names;
  - an entry with a reserved name can only be removed, after which respec links its own skill there again;
  - restore removes the folders respec created once they are empty.

## Findings -> tests

All tests below are new and were red before the fix. Red output from the first run is in brackets. Unless noted, they are in `tests/test_global_skills.py`, marked `shipped`.

| Finding / path                                                                 | Test                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1 reproduction (p2 on oh-my-pi, replaced `profile-maker` link, `adopt --add`) | `test_adopt_add_of_a_replaced_shipped_skill_is_refused_and_remove_relinks_it` [exit 0 instead of 1]. Afterwards: the entry is unchanged and absent from the profile; `--remove` backs up the edited copy and relinks the shipped link (reported in `linked`); `disable` and `use` work. |
| F1 second variant (`pi`, `~/.agents/skills/respec`)                            | `test_adopt_add_of_a_shipped_skill_outside_the_profile_targets_is_refused` [exit 0]. Then remove relinks it and `use pi` works.                                                                                                                                                         |
| `adopt --all add` refused before any entry changes                             | `test_adopt_all_add_is_refused_before_any_entry_changes` [exit 0]. An unrelated `aaa` stays.                                                                                                                                                                                            |
| `use --unknown add`                                                            | `test_use_unknown_add_of_a_reserved_entry_is_refused` [exit 0]. The active profile stays `a`, then `--unknown remove` switches and relinks.                                                                                                                                             |
| Adopt prompt                                                                   | `test_adopt_prompt_offers_only_remove_for_a_reserved_entry` [the prompt accepted add]                                                                                                                                                                                                   |
| `resolve` API (the TUI and takeover path)                                      | `test_resolve_api_refuses_add_of_a_reserved_entry_before_changes` [no refusal]. An earlier valid entry is untouched.                                                                                                                                                                    |
| CLI local add to an inactive profile (shipped and global names)                | `test_local_add_of_a_reserved_name_to_an_inactive_profile_is_refused[respec, notes]` [exit 0]                                                                                                                                                                                           |
| Git add                                                                        | `tests/test_sources.py::test_git_add_of_a_skill_named_like_a_shipped_skill_is_refused` [both skills added]                                                                                                                                                                              |
| Profile install                                                                | `tests/test_sources.py::test_profile_install_with_a_skill_named_like_a_shipped_skill_is_refused` [installed]                                                                                                                                                                            |
| Restore removes created parents                                                | `test_restore_removes_parent_folders_respec_created` [`~/.agents` remained]. A pre-existing `~/.omp` stays.                                                                                                                                                                             |
| Restore keeps a created parent that gained content                             | `test_restore_keeps_created_parents_that_gained_other_content` [red]                                                                                                                                                                                                                    |
| Restore never removes folders that existed before takeover                     | `test_restore_never_removes_folders_that_existed_before_takeover` (guard; passes before and after)                                                                                                                                                                                      |

One existing test changed: `tests/test_restore.py::test_restore_named_backup_restores_the_folders_it_holds`.

- It used to expect that the folder respec created for oh-my-pi survives a named restore. It now expects that folder, and its created parent, to be gone.
- This follows directly from the new cleanup requirement. The folder did not exist before respec and held only respec's skills.

Real CLI reproduction (scratch homes):

- `adopt --add profile-maker` exited 1 with "cannot add 'profile-maker' to profile 'p2' ('profile-maker': respec ships a skill of that name and installs it into every target). Nothing was changed. Choose remove instead ...".
- `adopt --remove profile-maker` backed it up and printed `linked .../.omp/agent/skills/profile-maker`. The link points at `rh/shipped/profile-maker`.
- `restore` left the scratch home empty: no `.omp` or `.agents`.

## Verification (fresh, at 7ee413f)

- `uv sync --frozen`: `Audited 27 packages`
- `uv lock --check`: `Resolved 28 packages`
- `uv run pytest -q`: `386 passed` (373 before this round)
- `uv run black --check .`: `32 files would be left unchanged.`
- `npx prettier@3 --check README.md src/respec/shipped/respec/SKILL.md src/respec/shipped/profile-maker/SKILL.md`: `All matched files use Prettier code style!`

## Concerns

- `tui.py` still offers add for a reserved entry; the core check refuses it and nothing changes. Ticket 011 can pass `entry`/`respec_home` to `adopt.choices`. `cli.py` changed only in `_prompt_choice`.
- `state.json` has a new optional key, `owned.<target>.created`. Older files load without it, so folders taken over before this change are never cleaned. That is safe; worth knowing for fix-7's JSON pass.
- An invalid `config.yaml` now also refuses every add, with the config error.
