# Integration check: 9c8f59f (after ticket 011 merge)

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- Head: `9c8f59f69e8c0bc2a4dba06407332ad3e5b0d859` (matches expected)
- Change range: `e417ce8..9c8f59f` (12 files, +2699/-92). The main changes are
  `tui.py` (+1143), new `sync.py` and `messages.py`, the public `switch.plan`,
  the git timeout and cancel in `sources.py`, and `items.user_path`.
- AGENTS.md: none in the repository. I followed the global CLAUDE.md and
  verify-before-handoff.
- Worktree state: only the expected orchestrator files under
  `.agents/board/respec-v1/` are dirty, plus this report. I changed no code.
- Scratch:
  `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/int9c8/`
  (`gates.log`, `smoke.sh`/`smoke.log`, `smoke2.sh`/`smoke2.log`,
  `tuisetup.sh`, `tuiscript/pilot.py`, `plancheck.py`)
- No guard denials.

## Gates

| Gate                                                                     | Result                            |
| ------------------------------------------------------------------------ | --------------------------------- |
| `UV_OFFLINE=1 uv sync --frozen`                                          | PASS (Audited 27 packages)        |
| `UV_OFFLINE=1 uv lock --check`                                           | PASS, rc 0 (Resolved 28 packages) |
| `uv run --frozen pytest -q -rs`                                          | PASS, 434 passed in 101.63s       |
| `uv run --frozen black --check .`                                        | PASS, 36 files unchanged          |
| `npx --no-install prettier --check README.md spec.md shipped/*/SKILL.md` | PASS                              |
| `uvx --offline ruff check src tests --select F`                          | PASS                              |
| `uvx --offline vulture src --min-confidence 60`                          | see dead code below               |

No tests were skipped. In tests, shipped skills stay off unless a test is
marked `shipped`. The smoke runs below use the real defaults:
`shipped_names() == ('profile-maker', 'respec')`.

## End-to-end smoke with real defaults (temp `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`; stdin `/dev/null`; git over `file://`; no network)

### smoke.sh (same scenario as int-e417ce8)

- `profile new`, `add` for profiles `pi` (oh-my-pi) and `work` (claude-code):
  every call returned rc 0.
