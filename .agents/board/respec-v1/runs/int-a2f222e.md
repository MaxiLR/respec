# Integration check: a2f222e (tickets 001, 002)

- Checkout: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- `git rev-parse HEAD` → `a2f222e109236e4e480bde4a6ba6ea6cdab2f633` (matches expected)
- Working tree: only expected orchestrator files dirty (`tickets/001.md`, `tickets/002.md`, `orchestration.md`, `runs/`)
- Change range `a8ec9de..a2f222e`: README.md, src/respec/cli.py, src/respec/state.py (new), src/respec/switch.py (new), tests/test_use_status.py (new); +877/-1
- No AGENTS.md in the repository.

## Gates

| Command                                       | Result                                    |
| --------------------------------------------- | ----------------------------------------- |
| `uv sync --frozen`                            | exit 0, "Audited 24 packages"             |
| `uv run pytest -q`                            | 56 passed in 1.27s, 0 skipped, 0 xfail    |
| `uv run black --check .`                      | 14 files would be left unchanged          |
| `npx prettier --check $(git ls-files '*.md')` | All matched files use Prettier code style |

## Cross-ticket findings

1. **Medium: `--home` (001) and target-keyed ownership (002) combine to skip the first-takeover backup.**
   `cli.main` relocates only the user home with `--home`; `paths.respec_home()` is called without it
   and still resolves to `~/.respec` (or `$RESPEC_USER_HOME/.respec`). `state.owned` is keyed by target
   name, and `_take_over` checks only `target not in state.owned`, never whether the recorded
   `skills_dir` equals the folder now resolved. Reproduced in scratch (fake `HOME`):
   - `respec --home h1 use p` → takes over `h1/.agents/skills`; state in `$HOME/.respec`.
   - `mkdir h2/.agents/skills/preexisting; respec --home h2 use p` → installs `x` into
     `h2/.agents/skills` next to `preexisting`, **no backup made** of h2's folder (violates
     spec decision 6 / ticket 002 AC2).
   - `respec --home h2 status` reports `agents  .../h1/.agents/skills` with item `x`, while `x` actually
     lives in h2 (stale `skills_dir`).
     Setting `RESPEC_USER_HOME` moves both homes together, so the env path is safe; the `--home` flag
     is the hazard (and could point real `~/.respec` state at a sandbox home). Suggested owner:
     decide whether `--home` should also move the default respec home, or have takeover compare
     `Owned.skills_dir` to the resolved folder.
2. **Low: targets sharing one real folder.** `_preflight` dedupes installs by `folder.resolve()`,
   but `_take_over` backs up each target separately (duplicate backup of the same real dir), and
   `status` lists the items only under the first target; the second shows "(no managed items)"
   though the folder holds them. Restore (005) should account for two backups of one real folder.
3. **Low (note for 005):** a later takeover of a target whose real folder is already owned via
   another target copies respec's own symlinks into the backup (`copytree(symlinks=True)`);
   restoring that backup would re-create managed links outside `state.json`.

## Contracts, duplication, dead code, vocabulary

- 002 consumes 001 correctly: `profiles.load_profile`, `profiles.SKILLS_DIR`, `profiles.profiles_dir`,
  `targets.registry()[t].skills_dir(user_home)`, `RespecError`. No re-implementation of profile
  parsing or target resolution.
- Path helpers are spread per module (`profiles.profiles_dir`, `state.state_path`,
  `switch.backups_dir`) rather than in `paths.py`; consistent pattern, not duplication. No dead code found.
- Vocabulary matches the spec: profile, target, take over, backups/<timestamp>/<target>, state.json,
  managed items, `--json`. Nit: CLI prints "installed 1 items" / "Removed 1 items" (pluralisation).
- Interrupted-switch journal (spec risk) is not present; ticket 002 explicitly defers it to 003
  (current behaviour: state saved after each step, active_profile set to null on failure).

No code changed; no tickets updated; nothing committed or pushed.
