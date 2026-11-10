# Final verify 1

Result: **PASS**

- Repository: `/Users/maxilr/Documents/GitHub/respec`
- Branch: `codex/respec-v1`
- Verified SHA: `4092c83fc1d41bd68a9cc763b1fe36694b5d0f00` (confirmed at start
  and again after all gates)
- Date: 2026-11-10
- Skill: verify-before-handoff. No `AGENTS.md` exists in the repository. Gates
  taken from `README.md` (`uv sync`, `uv run pytest`, `uv run black --check .`)
  plus the requested lock and Prettier checks.

## Working tree

Uncommitted planning artifacts only (not touched, not covered by the clone
check):

- Modified: `.agents/board/respec-v1/tickets/001.md` through `011.md` (ticket
  claim edits)
- Untracked: `.agents/board/respec-v1/orchestration.md`,
  `.agents/board/respec-v1/runs/` (run reports, including this file)

No source, test, or config file is modified or untracked.

## Gates in the worktree

| Command                                              | Result                                       |
| ---------------------------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                                   | exit 0, `Audited 27 packages`                |
| `uv lock --check`                                    | exit 0, `Resolved 28 packages`               |
| `uv run pytest`                                      | `559 passed in 198.66s`                      |
| `uv run black --check .` (black 26.10.1, default 88) | exit 0, `43 files would be left unchanged.`  |
| `npx --yes prettier@3.3.3 --check <files>`           | exit 0, `All matched files use Prettier ...` |

Prettier files: `README.md`, `src/respec/shipped/profile-maker/SKILL.md`,
`src/respec/shipped/respec/SKILL.md`, `.agents/board/respec-v1/spec.md`,
`.agents/board/respec-v1/tickets/*.md` (001-013, working-tree versions),
`src/respec/targets.yaml`. There is no project Prettier config or
`package.json`; Prettier 3.3.3 defaults were used.

## Fresh-clone sanity check

```sh
git clone -q --no-hardlinks /Users/maxilr/Documents/GitHub/respec <scratch>/clone
git checkout -q 4092c83fc1d41bd68a9cc763b1fe36694b5d0f00
UV_OFFLINE=1 uv sync --frozen          # exit 0 (installed from local uv cache)
uv lock --check --offline              # exit 0
UV_OFFLINE=1 uv run --frozen pytest -q # 559 passed in 205.23s, exit 0
uv run --offline --frozen black --check .  # 43 files would be left unchanged
npx --yes prettier@3.3.3 --check <same files, committed ticket versions>  # pass
```

No network was required (offline uv from cache). The suite does not depend on
untracked files.

## Real-CLI smoke (temp `HOME`)

Binary: `/Users/maxilr/Documents/GitHub/respec/.venv/bin/respec`, with `HOME`
and `XDG_CONFIG_HOME` set to a scratch dir. Seeded
`~/.claude/skills/preexisting/SKILL.md` and a local `./src/my-skill`.

1. `respec profile new work --target claude-code` -> exit 0,
   `Created profile 'work' at .../.respec/profiles/work`
2. `respec add ./src/my-skill -p work` -> exit 0,
   `Added 'my-skill' to profile 'work'`
3. `respec use work </dev/null` -> exit 0, backed up the claude-code folder,
   `Switched to profile 'work': installed 3 skills (7 links)`, warning that
   `preexisting` is a folder respec did not place (run `respec adopt`).
   `~/.claude/skills` then held symlinks `my-skill`, `profile-maker`, `respec`
   plus the untouched `preexisting` folder.
4. `respec status --json` -> exit 0, `active_profile: "work"`, `targets:
["claude-code"]`; claude-code folder lists `my-skill` (origin profile),
   `profile-maker` and `respec` (origin shipped); shipped skills also in
   `agents` and `oh-my-pi` folders; `unresolved` lists `preexisting`.
5. `respec restore </dev/null` -> exit 0, `Removed 3 skills (7 links) placed by
respec`, restored claude-code from backup, agents and oh-my-pi
   `from nothing (folder did not exist)`, `no profile is active`.
   Afterwards `~/.claude/skills` holds only `preexisting` with original
   content, `~/.agents` and `~/.omp` are gone, and `status --json` shows
   `active_profile: null`.

Note: an earlier attempt `respec use work --unknown add` exited 1 with the
documented refusal (`'--unknown add' adds to the profile active now, and no
profile is active`). That was an operator choice, not a defect; the smoke was
rerun without the flag as above.

## Skipped checks

- No linter/typechecker is configured in the project (no ruff/mypy in
  `pyproject.toml`); none run.
- TUI not exercised interactively (covered by the TUI tests in the suite).
- `respec add owner/repo`, `update`, `profile install` (network git sources) not
  exercised in the smoke.
