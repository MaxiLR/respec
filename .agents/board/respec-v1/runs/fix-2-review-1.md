# fix-2 review run 1

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-2`
- Diff: `eeca3cb13e94608ea86451782c87a96f32810adb..79ee8291590b6b1b78e997a12a9fd6d9fd77b279`
  (one commit, `79ee829` "Remove the --home CLI option")
- Verdicts: spec-compliance PASS, code-quality PASS
- Blocking findings: 0

## Acceptance criteria

| #   | Criterion                                            | Result | Evidence                                                                                                                                                                                                                                                                                                                                                                                           |
| --- | ---------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `--home` gone from root, subcommands, TUI            | PASS   | `main(ctx)` in `src/respec/cli.py` no longer declares the option, and no subcommand declares one. Running `uv run respec --home x` prints Typer's `No such option: --home`. The parametrized `test_home_option_is_rejected` covers the root, `profile show`, and `tui` and asserts exit code 2.                                                                                                    |
| 2   | Env vars unchanged                                   | PASS   | See the `paths.py` section.                                                                                                                                                                                                                                                                                                                                                                        |
| 3   | Dead code removed                                    | PASS   | The `override` parameters on `paths.user_home` and `paths.respec_home` are gone. Grep finds no callers that pass arguments. `Annotated`, `Optional` and `Path` are still imported in `cli.py`, but other code there uses them, so they are not dead.                                                                                                                                               |
| 4   | README/docstrings drop `--home`; env vars documented | PASS   | `grep -rn -e --home src README.md` finds nothing. The README and the `paths.py` module docstring call the env vars "advanced/testing overrides".                                                                                                                                                                                                                                                   |
| 5   | Rejection test; coverage preserved                   | PASS   | The removed `test_home_option_relocates_target_dirs` asserted the claude-code `skills_dir`. That assertion moved into `test_user_home_env_relocates_target_dirs`. The new `test_new_without_respec_home_follows_relocated_user_home` checks that with `RESPEC_HOME` unset, data lands at `<RESPEC_USER_HOME>/.respec`. Both tests use independent expectations, not mirrors of the implementation. |

## Specific investigations

### `src/respec/targets.yaml`

The change is one line in the YAML header comment. It replaced "with RESPEC_USER_HOME or `respec --home`" with "with the RESPEC_USER_HOME environment variable". No target entry (name, display name, skills dir) changed, so install paths and behavior are unchanged. It is in scope under criterion 4 because it removes a stale `--home` mention.

### `src/respec/paths.py` env-var semantics

I compared the base and head versions. The only removed branch is `if override: return _absolute(override)`. The env lookup, the `_absolute` (expanduser + resolve) normalization, the empty-string fallthrough and the `Path.home().resolve()` fallback are byte-identical. `respec_home()` still defaults to `user_home() / ".respec"`, as it did at base.

At base the CLI also called `paths.respec_home()` with no override, so `--home` never moved the data directory. The env-only behavior is therefore unchanged. The CLI option's `envvar=RESPEC_USER_HOME` binding only fed the same value back into `user_home(override)`, so removing it changes nothing for env users. One edge case: Typer would have passed an empty `RESPEC_USER_HOME=""` as `None` or an empty path, and either way it fell through to the same env check, which treats empty as unset. Behavior is the same.

## Non-blocking observations

- `src/respec/paths.py`, the `respec_home()` function docstring: it still says "`~/.respec` unless relocated", while the module docstring now says `<user home>/.respec`. These do not contradict each other, since `~` means the user home, but they could be worded the same. This is cosmetic and causes no behavior impact.
- Running `uvx ruff check` reports pre-existing findings in `cli.py` (UP045, B006, RUF100). None are on changed lines, and the project does not configure or gate on ruff. Not attributable to this fix.

## Gates rerun (fresh, in worktree)

- `uv run pytest -q`: 135 passed in 10.75s
- `uv run black --check .`: 23 files would be left unchanged
- `npx prettier --check README.md`: All matched files use Prettier code style
- Manual: `RESPEC_HOME=/tmp/x RESPEC_USER_HOME=/tmp/y uv run respec --home x`
  prints `No such option: --home (Possible options: --help)`

## Scope

There are six files: README, `cli.py`, `paths.py`, the `targets.yaml` comment, and two test files. All are within the fix-2 acceptance scope, and there are no unrelated changes or formatting churn.
