# Ticket 007 review 1 (fresh, independent)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t007`
- Diff reviewed: `51360971..c2f268d2` (single commit `c2f268d`)
- Inputs: ticket 007, spec (decision 8, testing seams), impl runs 1 and 2. No
  `AGENTS.md` or `CONTEXT.md` exists in the worktree.

## Verdicts

- spec-compliance: PASS (all three acceptance criteria hold; see evidence)
- code-quality: FAIL (one blocking security finding)
- tests-rerun: PASS

## Gates rerun (fresh, at `c2f268d`, clean tree)

- `uv run pytest -q`: 113 passed
- `uv run black --check .`: 20 files unchanged
- `npx prettier@3 --check README.md`: clean

## Blocking findings

### B1. Command execution through git option injection in `source.repo` (and `ref`)

- Location: `src/respec/sources.py` `_git` callers: `remote_commit` (line 110,
  `_git("ls-remote", url, wanted)`) and `checkout` (lines 135/138,
  `_git("fetch", ..., url, ref or "HEAD")`); `repo_url` (line 60) returns any
  non-shorthand `repo` unchanged; `profiles._parse_source` only checks that
  `repo`/`ref`/`path` are non-empty strings.
- Failing scenario (reproduced through the real entry point with scratch homes
  and isolated git config): a repository contains `profile.yaml` with
  `skills.a.source.repo: "--upload-pack=touch $S/PWNED_INSTALL;false"`.
  `respec profile install evil/pack` accepts it (owned locally, items keep
  their sources, as the ticket requires), then `respec update --check -p pack`
  runs `git ls-remote --upload-pack=...` and the file `PWNED_INSTALL` is
  created. The same happens with a hand-edited `profile.yaml` (`PWNED_REPO`).
  For `ref`: `git fetch` interleaves options after positionals, so
  `git fetch -q --depth 1 <url> "--upload-pack=..."` executes the command
  (`PWNED_FETCH` reproduced directly); this path is reachable from
  `respec add <spec> --ref=--upload-pack=...` and
  `respec profile install <spec> --ref=...` (ls-remote is not affected for
  `ref` because it stops option parsing at the URL).
- Impact: installing a third-party modpack and then running the read-only
  `update --check` executes arbitrary commands as the user. Modpack install
  from someone else's repository is exactly the trust boundary decision 8
  introduces, and agents are told to drive the CLI.
- Suggested fix: reject `repo`, `ref` and `path` values starting with `-`
  (in `_parse_source` and `parse_spec`/`--ref`), and pass `--end-of-options`
  (or `--`) before the URL/ref in `ls-remote` and `fetch`. Add a regression
  test that an option-like repo/ref is refused and runs nothing.

## Non-blocking findings

- N1 `source.path` traversal: `_replace` (line 409) and `install_profile`
  (line 450) join `tree / source.path` without the `..`/absolute check that
  `parse_spec` applies to CLI input. A `profile.yaml` (for example from
  `profile install`) with `path: /abs/dir` or `../../..` makes `update` copy an
  arbitrary local folder holding a `SKILL.md` into the profile. Apply the same
  validation in `profiles._parse_source`.
- N2 `_replace` window: if `os.replace(incoming, live)` (line 417) fails after
  `os.replace(live, old)` succeeded, `replaced` has not been appended, so
  `_restore` does not bring the old folder back and the item folder is missing
  (row reports error, loop continues). Append before the second rename, or
  restore inline.
- N3 Non-`SwitchBlocked` failures in `items.refresh_active` (any other
  `RespecError`/`OSError` from `switch.use`) skip both undo and the cleanup at
  lines 390-391, leaving `.<item>.old` folders and a saved `profile.yaml`
  with the new commits. Files and `profile.yaml` agree, and `state.json` stays
  under switch's own journal, so this is consistent but untidy; leftovers are
  removed on the next update of that item.
- N4 `digest` (line 150) hashes only regular files: adding an empty folder or
  a symlink to a folder is not seen as a local edit, so `update` would
  overwrite it without asking. Rare for skills; document or include
  directories/symlinks.
- N5 `_git` inherits `GIT_DIR`/`GIT_WORK_TREE` from the environment; when
  respec runs inside a git hook, `git init`/`fetch` with `cwd=tree` would act
  on the caller's repository. Drop `GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_INDEX_FILE` from the child env.

## Requested investigations

- (a) Isolation: PASS. Autouse `isolated_git` sets `GIT_CONFIG_GLOBAL` to a
  temp file, `GIT_CONFIG_NOSYSTEM=1`, author env and `RESPEC_GIT_BASE_URL`
  to a temp `file://` dir; conftest already sets temp `HOME`, `RESPEC_HOME`,
  `RESPEC_USER_HOME` and guards path resolvers. No `https`/`ssh`/`github`
  URL appears in `tests/test_sources.py`; `add acme/nope` resolves to
  `file://`. `RESPEC_GIT_BASE_URL` is read at call time (`base_url()`).
- (b) `source.digest` / ask-before-overwrite: compliant. `_modified` treats a
  missing digest as edited, so installed or hand-written sourced items ask.
  `update` overwrites only when `overwrite_edits` returns true: `--yes`, or an
  interactive "y"; `--json` without `--yes` skips; non-interactive stdin
  aborts (verified: `update </dev/null` -> "Aborted.", rc 1, edits kept, no
  leftovers). Only caveat is N4. The schema addition is optional and
  backward compatible; README documents it.
- (c) Disabled sourced items are updated: consistent with the spec. Decision 9
  and the user story only require that disabling keeps the item, its source
  record and local edits; local edits stay protected by the same prompt, and
  disabled items stay unlinked (verified: exclusive-layer member `y` updated
  to `y2`, still not linked). `update [item]` "applies" with no enabled-only
  restriction.
- (d) Rebase against 008: `profiles.py` diff is only `digest` in
  `SOURCE_KEYS`, `Source` and the docstring; `TOP_LEVEL_KEYS`, `LAYER_KEYS`,
  built-ins intact. `update` saves `dataclasses.replace(profile, skills=...)`,
  so `layers` are kept. Verified end to end: `add acme/two --ref main`, then
  `layer use design-principles x`, `layer add-item design-principles y`,
  upstream push, `update` updated both, only `x` linked, `layers` block and
  `ref: main` preserved. `profile install` of a repo with a `layers:` block
  installs it through `parse_profile` validation.
- (e) `items.refresh_active`: a thin public wrapper over `_refresh`; undo runs
  on `SwitchBlocked` and restores folders plus `profile.yaml`. Git fetch/clone
  failures happen before any profile write (add: in `checkout`, before
  staging; update: per item in `_replace` before the rename, row "error",
  other items continue and are saved). `state.json` is written only by
  `switch.use`. Gaps are N2 and N3.
- (f) Subprocess: list argv, no shell, `GIT_TERMINAL_PROMPT=0`, `check=False`
  with stderr surfaced. Option injection is not prevented: B1. `ext::` is not
  reachable (git's default `protocol.allow` blocks it) and `ssh://-host` is
  rejected by git itself.

## Acceptance evidence checked

- add shorthand/URL/several skills/`--ref`/active linking/clash/no-SKILL
  failure: tests present and pass; reproduced shorthand and `--ref` manually.
- `update --check`, `update [item]`, links refreshed when active, unsourced
  items never change: tests pass; reproduced manually.
- Local edits prompt: tests pass; reproduced decline and non-interactive abort.
- `profile install`: tests pass; reproduced install with layers.

Scope: changes stay within ticket 007 (sources module, CLI commands, one schema
field, one `items` seam, README, tests). No unrelated churn.
