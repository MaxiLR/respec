# Integration check: 35cad16 (tickets 001, 002, 006; just merged 006)

Read-only check. No code changed, no tickets updated, no commits/pushes.

## Checkout

- `git rev-parse HEAD` -> `35cad160ce8cb6a87396383c0656cb3370ee8a4c` (matches expected)
- `git status --short`: only orchestrator files under `.agents/board/respec-v1/`
  (tickets 001/002/006 modified, `orchestration.md` and `runs/` untracked); ignored.
- No AGENTS.md, glossary or decision records present in the worktree.
- Change range `a2f222e1..35cad160`: README.md, src/respec/{cli,items,profiles,switch}.py,
  tests/test_items.py (+663/-4). Commits: 2974fb0, merge 35cad16.

## Gates

| Command                                                | Result                                     |
| ------------------------------------------------------ | ------------------------------------------ |
| `uv sync --frozen`                                     | PASS (Audited 24 packages)                 |
| `uv run pytest -q`                                     | PASS: 73 passed in 1.84s, 0 skipped        |
| `uv run black --check .`                               | PASS: 16 files would be left unchanged     |
| `npx prettier@3 --check README.md .agents/.../spec.md` | PASS: All matched files use Prettier style |

## Smoke test (temp RESPEC_HOME and --home in scratchpad)

`profile new w -t claude-code -t agents`, `use w`, `add <dir> --json`, `disable`, `enable`,
`remove --json`, `status`: links created in both target folders on add/enable, removed on
disable/remove; `profile.yaml` keeps `enabled: false` entry after disable; profile skill
folder deleted on remove; status shows no managed items. JSON shape:
`profile, item, action, enabled, path, active, linked, unlinked`.

## Cross-ticket contract review (006 vs 001/002)

- `profiles.save_profile` (new, atomic tmp+`os.replace`) is now the single
  `profile.yaml` writer; `create_profile` refactored to use it. Output unchanged
  (`safe_dump`, `sort_keys=False`). Compatible.
- `switch.SwitchBlocked(RespecError)` replaces the plain `RespecError` from `_preflight`.
  Subclass, so existing 002 callers and `cli._fail` behave identically. Compatible.
- `items._refresh` re-runs `switch.use` for the active profile; state.json stays
  truthful via 002's engine. `remove` correctly orders `except SwitchBlocked` before
  `except RespecError`.
- Item-name validation reuses `profiles.NAME_PATTERN`/`NAME_RULE`; consistent with
  `profile.yaml` parsing.

## Findings (none blocking)

1. Low-medium, inherited from 002 and amplified by 006: every item change re-runs a
   full switch. If a recorded symlink in a target folder was replaced by a foreign
   entry, `_preflight` accepts it (path is recorded), `_remove` leaves it (mode
   symlink, no longer a link), then `_install` hits `FileExistsError` -> generic
   `RespecError` "did not complete", no profile active. Because this is not
   `SwitchBlocked`, `items` does not undo the profile change. So a single
   `enable`/`disable`/`add` can deactivate the profile. Relevant to adopt (ticket on
   decision 5) and the interrupted-switch journal risk.
2. Minor duplication: `items._skill_folder` duplicates the inline
   `profile.path / profiles.SKILLS_DIR / skill` used twice in `switch._preflight`.
3. Minor: `items.add` loads the profile, then `add_local` loads it again, and the new
   item name is recovered by set difference rather than returned. `add_local`'s
   `enabled` parameter is not used by any caller (presumably a seam for 007).
4. Cosmetic: with copy-mode installs, refresh deletes and re-copies every item;
   `linked`/`unlinked` are set differences, so re-copied paths are not reported.

## Vocabulary

Consistent with spec: "item" for CLI/JSON (`respec add/remove/enable/disable <item>`),
`skills:` in `profile.yaml`, "profile", "target", "active profile". No drift found.
No dead code beyond the unused `enabled` parameter noted above.
