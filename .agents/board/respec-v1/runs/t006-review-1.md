# Ticket 006 review 1 (fresh, independent)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t006`
- Diff: `a2f222e..2974fb0` (one commit; worktree clean at `2974fb0`)
- Inputs: ticket 006, spec (decisions 1, 8, 9, 12), ticket 004, implementation claims `t006-impl-1.md`. No AGENTS.md or CONTEXT.md in the worktree.

## Verdicts

| Axis              | Verdict |
| ----------------- | ------- |
| Spec compliance   | PASS    |
| Code quality      | PASS    |
| Tests and format  | PASS    |
| Blocking findings | 0       |

## Gates rerun

- `uv run pytest -q`: 73 passed
- `uv run black --check .`: 16 files would be left unchanged
- `npx prettier@3 --check README.md`: clean
- Manual runs of `.venv/bin/respec` with HOME, RESPEC_HOME and RESPEC_USER_HOME pointed at a scratch folder (scenarios below).

## Acceptance criteria

| Criterion                                                                   | Result | Evidence                                                                                                                         |
| --------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `add <path> [-p]` copies a folder with SKILL.md; default is the active one  | Met    | `items.add_local` and `items.resolve_profile_name`; tests `test_add_*`; manual run                                               |
| remove/enable/disable update profile.yaml; active profile refreshed at once | Met    | `items._refresh` reruns `switch.use`; tests check profile.yaml, links and `state.json` before and after                          |
| Disabled items keep files and metadata                                      | Met    | `set_enabled` uses `dataclasses.replace(entry, enabled=...)`, so `source` survives; test checks the folder and the source record |
| All commands support `--json`                                               | Met    | `ItemChange.to_dict`; `test_commands_support_json`                                                                               |

## Requested investigations

### (a) Full `use` rerun on refresh

Safe within the engine's existing contract. `state.json` is saved after every removal and every install. On a preflight refusal (`SwitchBlocked`), nothing on disk has changed and `items` undoes the profile.yaml change. For `add`, it also deletes the copied folder. Tests cover the undo for add, enable and remove. During the rerun, every link of the active profile disappears briefly. That matters only to a harness that scans the folder at that exact moment, which is already true of `respec use`.

Non-blocking finding A1: an item command can deactivate the whole profile because of a problem with a different item.

- Location: `src/respec/items.py` `_refresh`, which calls `switch.use` (`src/respec/switch.py` `use`, the install loop).
- Scenario, reproduced: active profile `w` has items `real-name`, `a` and `b`. Another tool replaces the recorded symlink `~/.claude/skills/a` with a real folder. `respec disable b` then exits 1 with "switch ... did not complete: File exists ... No profile is active".
- Result: `active_profile` is `null`, and `b: enabled: false` stays in profile.yaml (it is not rolled back). `real-name` is relinked. The foreign `a` folder is left alone and is not recorded. Nothing is deleted and `state.json` stays truthful.
- Impact: changing one item turns off the user's whole setup because another item has drifted. The behavior comes from engine 002/003 and follows the documented contract, but rerunning everything makes it easier to hit. Before ticket 004, consider a refresh that touches only the changed item, or let the 004 drift/adopt detection run before the refresh.

### (b) save_profile drops comments

This does not violate the spec. Decision 12 says agents change profiles through the CLI, not by editing YAML. Decision 1 makes the folder the source of truth but never promises to keep a hand-edited layout. The parser rejects unknown keys, so a rewrite can lose only comments, formatting and quoting, not data. Skill order is kept because `sort_keys=False` is used and dicts keep insertion order.

Non-blocking finding B1: the README does not say that the first add, remove, enable or disable rewrites `profile.yaml` and drops comments (`README.md`, usage section). A user who annotated the file loses the notes without warning. A one-line note in the README, or later in the `respec` skill (ticket for decision 12), would fix this.

### (c) One reusable core and a single writer

Met. `items.add_local(respec_home, profile, source, enabled=True)` has no CLI or Typer dependency and does not touch target folders. `profiles.save_profile` is the only code that writes `profile.yaml`, and it writes atomically (temp file plus `os.replace`). A grep finds no other `safe_dump` or `write_text` on profile files. `create_profile` now goes through it too.

Non-blocking finding C1: `add_local` names the item after the resolved source, which will give 004's adopt flow the wrong name.

- Location: `src/respec/items.py` `add_local`, where `source = Path(source).expanduser().resolve()` and `item = source.name`.
- Scenario, reproduced: `respec add <dir>/alias`, where `alias` is a symlink to `<dir>/real-name`, adds the item as `real-name`. For adopt, an unknown entry `~/.claude/skills/foo -> ~/code/foo-v2` would be added as `foo-v2`. The harness-visible name would change, and the original entry `foo` would not match the managed item.
- Impact: ticket 004 needs an optional `name` parameter, or naming by the unresolved basename, before it reuses this function. For 006 alone this is only a surprising name for a symlinked source.

### (d) `remove` never deletes outside respec's profile folder

Met. `remove` deletes only `profiles/<name>/skills/<item>`. `<item>` must be a key that is already in profile.yaml and passed `NAME_PATTERN`, so a path separator or a leading `.` is impossible. Removing target links goes through the engine's `_remove`, which unlinks symlinks and refuses copy-mode paths that resolve inside a profile folder.

Reproduced: I replaced `skills/ext` with a symlink to an outside folder and ran `respec remove ext`. The outside data was untouched, because `shutil.rmtree` refuses a symlink.

Non-blocking finding D1: that refusal is hidden. `rmtree(..., ignore_errors=True)` swallows the error, the command reports success, and the dangling symlink `skills/ext` stays in the profile folder. A later `respec add` of a folder named `ext` then fails with "already exists but is not listed". The impact is minor: there is no data loss, only a leftover and a misleading success message. Unlinking the symlink, or reporting it, would fix this.

### (e) Temp-home isolation

Met. Every test in `tests/test_items.py` runs through the `run` fixture under the autouse `isolated_homes` fixture (`tests/conftest.py`), and that fixture fails any path resolved under the real home. Fixtures read `isolated_homes` paths directly.

## Other notes (non-blocking)

- Untested path: an `enable` or `disable` that changes nothing returns early without writing. This is correct by inspection, but no test covers it.
- `remove`, after a non-blocked refresh failure, deletes the item folder while `state.json` may still record symlinks into it. Those dangling links are cleaned up by the next `use`, as the implementation claims say. Accepted.
- Scope: no remote-source or layer work slipped in. The `SwitchBlocked` subclass is a minimal, compatible change to the engine.
