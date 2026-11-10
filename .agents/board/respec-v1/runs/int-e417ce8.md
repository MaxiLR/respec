# Integration check: e417ce8 (after ticket 009 merge)

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- Head: `e417ce87a36d965d3385c903e37b4153cd6f3791` (matches expected)
- Change range: `b8d1aee..e417ce8` (18 files, +1561/-35; commits 5dc0cd1,
  7ee413f and merge e417ce8)
- AGENTS.md: none in the repository. I followed the global CLAUDE.md and
  verify-before-handoff.
- Worktree state: only the expected orchestrator files under
  `.agents/board/respec-v1/` are dirty, plus this report. I changed no code.
- Spec basis: decision 11 as amended by the engineer. Shipped `respec` and
  `profile-maker` go into every registered target whenever a profile is active,
  with no opt-out. Global `config.yaml` skills go only to the active profile's
  targets.
- Scratch:
  `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/inte417/`
  (`smoke.sh`, `smoke2.sh`, `tuiscript/pilot.py`, and the `*.log` and
  `*.compact.log` files)

## Gates

| Gate                                                                     | Result                        |
| ------------------------------------------------------------------------ | ----------------------------- |
| `UV_OFFLINE=1 uv sync --frozen`                                          | PASS                          |
| `UV_OFFLINE=1 uv lock --check`                                           | PASS (Resolved 28 packages)   |
| `uv run --frozen pytest -q -rs`                                          | PASS, 386 passed in 59.52s    |
| `uv run --frozen black --check .`                                        | PASS, 32 files unchanged      |
| `npx --no-install prettier --check README.md spec.md shipped/*/SKILL.md` | PASS (3.9.10)                 |
| Prettier on committed `tickets/*.md` (HEAD blobs via stdin)              | PASS, no diffs                |
| `uvx --offline ruff check src tests --select F`                          | PASS                          |
| `uvx --offline vulture src --min-confidence 60`                          | only Typer command false hits |

No tests were skipped. In tests, the `shipped_skills` autouse fixture removes
the shipped skills unless a test is marked `shipped`. The smoke runs below use
the real defaults: `shipped_names() == ('profile-maker', 'respec')`.

## End-to-end smoke with real defaults (temp `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME`; stdin `/dev/null`; no network)

### smoke.sh

Starting state: `~/.claude/skills` held `pre1/` (a 755 file), `pre2/`,
`notes.md` and the symlink `extlink`. `~/.claude/settings.json` existed.
`~/.agents/skills/apre/` and `~/.agents/other.txt` existed. `~/.omp` did not
exist. The snapshot covered the whole `HOME` except `.respec`: type, mode, link
target and sha256 of every path.

- `profile new pi --target oh-my-pi`, `add p1 -p pi`, `profile new work
--target claude-code`, `add d1 d2 rev -p work`: rc 0.
- Reserved name: `add $T/src/respec -p work` printed
  `error: cannot add 'respec' to profile 'work' ('respec': respec ships a skill … installs it into every target). Nothing was changed.`
  It returned rc 1, and the profile still held only d1, d2 and rev.
- **First takeover:** `use pi --json` (non-TTY) returned rc 0.
  - `backups` covers claude-code and agents. oh-my-pi has no backup because its
    folder did not exist.
  - `installed` has `p1` in omp and `profile-maker` and `respec` as symlinks to
    `~/.respec/shipped/<name>` in **all 3 folders**.
  - The 5 pre-existing entries came back as typed `unknown-entry` warnings.
  - `state.json` records `owned.oh-my-pi.created = [.omp/agent/skills,
.omp/agent, .omp]`, deepest first.
  - `status` shows the shipped skills in every folder with
    `Targets: oh-my-pi`.
- **Switch:** `use work --json` removed only `omp/p1` and installed d1, d2
  and rev. The shipped links were kept, so they are not in `removed` or
  `installed`.
- Unrelated unknown entry: with `stray/` in a folder, `layer use` and
  `layer add-skill` warned and were not blocked.
- **Adopt:** `adopt --add pre1 --json` added and linked it. `adopt --remove
pre2` backed it up and removed it. A shipped link replaced by a hand-made
  folder (`omp/respec`) was then handled as follows:
  - `adopt --add respec` was refused with rc 1, and the message suggests
    `--remove`.
  - `adopt --remove respec --json` backed it up (`replaced: true`) and
    `linked` holds `omp/respec` again (`relink_lasting`).
- **Layer conflict and repair:** after a hand edit enabled d2, `use work` was
  refused (rc 1) with the repair hint. `layer repair design-principles --keep
d2 --json` returned rc 0 with `disabled [d1]`, `linked [d2]` and
  `unlinked [d1]`.
- **Git source over file://:** `add acme/skills -p work --json` recorded repo,
  path, commit and digest and linked `gs`. `update --check` printed
  `gs  update available fa33ebd3418e -> 17ca3559ca78`. `update gs --json`
  returned `result: updated`, and the linked file now ends in `v2`. A repo
  whose skill is named `profile-maker` was refused before any change.
- Switching back with `use pi --json` removed d2, rev, pre1 and gs. The
  shipped links stayed in all 3 folders.
- **Restore:** `restore --overwrite --json` returned rc 0.
  - `restored` shows claude-code and agents from the takeover run, and
    oh-my-pi from `null`.
  - `removed` lists all 6 shipped links plus `p1`.
  - `stray` appears under `overwritten`, with its backup.
  - `released` lists all 3 folders. `state.json` is empty.
  - A second `restore` failed cleanly ("owns no folders").
