# fix-2 implementation run 1

- Status: DONE
- Branch: `codex/respec-v1-fix-2` (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-2`)
- Base: `eeca3cb13e94608ea86451782c87a96f32810adb`
- Head: `79ee829` "Remove the --home CLI option"

## Changes

- `src/respec/cli.py`: the root callback `main` no longer takes `--home`; it builds
  `Homes` from `paths.respec_home()` and `paths.user_home()`. This is the only edit
  in cli.py (lines 37-51 before), so it should not conflict with tickets 005/007.
- `src/respec/paths.py`: removed the `override` parameter from `user_home()` and
  `respec_home()`. Nothing else used it. Updated the module docstring to call the
  env vars advanced/testing overrides, and to say the data default is
  `<user home>/.respec`.
- `src/respec/targets.yaml`: the header comment no longer mentions `respec --home`.
- `README.md`: the paragraph about overrides now drops `--home` and documents
  `RESPEC_USER_HOME` and `RESPEC_HOME` as advanced/testing overrides.
- Tests: see below.

## Criterion -> evidence

| #   | Criterion                                                                     | Evidence                                                                                                                                                                                                                                                                                                                                                                                                           |
| --- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `--home` gone from root, subcommands, TUI; Typer "No such option"             | `tests/test_profile_list_show.py::test_home_option_is_rejected` (parametrized: root `--home x profile show work`, `profile show work --home x`, `tui --home x`) asserts exit code 2 and `No such option: --home`. It was red before the fix on the root case. Manual check: `uv run respec --home x` prints `No such option: --home`.                                                                              |
| 2   | `RESPEC_HOME` and `RESPEC_USER_HOME` unchanged                                | `test_user_home_env_relocates_target_dirs` (now also asserts the claude-code dir, which the removed `--home` test covered). `test_new_without_respec_home_uses_dot_respec_in_home` is unchanged. New `test_new_without_respec_home_follows_relocated_user_home`: with `RESPEC_HOME` unset and `RESPEC_USER_HOME` set elsewhere, data lands at `<that>/.respec`. `tests/test_isolation.py` is unchanged and passes. |
| 3   | Dead code removed                                                             | The `override` parameters on `paths.user_home` and `paths.respec_home` were removed. Grep shows no remaining callers that pass arguments.                                                                                                                                                                                                                                                                          |
| 4   | README and docstrings drop `--home`; env vars documented as advanced/testing  | `grep -rn -- "--home" src README.md` returns nothing. README and the `paths.py` docstring call the env vars advanced/testing overrides.                                                                                                                                                                                                                                                                            |
| 5   | Rejection test; former `--home` tests moved to the env vars, no coverage lost | `test_home_option_relocates_target_dirs` was replaced by the rejection test. Its claude-code `skills_dir` assertion moved into the `RESPEC_USER_HOME` env test.                                                                                                                                                                                                                                                    |

## Verification (fresh, in worktree)

- `uv sync --frozen`: Audited 27 packages
- `uv run pytest -q`: 135 passed in 9.85s
- `uv run black --check .`: 23 files would be left unchanged
- `npx prettier --check README.md`: All matched files use Prettier code style
- TDD red step: `test_home_option_is_rejected[args0]` failed before the fix. The
  root accepted `--home x`, and the isolation guard then caught the resolved path.
  The subcommand and `tui` cases already rejected it, and they stay as regression
  guards.

## Concerns

None. The `envvar=RESPEC_USER_HOME` binding on the old option was redundant with
`paths.user_home()`, which reads the env var itself. Behavior is unchanged.
