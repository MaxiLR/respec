# Integration check: a8ec9de (ticket 001)

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- `git rev-parse HEAD`: `a8ec9dedcd47c7bc5ae77eb6f168f292da910495` (matches expected)
- Range: `3e582ec..a8ec9de` (9463b19 ticket commit + a8ec9de merge); 15 files, +1543
- Working tree: only the expected orchestrator files under `.agents/board/respec-v1/` are dirty (untouched)
- AGENTS.md: none in the repository; global CLAUDE.md applied

## Gates

| Command                                       | Result                                    |
| --------------------------------------------- | ----------------------------------------- |
| `uv sync --frozen`                            | OK (rc 0)                                 |
| `uv run pytest -q -rs`                        | 37 passed in 2.13s, 0 skipped, 0 xfail    |
| `uv run black --check .`                      | 11 files would be left unchanged          |
| `npx prettier --check $(git ls-files '*.md')` | All matched files use Prettier code style |

Result: all gates PASS.

## Cross-ticket review

Only ticket 001 is integrated, so there are no earlier contracts to conflict with. No duplicated
helpers were found. Vocabulary matches the spec: profile, target, `profile.yaml`, `skills/`,
source (`repo`, `path`, `ref`, `commit`), `enabled`, `RESPEC_HOME`. The three registry
targets and their folders match decision 14.

Findings (none block the gates):

1. **`--home` and `RESPEC_USER_HOME` behave differently (medium).** `paths.respec_home()`
   defaults to `user_home() / ".respec"` with no argument. That reads the `RESPEC_USER_HOME`
   env var but ignores the `--home` CLI option, because `cli.main` calls
   `paths.respec_home()` without passing `home`. Probe: with
   `HOME=$S/realhome respec --home $S/fake profile new p -t agents`, the profile was written
   to `$S/realhome/.respec/profiles/p`. Setting the env var instead moves both homes. The two
   overrides are documented as equivalent, so later tickets that use `--home` for isolation
   (`use`, backups, `state.json`) could write respec data under the real home. The tests
   only use the env vars, so they do not catch this. Decide which contract is intended
   before ticket `use` or `restore` depends on it.
2. **Duplicate skill keys pass silently (low).** `yaml.safe_load` keeps the last of two
   duplicate `skills:` keys. A file with `a: {enabled: true}` followed by
   `a: {enabled: false}` loads as a single disabled `a` and reports no error. The loader is
   supposed to give actionable errors for invalid files, so this one slips through.
3. **Unused parameter (low).** The `override` parameter of `paths.respec_home(override)`
   is never passed by any caller in `src/` or `tests/`.
4. **Vocabulary note (info).** The spec says "item" for enable/disable, sources and layers
   (decisions 8–10). The code and schema say "skill" (`skills:`, `SkillEntry`). That fits
   v1, which covers skills only. Later layer and global tickets should pick one name for
   CLI arguments and `--json` keys (for example `respec enable <item>`).

No other cross-ticket issues: `--json` shapes (`profile new`, `list`, `show`) are
consistent, and the error path goes through `RespecError` and `_fail` with exit code 1.
