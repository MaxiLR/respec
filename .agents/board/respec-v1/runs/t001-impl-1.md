# t001 implementation run 1

- Ticket: 001, package skeleton, target registry, profile new/list/show
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t001`
- Branch: `codex/respec-v1-t001`, base `3e582ec`, head `9463b19`
- Status: DONE (committed locally, not pushed)

## Changes

- `pyproject.toml`, `uv.lock`: uv-managed package `respec` (hatchling, src layout).
  Runtime dependencies are `typer` and `pyyaml`. The dev group has `pytest` and
  `black`. The entry point is `respec = "respec.cli:app"`.
- `src/respec/targets.yaml` and `targets.py`: data-file registry shaped after
  skills.sh `agents.ts` (`name`, `display_name`, `global_skills_dir`). It holds
  `claude-code` (`~/.claude/skills`), `agents` (`~/.agents/skills`) and
  `oh-my-pi` (`~/.omp/agent/skills`). `Target.skills_dir(home)` resolves the
  `~/` prefix against the given home.
- `src/respec/paths.py`: `respec_home()` uses `RESPEC_HOME`, falling back to
  `<user home>/.respec`. `user_home()` uses the `--home` option, then
  `RESPEC_USER_HOME`, then `Path.home()`.
- `src/respec/profiles.py`: profile model plus the `profile.yaml` loader and
  validator. Top-level keys are `targets` (required, non-empty, known, no
  repeats) and `skills` (optional mapping of name to
  `{enabled: bool, source?: {repo (required), path?, ref?, commit?}}`). Unknown
  keys are rejected at every level. All problems are collected and reported
  with the file path and the field path. Profile and skill names must match
  `^[A-Za-z0-9][A-Za-z0-9._-]*$`, which blocks path traversal.
- `src/respec/cli.py`: global `--home` (env `RESPEC_USER_HOME`),
  `profile new <name> -t/--target ... [--json]`, `profile list [--json]` and
  `profile show <name> [--json]`. Errors print `error: ...` on stderr and exit
  with code 1, without a traceback.
- `tests/conftest.py`: autouse `isolated_homes` fixture (the orchestrator's
  isolation request). It points `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` at
  per-test temp dirs. It fails the test if `tmp_path` sits under the real home.
  It also wraps `respec.paths.respec_home` and `respec.paths.user_home` so that
  any resolution under the real home calls `pytest.fail`. The real home comes
  from `pwd`, not `$HOME`. `pytest.fail` raises a BaseException, so CliRunner
  does not swallow it. There is also a `run` fixture that runs the CLI
  in-process.
- `README.md`: Development section (commands and the home overrides).

Note for later tickets: code must reach paths through the module attributes
`paths.respec_home()` and `paths.user_home()`, or the CLI `Homes` context
object. A `from respec.paths import ...` binding would bypass the guard.

## Acceptance criteria to evidence

| Criterion                                                                                        | Evidence                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Package `respec`, Typer CLI, entry point `respec`, Black, pytest, uv                             | `uv sync`. `uv run respec --help` works through the console script. `uv run black --check .` reports 11 files unchanged. `uv run pytest` passes 37 tests. `uv build --wheel` includes `respec/targets.yaml`.                                                                                                                                                                                 |
| Target registry data file with the three targets, agents.ts shape                                | `src/respec/targets.yaml`. `test_show_json_includes_resolved_target_dirs_and_skills` asserts the name, display name and resolved dir for all three.                                                                                                                                                                                                                                          |
| `RESPEC_HOME` relocates `~/.respec`; target dirs resolve against an overridable home             | `test_new_creates_profile_yaml_and_skills_folder` (under `RESPEC_HOME`) and `test_new_without_respec_home_uses_dot_respec_in_home`. `test_home_option_relocates_target_dirs` covers `--home`. `test_user_home_env_relocates_target_dirs` covers the env var. `test_isolation.py` covers the guard: 3 tests, including that it trips on the real home.                                        |
| `profile new` creates `profile.yaml` and `skills/`; rejects unknown targets and duplicate names  | `tests/test_profile_new.py` has 7 tests. They cover the files and YAML content, an unknown target (lists the known ones, creates no folder), a duplicate (existing file unchanged), a missing `--target`, a path-like name, and a repeated target.                                                                                                                                           |
| `profile list` / `profile show`, human and `--json`                                              | `tests/test_profile_list_show.py` has 10 tests: empty list in both formats, ordered JSON summaries, invalid profiles flagged in both formats, full show JSON, human show output, and an unknown profile.                                                                                                                                                                                     |
| Schema loader validates targets and skills (`enabled`, optional `source`) with actionable errors | `tests/test_profile_schema.py` has 17 tests. They cover 14 invalid cases (each asserting the file path, the field-specific message and no traceback), aggregated problems, a missing `profile.yaml`, and the optional `skills` and source fields. A mutation check (disabling the `enabled` type check and the top-level unknown-key check) made 3 tests fail. The source was then restored. |

Criteria met: 6/6.

## TDD trail

- Isolation tests were written first. They were red (`respec.paths` absent), then green.
- `profile new` tests were red (`respec.cli` absent), then green.
- list/show tests were red: 10 failed with exit 2 (no such command), then green.
- The schema tests passed on first run because the validator was built with
  `new`. A mutation check confirmed they detect regressions.

## Verification (fresh, at head 9463b19)

- `uv run pytest -q`: 37 passed in 0.24s
- `uv run black --check .`: 11 files would be left unchanged
- `npx prettier@3 --check README.md`: clean
- Manual end-to-end run of the real entry point with `RESPEC_HOME` and
  `RESPEC_USER_HOME` set to scratch dirs:
  - `profile new`, a duplicate and an unknown target: the last two exit 1 with
    clear errors.
  - A missing `--target` gives a usage error with exit 2.
  - `list` and `list --json`, `show`, and `--home <dir> profile show --json`
    all behave as expected.
  - Only the scratch dirs were written.
- The repo has no pre-commit config.

## Decisions and concerns

- The env var name for the user home was chosen here: `RESPEC_USER_HOME`
  (alongside the `--home` option). The spec did not name it.
- A profile needs at least one target, in `new` and in the schema. An
  "empty/off" profile is therefore impossible; `restore` covers that need.
- Unknown keys are rejected strictly. Later tickets that add `layers` or
  `system` must extend `TOP_LEVEL_KEYS` in `profiles.py`.
- `source` requires `repo`. Ticket 007 may want local-path sources or other
  shapes and would need to adjust the schema.
- `profile new --json` was added for consistency, beyond the read-command
  requirement.
- `respec` with no args prints help for now. Ticket 010 turns that into the TUI.
