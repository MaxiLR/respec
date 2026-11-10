# Integration check: b8d1aee (after fix-6 merge)

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- Head: `b8d1aee671ac7efa848c1f2992f610117fdd824f` (matches expected)
- Change range: `493d8e8..b8d1aee` (18 files, +2222/-605; commits 43d49d2,
  777ca83, 4b79c93 and merge b8d1aee)
- AGENTS.md: none in the repository. Followed global CLAUDE.md and
  verify-before-handoff.
- Worktree state: only the expected orchestrator files under
  `.agents/board/respec-v1/` are dirty, plus this report. One API probe created
  a temp dir `api.jyvutsyu/` in the repo root by mistake (cwd); I removed it at
  once and `git status` was clean again.
- Scratch:
  `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/intb8d/`
  (`smoke.sh`, `smoke2.sh`, `smoke3.sh`, `api.py`, the `.log` files, and
  `smoke.compact.log` with the paths shortened).

## Gates

| Gate                                                           | Result                                |
| -------------------------------------------------------------- | ------------------------------------- |
| `UV_OFFLINE=1 uv sync --frozen`                                | PASS                                  |
| `UV_OFFLINE=1 uv lock --check`                                 | PASS (Resolved 28 packages)           |
| `uv run --frozen pytest -q`                                    | PASS, 344 passed in 57.30s, 0 skipped |
| `uv run --frozen black --check .`                              | PASS, 29 files unchanged              |
| `npx --no-install prettier --check README.md spec.md` (3.9.10) | PASS                                  |
| Prettier on committed `tickets/*.md` (HEAD blobs via stdin)    | PASS, no diffs                        |
| `uv run --frozen pytest -q tests/test_tui.py` (Pilot)          | PASS, 26 passed                       |
| `uvx --offline ruff check src tests --select F`                | PASS                                  |

## End-to-end smoke (temp `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`; stdin `/dev/null`; no network)

### smoke.sh: non-clashing pre-existing entries

`~/.claude/skills` started with `pre1/` (a 755 file inside), `pre2/`,
`notes.md` and the symlink `extlink -> $T/ext`. `~/.claude/settings.json` was
outside the skills folder. A snapshot recorded type, mode, link target and
sha256 for every path.

- `profile new work|other --target claude-code` and `add d1 d2 rev -p work`:
  rc 0.
- First takeover, non-TTY `use work`: rc 0. It printed
  `Backed up claude-code folder to …/backups/<run>/claude-code` and
  `Switched to profile 'work': installed 3 skills`, then 4 warnings of the form
  `warning: …/pre1 is a folder respec did not place; run 'respec adopt' to add it to the active profile or remove it`.
  `use work --json` has `resolved: []`, `linked: []` and typed
  `unknown-entry` warnings (name, path, kind, targets, replaced, message).
  `status` lists the entries as `unknown folder|file|symlink`.
- Unrelated unknown entry (`stray/` added after takeover): `disable d2`,
  `enable d2 --json`, `layer use design-principles d1 [--json]`,
  `layer add-skill`, `layer add review --additive -d …` and `layer add-skill`
  all returned rc 0. Each warned and was not blocked.
- adopt: `adopt` (non-TTY) only lists the entries (rc 0). `adopt --json`
  returns `{resolved: [], linked: [], unknown: [...5], warnings: []}`.
  `adopt --add pre1 --json` added and linked it (`resolved[0].choice=add`,
  `profile=work`). `adopt --remove pre2` printed
  `Backed up …/pre2 to …/backups/<run2>/claude-code/pre2 and removed it`.
  `adopt --add extlink` (a link to a folder without SKILL.md) failed with
  `error: $T/ext has no SKILL.md; a skill folder needs one`, rc 1, and nothing
  changed.
- Layer conflict and repair: after a hand edit enabled d2,
  `status --json` returned a `warnings` entry of `type: layer-conflict` with a
  `fix`. `use work` was refused (rc 1) with
  `cannot switch to profile 'work': - layer 'design-principles' … repair …`.
  `layer repair design-principles --keep d2 --json` (with unknown entries
  present) returned rc 0, `disabled: [d1]`, `linked: [d2]` and
  `unlinked: [d1]`.
- Git source: with `RESPEC_GIT_BASE_URL=file://$T/gitbase`,
  `add acme/skills -p work --json` recorded repo, path, commit and digest and
  linked `gs`. `update --check` printed
  `gs  update available 7c8bf6eb2934 -> 9bc451200f78`. `update gs --json`
  returned `result: updated`, and the linked file shows `v2`.
- `use other --json` (with `stray` present) returned rc 0 and removed the 4
  work skills.
- Restore: `restore --list --json` lists both runs (the takeover run has
  `takeover: [claude-code]`). `restore --overwrite` printed
  `Backed up …/stray … and removed it` and
  `Restored claude-code from …/<takeover run>/claude-code`, then
  `respec released its folders; no profile is active.` `state.json` was empty
  (`owned: {}`, `active_profile: null`). A second `restore --overwrite`
  failed cleanly with `respec owns no folders; nothing to restore …`.
- **`diff before.snap after.snap`: no differences. `~/.claude` is
  byte-identical after restore.** That covers pre1 (added to the profile),
  pre2 (removed with backup), notes.md and extlink (left unknown),
  settings.json, and the file modes.

### smoke2.sh: clashing pre-existing entry at first takeover (non-TTY)

`~/.claude/skills/d1/` (hand-made) and `keepme/` existed. Profile `work` has
skill `d1`.

- `use work`: rc 1, before any takeover (no `backups/` dir). The message was
  `cannot switch … - …/d1 (folder). No profile is active, so they can only be removed … 'respec adopt --remove <name>'. Or pass '--unknown remove'`.
  The `--json` form has every key, `backups: {}` and `error`.
