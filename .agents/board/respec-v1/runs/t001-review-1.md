# t001 fresh review 1

- Reviewer: fresh independent context. I did not implement this work.
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t001`
- Diff: `3e582ec..9463b19` (one commit, 15 files)
- Inputs: ticket 001, spec `respec-v1` (rev 2), implementation claims
  `t001-impl-1.md`. There is no `CONTEXT.md`, no decision records and no
  `AGENTS.md` in the worktree.

## Verdicts

- spec-compliance: PASS (with one should-fix inconsistency, F1)
- code-quality: PASS
- tests-rerun: PASS
- blocking: 0

## Gates rerun (fresh, at 9463b19)

| Gate                               | Result                              |
| ---------------------------------- | ----------------------------------- |
| `uv lock --check`                  | lock consistent, 25 packages        |
| `uv sync --frozen`                 | ok                                  |
| `uv run pytest -q`                 | 37 passed                           |
| `uv run black --check .`           | 11 files unchanged                  |
| `npx prettier@3 --check README.md` | clean                               |
| Manual CLI run in scratch homes    | reproduced F1, otherwise as claimed |

## Acceptance criteria

| Criterion                                                     | Verdict | Notes                                                                                                                                              |
| ------------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Package, Typer, entry point `respec`, Black, pytest, uv       | Met     | `pyproject.toml` `[project.scripts]`. Gates above.                                                                                                 |
| Target registry data file, three targets, agents.ts shape     | Met     | `src/respec/targets.yaml` uses name, display_name and global_skills_dir. Directories match spec decision 14. It is bundled as package data.        |
| `RESPEC_HOME`; target dirs against overridable home           | Met     | Env and option both relocate target dirs (tested). See F1 for an inconsistency between the two.                                                    |
| `profile new` creates files; rejects unknown/duplicate        | Met     | `tests/test_profile_new.py` asserts on the filesystem and the error text. Duplicates leave the existing file unchanged. Path traversal is blocked. |
| `profile list` / `show`, human and `--json`                   | Met     | `tests/test_profile_list_show.py` asserts parsed JSON with independent expected values.                                                            |
| Schema loader validates targets and skills, actionable errors | Met     | `tests/test_profile_schema.py` has parametrized invalid cases. Each asserts the field path and the file path. Problems are aggregated.             |

The tests check observable behavior: files created, parsed JSON and stderr
text. They do not assert on source text or restate the implementation.

## Requested investigations

### (a) `RESPEC_USER_HOME` and `--home`: invented public surface?

The spec does not name either one. Its proposed defaults say only "target
folders resolve against an overridable home so tests run in temporary
directories". The ticket AC asks for "an overridable home (env or option)".
So some override is required, and the implementer had to pick names. The
choice fits the ticket, and the implementation run discloses it under
"Decisions and concerns". It is still new public surface that the engineer
should confirm. The `respec` skill (ticket 012-ish) and the README will
document it. A simpler alternative would be to resolve against `HOME` alone
(`Path.home()`), which would need no new name. Not blocking. Flag it to the
engineer for an explicit naming decision.

### (b) Is the autouse isolation fixture sufficient?

The fixture is stronger than "only guards `paths.*`". In `tests/conftest.py`
it does the following:

1. It sets `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` to per-test temp dirs.
   `Path.home()`, `os.path.expanduser("~")` and child processes (for example
   `git`, which reads `~/.gitconfig`) therefore all resolve to the temp home,
   even in code that bypasses `paths`.
2. It wraps `paths.respec_home` and `paths.user_home` to fail any resolution
   under the real home, which it reads from `pwd`.
3. It fails if `tmp_path` itself is under the real home.

Under pytest-xdist, each test gets its own `tmp_path` and its own
monkeypatch, so the setup is parallel-safe. Remaining holes, none of them
blocking now:

- B1 (`tests/conftest.py`, the fixture as a whole): import-time capture.
  Tests import `respec` modules at collection time, before the fixture runs.
  A later module that computes a path at import, such as
  `STATE = Path.home() / ".respec" / "state.json"` or a `@cache` around
  `paths.respec_home()`, would capture the real home. The guard would never
  see it. Impact: later tickets could write `state.json`, backups or links
  into the real `~/.respec`, `~/.claude/skills` and similar folders while
  every test passes. The note in the implementation run covers only
  `from respec.paths import ...` bindings, and those are still safe because
  of the env vars. Recommendation: document "no import-time or cached home
  paths" for later tickets, or add a session-level check that the real
  target folders and `~/.respec` are unchanged (mtime or listing snapshot)
  after the run.
- B2: the guard checks resolution, not writes. Code that builds absolute
  paths some other way (`pwd`, `~user`, hard-coded `/Users/...`) is not
  caught. This is low risk.
- B3: tests that pass `env={"HOME": None}` or similar to `CliRunner` remove
  layer 1 for that call. Only `RESPEC_HOME: None` is used today, and that is
  safe.

### (c) `profile.yaml` schema: strict keys and `source.repo` required

There is no contradiction with the spec today:

- Decision 8 lists the origin record as repo, path, ref and resolved commit.
  `SOURCE_KEYS` matches that, and requiring `repo` matches "records its
  origin (repo…)".
- `respec add <path>` (local) items have no source per decision 8 ("Items
  without a source never change"), so they do not need `repo`.
- Decision 10 layers and the built-in layer toggle will need new top-level
  keys. With strict rejection, ticket 009 must extend `TOP_LEVEL_KEYS`. The
  implementation run discloses this. It is a forward constraint, not a
  current contradiction.
- Requiring at least one target is consistent with decision 2.

### (d) uv.lock and pyproject

`uv lock --check` passes. Runtime dependencies are `typer>=0.12` and
`pyyaml>=6.0`. Dev dependencies use `[dependency-groups]` (`black`,
`pytest`). The build backend is hatchling with a src layout, and
`requires-python>=3.11`. All of this is appropriate. The lock pulls in
`pydantic`/`pydantic-core` through typer 0.29, which is a transitive
dependency and acceptable. Textual is not added yet, which is correct
because the TUI is excluded from this ticket.

## Findings

### F1 (should-fix, not blocking): `--home` and `RESPEC_USER_HOME` disagree on where `~/.respec` lives

- Location: `src/respec/cli.py` `main()` calls `paths.respec_home()` without
  the `--home` value. `src/respec/paths.py` `respec_home()` falls back to
  `user_home()`, which reads only the env var.
- Scenario (reproduced in scratch homes, with `RESPEC_HOME` unset):
  - `HOME=h1 RESPEC_USER_HOME=h2 respec profile new a -t agents` creates
    `h2/.respec/profiles/a`.
  - `HOME=h1 respec --home h2 profile new b -t agents` creates
    `h1/.respec/profiles/b`.
- Impact: the same setting gives a different data location depending on
  whether it is passed as an env var or as an option. Suppose someone
  experiments with `respec --home /tmp/x` and expects a sandbox. The target
  folders go to `/tmp/x`, but profiles, and later `state.json` and backups,
  go to the real `~/.respec`. Later, `use` and `restore` would record real
  state for a fake home. No test covers `--home` without `RESPEC_HOME`. The
  suite always sets `RESPEC_HOME`, which hides the problem.
- Fix: in `main()`, pass the resolved user home into the default, for
  example `paths.respec_home(default_base=user_home)`. Alternatively,
  document that `--home` relocates target folders only and make the env var
  behave the same way. Add one test for whichever behavior is chosen.

### F2 (minor): unreadable `profile.yaml` gives a traceback

- Location: `src/respec/profiles.py` `load_profile`. `file.read_text("utf-8")`
  is outside the `try`, and only `yaml.YAMLError` is caught.
- Scenario: a `profile.yaml` with invalid UTF-8 or no read permission raises
  `UnicodeDecodeError` or `PermissionError`. `profile show` then exits with a
  traceback (`pretty_exceptions_enable=False`). `profile list` aborts
  entirely instead of flagging one profile.
- Impact: this conflicts with the AC promise that invalid files produce
  actionable errors. It is an edge case. Wrap `OSError` and
  `UnicodeDecodeError` into `ProfileError`.

### F3 (minor): `profile new` is not atomic

- Location: `profiles.create_profile` runs `mkdir`, then `write_text`.
- Scenario: if the write fails, a folder without `profile.yaml` remains, and
  a retry reports "already exists". Low impact. Writing a temp file and then
  renaming it would fix this.

## Scope

The diff stays within ticket 001. Activation, layers, sources and TUI are
absent. `profile new --json` is a small, disclosed addition that matches
"every read command supports `--json`". `respec` with no arguments prints
help, and ticket 010 changes that.