- Reserved name: `add …/respec -p work` was refused with rc 1 ("respec ships
  a skill of that name and installs it into every target"), and the profile
  did not change.
- First takeover, `use pi --json`, returned rc 0. The 5 pre-existing entries
  came back as `unknown-entry` warnings. The shipped links went into all 3
  folders.
- `use work --json` returned rc 0. Unrelated unknown entries only warned
  during `layer use` and `layer add-skill`.
- Adopt:
  - `adopt --add pre1 --json` returned rc 0.
  - `adopt --remove pre2` backed the entry up and removed it.
  - With a hand-made `omp/respec` folder in place of the shipped link,
    `adopt --add respec` was refused (rc 1, the message suggests `--remove`).
    `adopt --remove respec --json` returned rc 0 and the shipped link came
    back.
- Layer conflict: after a hand edit enabled d2, `use work` was refused (rc 1)
  with the repair hint. `layer repair design-principles --keep d2 --json`
  returned rc 0.
- Git source over file://:
  - `add acme/skills -p work --json` linked `gs`.
  - `update --check` printed `gs  update available 2fd5b2bb913c -> dda10ea9c4f0`.
  - `update gs --json` returned `result: updated`, and the file now ends in
    `v2`.
  - A repo with a skill named `profile-maker` was refused with rc 1.
- `use pi --json` returned rc 0.
- Restore:
  - `restore --overwrite --json` returned rc 0.
  - A second `restore` failed cleanly ("owns no folders").
  - **`HOME (excluding .respec) BYTE-IDENTICAL after restore`**, and
    `.omp removed`.

### smoke2.sh: user's own `respec` skill before takeover, global skill

- `use cc` was blocked before the takeover, saying the entry can only be
  removed. `--unknown add` was refused because no profile is active.
  `use cc --unknown remove --json` returned rc 0.
- Global skill `gnotes` from `config.yaml`:
  - It was linked into claude-code.
  - `add …/gnotes -p cc` was refused because gnotes is a global skill.
  - After `use pi`, it moved to `omp/gnotes`.
- `restore --json` returned rc 0. **`HOME BYTE-IDENTICAL after restore`**.

## TUI via Pilot (real defaults, 120x60): `tuisetup.sh` then `tuiscript/pilot.py`

Setup: profile `work` (claude-code) with d1, d2 and rev. d1 and d2 are in the
exclusive layer `design-principles`, with d2 disabled. The global skill
`gnotes` is set in `config.yaml`. A CLI `use work` installed 9 skills on an
empty `HOME`.

1. `s` opens `SyncScreen`. Summary: **"All in sync: no unknown entries, layer
   conflicts or link problems."**
2. I then made four kinds of drift:
   - deleted the `~/.agents/skills/respec` link;
   - replaced `~/.omp/agent/skills/respec` with a hand-made folder;
   - added `~/.claude/skills/stray`;
   - replaced the `rev` link with an edited copy;
   - hand-enabled d2.

   After `s`, the summary read **"Found 3 unknown entries, 1 layer conflict,
   2 link problems."**
   - `rev` (`replaced=True`) and `stray` were offered add and remove. The
     `respec` folder was offered **remove only**, so the reserved-name rule
     holds in Sync.
   - Conflict: `design-principles ('d1', 'd2')`.
   - Links: `respec (agents) is missing` and
     `d2 (claude-code) is enabled in the active profile but not linked`. These
     include the shipped skills through `switch.plan`.

3. Resolving all 3 by remove backed each one up and removed it. The summary
   became "Found 1 layer conflict, 2 link problems."
4. "Repair layer" (keep d1) logged `Repaired … kept 'd1'`, `disabled 'd2'` and
   `linked …/rev`. The summary went back to **"All in sync"**.
   - Afterwards the agents/respec link, the omp/respec link and the rev link
     were all symlinks again, and stray was gone.
5. Profile editing: `e` opened `ProfileScreen`, which marks shipped and global
   skills ("shipped with respec, in every target", "global (config.yaml), in
   this profile's targets"). `a` opened `AddDialog`, and adding
   `src/respec` gave
   `error: cannot add 'respec' to profile 'work' (… respec ships a skill …). Nothing was changed.`
   The profile skills stayed `['d1', 'd2', 'rev']`.
6. Sync again: "All in sync".

## Cross-ticket contracts

- **switch.plan vs use:** `plancheck.py` on the TUI home after a clean `use`
  found that the `(target, skill, destination)` tuples of `switch.plan` and
  `state.installed` are the same set (9 = 9, no differences). `plan` is a thin
  wrapper over `_plan_all`, the same planner that `use`, `relink_lasting` and
  the refresh path call. No drift risk found.
- **Reserved-name check, TUI vs CLI:** I checked six paths and they agree:
  - CLI `add` local and git: refused.
  - CLI `adopt --add`: refused, with a hint.
  - CLI prompt (`_prompt_choice`): remove only.
  - TUI `AdoptDialog` (`tui.py:433`) and the Sync choices (`tui.py:1131`):
    both pass the entry and `respec_home` to `adopt.choices`, so they offer
    remove only.
  - TUI `AddDialog`: refused through `items.add`.

  int-e417ce8 finding 1 is fixed. One small difference remains:
  `cli._prompt_choice` reads `paths.respec_home()` instead of
  `homes.respec_home`. Both give the same value today.

- **Messages:** the CLI and TUI now share `messages.py`, which removes the
  duplicated text from int-e417ce8 / 011 N3.

## Dead code (vulture, Textual and Typer framework hooks excluded)

- `profiles.exclusivity_problems()` (`profiles.py:226`) still has no caller.
- `sources.BASE_URL_ENV` (`sources.py:41`) is an alias of
  `profiles.GIT_BASE_URL_ENV` that nothing uses.

## JSON key consistency

- `restore --json` uses `unknown` for the resolutions it applied, while `use`
  and `adopt` call them `resolved`.
- `adopt --json` uses `unknown` for the entries still unresolved. The same key
  name means different things in two commands.
- `use --json` `installed[]` items carry `"digest": null` (8 in one run),
  while `state.json` leaves the key out.
- `restore --json` returns `backup: null` on a default restore.
- `status --json` and the text `status` still do not mark which skills are
  shipped or global. The TUI now marks them, so the CLI and TUI differ.
- Sync exists only in the TUI. There is no CLI or `--json` counterpart (in
  scope as built; noting it for parity).

## Cleanup candidates for fix-7

1. Dead code: remove `profiles.exclusivity_problems` and
   `sources.BASE_URL_ENV`.
2. In `cli.py`, the aliases `_source_label = messages.source_label` and
   `_short = messages.short` could call `messages.*` directly.
   `messages.sourced_change` builds its own `linked` lines instead of calling
   `link_lines`.
3. Duplicate helpers that remain:
   - `switch._real` is the same as `unknown.real`.
   - `adopt._copy_entry` is the same as `restore._put_back`.
   - Four tree comparisons: `adopt._same_content`, `restore._same`,
     `global_skills._same_tree` and `unknown.digest`.
   - `restore._respec_link` builds its own root list instead of calling
     `global_skills.source_roots()`.
   - `switch._check_global` re-derives the reserved names instead of using
     `global_skills.reserved()`.
   - The lasting-names set is built twice (`switch.relink_lasting` and
     `switch._kept`).
   - `profiles.enabled_members` overlaps with the logic in `layers.add_skill`.
4. `sync.check` loads `state.json` twice (in `check` and in
   `_link_problems`). Pass the state through instead.
5. `cli._prompt_choice`: use `homes.respec_home`, not `paths.respec_home()`.
6. Unify the JSON keys listed above: `resolved` vs `unknown`, the meaning of
   adopt's `unknown`, `digest: null`, `backup: null`, and shipped or global
   markers in `status`.
7. Carried over from the 011 review:
   - N1, a Sync deadlock: an edited copy plus a layer conflict in the active
     profile leaves add and repair each refusing.
   - N2, the wording when a global skill's source folder is missing.
8. Carried over from int-e417ce8:
   - A user's own pre-existing `respec` or `profile-maker` folder gives "can
     only be removed" at the first takeover without saying it clashes with a
     shipped skill.
   - `spec.md` decision 11 and decision 5 (keep-unmanaged) are stale against
     the engineer's amendments in the ledger.

## Verdict

Green at 9c8f59f. 434/434 tests pass and every gate passes. The CLI smoke and
the TUI Sync and editing check under real defaults behave correctly, and
restore is byte-identical. No blocking cross-ticket issues. The findings above
are non-blocking cleanup for fix-7.