- `use work --unknown add` failed with a clear error: no active profile, so use
  `--unknown remove`.
- `use work --unknown remove --json`: rc 0. `backups.claude-code` is set,
  `resolved[0]` is the d1 remove with its backup path, and the `keepme`
  warning is typed `unknown-entry`.
- `adopt --add keepme`: added and linked it, and the profile.yaml entry is
  `enabled: true`.
- `restore --overwrite --json`: rc 0, `removed: [d1, keepme]`,
  `released: [claude-code]`. **`~/.claude` is byte-identical to the pre-run
  snapshot.**

### smoke3.sh: findings from the previous report, rechecked

- Previous finding 1 (`layer off` did not relink) is **fixed**:
  `layer off design-principles --json` on the conflicted active profile
  returns `linked: [d2]`, and d2 is in the folder.
- Previous finding 2 (refusal said "switch") is **fixed**: a refused
  `layer disable rv` now says `cannot refresh profile 'work': … Profile 'work' was left unchanged.`
- Previous findings 3 and 4 (unknown entries block repair and refresh, and
  first-takeover entries stay unknown) are **fixed** by warn-not-block and the
  takeover prompt, as smoke.sh shows.

## Core API for a TUI Sync action (`scratchpad/intb8d/api.py`)

On an active profile with two hand-made entries:

- `adopt.unresolved(rh)` returned `[('x1','folder',False),('x2','folder',False)]`.
- `adopt.choices('work')` returned `('add','remove')`, and
  `adopt.choices(None)` returned `('remove',)`.
- `adopt.resolve(rh, entries, decide, 'work', done=done)` with `{x1: add, x2: remove}`
  returned Resolutions whose `.describe()` is the CLI text.
- `adopt.link_added(rh, home, res)` returned `linked=[…/x1]` and
  `blocked=[]`. Afterwards `unresolved` was `[]` and x1 was a symlink.
- `adopt.adopt(rh, home, decide)` (whole flow) added and linked x3.

The API is usable. The TUI already uses it: `ChoiceScreen` with
`adopt.choices`, `action_adopt` calls `adopt.adopt`, and activation calls
`resolve`/`taken_over`/`link_added`. One caveat for 011: the low-level
`resolve()` neither refuses adds into a profile with layer conflicts nor rolls
back on failure. `adopt.adopt()` does both. A Sync action should call
`adopt.adopt(decide=<mapping>)`, or call `switch.refuse_layer_conflicts`
itself before it uses `resolve`.

## JSON key consistency (use / adopt / restore)

| Command                 | Applied choices                  | Remaining entries                                          | On error                                             |
| ----------------------- | -------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------- |
| `use --json`            | `resolved` (Resolution dicts)    | `warnings[type=unknown-entry]`                             | same full shape + `error`                            |
| `adopt --json`          | `resolved`                       | `unknown` (Unknown dicts); `warnings: []`                  | only `resolved`, `error`, `warnings` (`_fail_after`) |
| `restore --json`        | **`unknown`** (Resolution dicts) | none                                                       | only `resolved`, `error`, `warnings` (`_fail_after`) |
| `status --json`         | none                             | `folders[].unknown`; `warnings` holds only layer conflicts | none                                                 |
| layer/enable/add/update | none                             | `warnings[type=unknown-entry]`                             | none                                                 |

## Findings (cross-ticket, non-blocking)

1. **JSON key clash: `unknown` means different things.** `restore --json`
   success puts the applied Resolutions under `unknown` (`cli.py:1182`).
   `adopt --json` uses `unknown` for the entries still unresolved
   (`cli.py:1071`), and `use` uses `resolved` for applied choices. Restore's
   own failure path (`_fail_after`) also emits `resolved`, so one restore run
   names the same data `unknown` on success and `resolved` on failure. Rename
   restore's key to `resolved`.
2. **Remaining unknown entries are reported in three places.** `use` and the
   change commands put them in `warnings` as `unknown-entry`. `adopt` puts
   them in `unknown` with `warnings: []`. `status` puts them in
   `folders[].unknown` with no `unknown-entry` warnings. Each choice can be
   defended (adopt and status report them as their main content), but a JSON
   consumer cannot read one key everywhere. Document the convention or align
   it.
3. **The error JSON shape differs from the success shape for adopt and
   restore.** `_fail_after` emits only `resolved`, `error` and `warnings`, so
   `linked`/`unknown` (adopt) and `restored`/`released`/... (restore) are
   missing on failure. `use` keeps its full shape plus `error`
   (`_SwitchRun.finish`).
4. **Duplicate helpers:**
   - `switch._real` (`switch.py:112`) is identical to `unknown.real`
     (`unknown.py:49`).
   - `adopt._copy_entry` (`adopt.py:125`) and `restore._put_back`
     (`restore.py:301`) are the same link-preserving copy with cleanup. Only
     the error type and text differ.
   - `adopt._same_content` (digest only) and `restore._same` (digest plus
     modes) are near-duplicates with different semantics. That is
     intentional but undocumented.
   - `layers.add_skill` (`layers.py:186-190`) still inlines "other enabled
     members" instead of using `profiles.enabled_members()`, which
     `layers.py:321` does use.
5. **Dead code:** `profiles.exclusivity_problems()` (`profiles.py:226`) has no
   caller in src or tests (still open from the last report).
6. **Minor:** `restore --overwrite --json` reports `"backup": null` when it
   restores the default takeover backups. The field holds the named backup
   argument only. The real sources are in `restored`.
7. **Noted for 011:** use `adopt.adopt()` instead of a bare `resolve()` (see
   the API caveat above).

No blocking integration failures. fix-6 composes with 001-010, fix-1 to fix-5
and git sources. Previous findings 1-4 are resolved.
