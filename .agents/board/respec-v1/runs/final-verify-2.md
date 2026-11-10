# Final verify 2

Result: **PASS**

- Repository: `/Users/maxilr/Documents/GitHub/respec`
- Branch: `codex/respec-v1`
- Verified SHA: `a530f42d9ecf24fb29fab82e87a519a4f245900b` (confirmed at start
  and again after all gates)
- Date: 2026-11-10
- Skill: verify-before-handoff. No `AGENTS.md` exists in the repository. Gates
  from `README.md`/`pyproject.toml` plus the requested lock and Prettier checks.
  No git pre-commit config; `.git/hooks/pre-push` exists (push guard, not
  exercised: no push performed).

## Working tree

Uncommitted orchestrator planning artifacts only (not touched, not covered by
the clone check):

- Modified: `.agents/board/respec-v1/tickets/001.md` through `011.md`
- Untracked: `.agents/board/respec-v1/orchestration.md`,
  `.agents/board/respec-v1/runs/` (run reports, including this file)

No source, test, or config file is modified or untracked (13 status entries,
all under `.agents/board/respec-v1/`).

## Gates in the worktree

| Command                                              | Result                                       |
| ---------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                   | exit 0, `Audited 27 packages`                |
| `uv lock --check`                                    | exit 0, `Resolved 28 packages`               |
| `uv run pytest -q`                                   | exit 0, `589 passed in 251.20s`              |
| `uv run black --check .` (black 26.10.1, default 88) | exit 0, `45 files would be left unchanged.`  |
| `npx --yes prettier@3.3.3 --check <files>`           | exit 0, `All matched files use Prettier ...` |

Prettier files: `README.md`, `src/respec/shipped/profile-maker/SKILL.md`,
`src/respec/shipped/respec/SKILL.md`, `.agents/board/respec-v1/spec.md`,
`.agents/board/respec-v1/tickets/*.md` (001-013, working-tree versions),
`src/respec/targets.yaml`. No project Prettier config or `package.json`;
Prettier 3.3.3 defaults used.

## Fresh-clone sanity check

```sh
git clone -q --no-hardlinks /Users/maxilr/Documents/GitHub/respec <scratch>/fv2/clone
git checkout -q a530f42d9ecf24fb29fab82e87a519a4f245900b   # rev-parse confirmed
UV_OFFLINE=1 uv sync --frozen               # exit 0 (installed from local uv cache)
uv lock --check --offline                   # Resolved 28 packages
UV_OFFLINE=1 uv run --frozen pytest -q      # 589 passed in 249.59s, exit 0
uv run --offline --frozen black --check .   # 45 files would be left unchanged
```

No network needed. The suite does not depend on untracked files.

## Real-CLI smoke (temp `HOME`)

Binary: `/Users/maxilr/Documents/GitHub/respec/.venv/bin/respec`, with `HOME`
and `XDG_CONFIG_HOME` set to a scratch dir, stdin `/dev/null`. Seeded
`~/.claude/skills/preexisting/SKILL.md` and a local `./src/my-skill`.

1. `respec profile new work --target claude-code` -> exit 0, `Created profile
'work' ...`
2. `respec profile new spare --target claude-code` -> exit 0, `Created profile
'spare' ...`
3. `respec add ./src/my-skill -p work` -> exit 0, `Added 'my-skill' to profile
'work'`
4. `respec use work` -> exit 0, backed up claude-code folder,
   `Switched to profile 'work': installed 3 skills (7 links)`, warning that
   `preexisting` is a folder respec did not place (run `respec adopt`).
5. `respec status --json` -> exit 0, `active_profile: "work"`, `targets:
["claude-code"]`; claude-code folder: `my-skill` (origin profile),
   `profile-maker`, `respec` (origin shipped); shipped skills also in `agents`
   and `oh-my-pi`; `unresolved` lists `preexisting`; `warnings: []`.
6. `respec profile remove spare` (inactive) -> exit 0, `Removed profile
'spare'`, folder moved to `~/.respec/removed-profiles/<ts>/spare` with
   recovery hint. `respec profile list` then shows only `work`.
7. `respec restore` -> exit 0, `Removed 3 skills (7 links) placed by respec`,
   restored claude-code from backup, agents and oh-my-pi `from nothing`,
   `no profile is active`. Afterwards `~/.claude/skills` holds only
   `preexisting` with original content; `~/.agents` and `~/.omp` are gone;
   `status --json` shows `active_profile: null`, `targets: []`.

## Skipped checks

- No linter/typechecker configured (no ruff/mypy in `pyproject.toml`).
- TUI not exercised interactively (covered by TUI tests in the suite).
- Network git sources (`add owner/repo`, `update`, `profile install`) not
  exercised in the smoke.
- Pre-push hook not exercised (no push in scope).

## Guard denials

None.
