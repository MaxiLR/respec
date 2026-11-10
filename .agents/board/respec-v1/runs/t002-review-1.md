# t002 fresh review 1

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t002`, HEAD `134a0e6`
- Diff: `a8ec9de..134a0e6` (cli.py, state.py, switch.py, tests/test_use_status.py, README.md)
- Inputs: ticket 002, spec revision 2, implementation claims `t002-impl-1.md`. No AGENTS.md, CONTEXT.md or decision records in the worktree.

## Verdicts

- spec-compliance: FAIL (one blocking finding breaks the A to B isolation guarantee after a mid-switch failure)
- code-quality: FAIL (same finding: install records are kept only in memory until the end of the switch)
- tests-rerun: PASS

## Gates rerun

| Gate                             | Result             |
| -------------------------------- | ------------------ |
| `uv run pytest -q`               | 53 passed          |
| `uv run black --check .`         | 14 files unchanged |
| `npx prettier --check README.md` | clean              |
| Worktree clean, HEAD `134a0e6`   | yes                |

## Blocking findings

### B1. Install-phase failure leaves unrecorded links. The next switch then leaves the previous profile's items in place.

- Location: `src/respec/switch.py`, `use()` install loop (records are appended to `state.installed` in memory and saved once, after the loop) and `_install()` (`except OSError` also catches `FileExistsError`, then `copytree` onto an existing path).
- Failing scenario (reproduced with the real entry point in a scratch home): `~/.claude/skills` is a symlink to `~/.agents/skills`. This setup is common, and the spec notes that harnesses share folders. Profile `a` targets `claude-code` and `agents` with skill `tdd`. Preflight passes because neither destination exists yet. `respec use a` symlinks `tdd` through `claude-code`. The `agents` install then hits `FileExistsError`, falls back to `copytree`, and crashes with a raw Python traceback (the CLI catches only `RespecError`). The resulting `state.json` has `active_profile: null` and `installed: []`, but `~/.agents/skills/tdd` exists as a symlink into profile `a`. `respec use b` (target `oh-my-pi`) then reports success while `~/.agents/skills/tdd` (profile `a`) is still present. Any later `use a` refuses with "not managed by respec".
- Impact: this violates the ticket's switch criterion and the A(claude-code, agents) to B(oh-my-pi) scenario. respec loses track of paths it created, so it can never remove them, which defeats isolation. A failure from any other cause partway through the install loop has the same effect: copy fallback hitting a permission error, a full disk, or a missing source. state.json and the targets end up inconsistent, contrary to review focus (a). No user data is deleted.
- Suggested direction: persist each `Installed` record as soon as its path is created, or record it before creating the path. In preflight, detect target folders that resolve to the same real directory, either deduplicating them or refusing with a `RespecError`. Do not fall back to a copy on `FileExistsError`. Ticket 003's journal adds resume and rollback but should not be required for state.json to stay truthful.

## Non-blocking observations

- N1. `_remove` (`switch.py`): `mode == "copy"` entries are deleted with `rmtree` without checking the contents. If the user has edited a copied skill, or replaced it with their own folder at the same path, those changes are lost on the next switch. This stays within "removal only touches recorded paths", but ticket 004 or 005 may want a content check or a backup here. A user-replaced symlink at a recorded path is also unlinked. Only the link is lost, not its target's data.
- N2. A failure during takeover (`copytree` of an unreadable file) leaves a partial backup run folder and no state change. Safe, but the partial folder stays behind.
- N3. Target ordering in `status` falls back to `len(order)` for unknown targets. That is fine.

## Review focus answers

- (a) Switching safety: preflight refuses unrecorded entries at install paths and changes nothing (verified by test and code). Removal touches only recorded paths. Symlinks are unlinked and never followed. Copies are guarded against deleting inside the profiles root. Profile folders survive (verified by test). Mid-switch consistency fails for the install phase (B1). A removal-phase failure keeps the old records, which is safe because missing paths are skipped later.
- (b) Install mode per installed path: acceptable. The spec's proposed default is "symlink with copy fallback when a symlink cannot be created", and the per-target default appears only as a risk mitigation. Each path needs its own mode record for removal anyway. No conflict with the spec.
- (c) Refusing an untracked entry at an install path before ticket 004: consistent with decision 5 (adopt is ticket 004) and the safest behavior. Nothing is overwritten, no backup is written and no state is saved (`test_use_refuses_to_overwrite_unrecorded_entry`). Untracked entries that do not collide are left alone (`test_switch_only_removes_recorded_paths_and_keeps_profile_folders`).
- (d) Isolation: every test in `tests/test_use_status.py` uses the autouse `isolated_homes` fixture through `dirs`, `run` and `isolated_homes`. No module computes a home path at import time. `paths`, `targets.skills_dir(home)`, `profiles_dir(respec_home)` and `backups_dir(respec_home)` all take homes at call time, and `conftest.REAL_HOME` is used only by the guard. The guard wrappers on `paths` cover the CLI path.

## Acceptance evidence check

- Symlinks plus copy fallback, records in state: verified by tests and code. The fallback is too broad (B1).
- First-takeover backup, install changes nothing: verified, including same-second collision handling.
- Switch removes recorded paths everywhere and installs into new targets only: verified on the happy path. Fails after an install-phase error (B1).
- Disabled skills never linked: verified.
- Removal only touches recorded paths; profile folders kept: verified.
- `status` and `--json`: verified. Unknown-entry listing is deferred to ticket 004 as the ticket states.
- Tests check filesystem state and state.json against independent expectations. No source-text or mirror tests.