- **`diff before.snap after.snap`: no differences. `HOME` (except `.respec`)
  is byte-identical, and `.omp` (created parents) was removed.**

### smoke2.sh: reserved-name entry before first takeover, global skills, partly existing parents

- `~/.agents/skills/respec/` (the user's own skill) existed. `~/.omp/config.yml`
  existed, but `~/.omp/agent` did not.
- `use cc` (profile targets: claude-code only) was blocked before the
  takeover, with no `backups/` folder. The message says it can only be removed.
  `--unknown add` was refused because no profile is active.
  `use cc --unknown remove --json` returned rc 0: agents was backed up, the
  user's `respec` folder went to a backup, and the shipped links went into all
  3 folders.
- Global skill: with `config.yaml` set to `global: {skills: [gnotes]}`,
  `use cc` linked `claude/gnotes`. `add …/gnotes -p cc` was refused because
  gnotes is a global skill. `use pi` removed `claude/gnotes` and linked
  `omp/gnotes`, so global skills follow only the active targets.
- `restore --json` returned rc 0 and put the user's own `respec` back from the
  takeover backup. **`HOME` is byte-identical.** `~/.claude` (created) is gone.
  `~/.omp/agent` was removed and `~/.omp/config.yml` stays.

## TUI (010) under real defaults: Pilot (`tuiscript/pilot.py`, 120x50)

- Profile `pi` (oh-my-pi only). `~/.claude/skills/pre1` existed beforehand.
- Activating opened the takeover `AdoptDialog` for `pre1` (add/remove).
  Choosing remove gave the feedback `Resolved 1 unknown entries: Backed up … pre1 … and removed it`.
- The status panel shows the shipped skills in all 3 folders:
  - `claude-code | ● profile-maker symlink | ● respec symlink`
  - `agents | ● profile-maker symlink | ● respec symlink`
  - `oh-my-pi | ● p1 symlink | ● profile-maker symlink | ● respec symlink`
- **Finding 1:** I replaced the shipped link `~/.agents/skills/respec` with a
  hand-made folder, then pressed `r` and `a`. The dialog offered
  **both `unknown-0-add` and `unknown-0-remove`** for it. Choosing add failed
  safely: `error: cannot add 'respec' … Choose remove instead ('respec adopt --remove respec') …`.
  Nothing changed.

## JSON key consistency

- `use --json` `installed[]` items include `"digest": null` for symlinks, but
  `state.json` leaves `digest` out (`Installed.to_dict`). This is minor and was
  there before 009.
- `status --json` and the TUI do not mark which skills are shipped or global.
  `skills[]` entries have only `name`, `path` and `mode`, so a consumer cannot
  tell `respec` (shipped) from a profile skill. The same goes for the text
  `status`, where `Targets: oh-my-pi` sits above shipped skills in all folders.
- `restore --json` now uses `overwritten` for set-aside entries and `unknown`
  for prompt and flag resolutions. These are still Resolution dicts, while
  `use` and `adopt` call them `resolved` (earlier finding 1, partly addressed).
  `backup: null` on a default restore is unchanged.

## Findings (cross-ticket, non-blocking)

1. **TUI does not apply the reserved-name rule to the dialog's choices
   (009 x 010).** `AdoptDialog.compose` calls `adopt.choices(self.profile)`
   (`tui.py:283`) without `entry` or `respec_home`. The CLI prompt passes
   both (`cli.py:260`), so for an entry named `respec`, `profile-maker` or a
   global skill the CLI offers only remove, while the TUI offers "Add to
   profile …". Choosing add is refused safely, but the error tells the user to
   run a CLI command. This affects the `a` dialog and the switch/takeover
   dialogs alike. Fix: pass the entry and `self.app.respec_home`.
2. **The spec text is stale for the amended decision 11.** `spec.md` decision
   11 still says global items (respec's own skills) go "only into the active
   profile's targets". Ticket 009's AC still says "a profile can opt out with
   `system: false`". The code and README follow the amendment (all targets, no
   opt-out). Update the spec and ticket wording so later reviews don't flag it.
3. **Duplicate helpers (new in 009):**
   - `restore._respec_link` (`restore.py:147-151`) builds the
     profiles/global/shipped root list itself instead of calling
     `global_skills.source_roots()`, which `unknown.is_managed` and
     `switch.remove_installed` use.
   - The "lasting names" set (`load_global` + `shipped_names`) is built twice,
     in `switch.relink_lasting` and `switch._kept`.
   - The reserved-name check exists twice. `switch._check_global` re-derives
     shipped and global clashes with its own messages, while
     `global_skills.reserved()` / `refuse_reserved()` serve the add paths.
     `adopt._reserved` wraps `reserved()` with a shipped-only fallback.
   - `global_skills._same_tree` (filecmp) is a fourth tree comparison, next to
     `adopt._same_content`, `restore._same` and `unknown.digest`.
   - Still open from the last report: `switch._real` is the same as
     `unknown.real`, and `adopt._copy_entry` is the same as
     `restore._put_back`.
4. **Dead code:** `profiles.exclusivity_problems()` (`profiles.py:226`) still
   has no caller. vulture flagged nothing else apart from Typer command
   functions.
5. **UX note:** a user's own pre-existing skill named `respec` or
   `profile-maker` blocks the first switch. The message gives only "can only be
   removed" and does not say the name clashes with a shipped skill (the
   `adopt --add` refusal does say so). Restore puts the user's skill back
   correctly.

No blocking integration failures. 009 composes with takeover, switch, adopt,
layer repair, git sources, restore (byte-identical, created parents removed)
and the TUI.
