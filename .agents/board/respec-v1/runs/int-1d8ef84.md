# Integration check at 1d8ef84

- Worktree: `/Users/maxilr/Documents/GitHub/respec`, branch `codex/respec-v1`
- Head: `1d8ef84d84109d68f642d6cd10a0dcbd8bf3119d` (`git rev-parse HEAD`
  matches the expected head)
- Merged: 001, 002, 006, 008, 004, fix-1, 010, fix-2, 005, 007, fix-4. The
  most recent merge is fix-4.
- Change range: `fc7912b..1d8ef84`, touching `README.md`, `src/respec/cli.py`,
  `src/respec/profiles.py`, `src/respec/sources.py` and
  `tests/test_sources.py` (+296/-35)
- AGENTS.md: none in the repository; global CLAUDE.md applies
- Working tree: the only uncommitted changes are the orchestrator's files under
  `.agents/board/respec-v1/`, which this check did not touch
- This was a read-only check. The only file written in the repository is this
  report.

## Gates

| Gate                                                                                           | Result                                                              |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `uv sync --frozen`                                                                             | PASS (`Audited 27 packages`)                                        |
| `uv lock --check`                                                                              | PASS (`Resolved 28 packages`)                                       |
| `uv run --frozen pytest -q`                                                                    | PASS, `236 passed in 48.42s`, no skips                              |
| `uv run --frozen black --check src tests`                                                      | PASS, `27 files would be left unchanged.`                           |
| `npx --no-install prettier --check README.md .agents/board/respec-v1/spec.md`                  | PASS, Prettier 3.9.10, `All matched files use Prettier code style!` |
| `python -c "import respec.sources, respec.unknown, respec.tui, respec.restore, respec.switch"` | `imports ok` (the new `sources -> unknown` import adds no cycle)    |

## Callers of the digest rename and the `unknown.real` reuse

- `sources.digest` was renamed to `sources.fetched_digest`. `grep sources.digest`
  over `src`, `tests` and `README.md` finds nothing. The three internal callers
  (`add`, `_modified`, `_replace`) use the new name.
- `restore.py` (lines 165 and 206) and `switch.py` (line 314) call
  `unknown.digest`, which this range did not change. `tui.py` imports
  `unknown` only for the `Unknown` type and calls no digest helper. No caller
  broke.
- `unknown.real(p)` is `Path(p).parent.resolve() / Path(p).name`, the same
  expression `sources._label` used before, so labels are unchanged. Callers in
  `restore.py` (270-283), `switch.py` (153, 258, 265), `adopt.py` and
  `cli.py:742` are untouched.
- `sources` now imports `unknown`. `unknown` imports only `profiles`, `targets`
  and `state`, so there is no cycle.

## End-to-end smoke (temp homes, local bare repos over file://)

- Script: `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/smoke8.sh`
- Log: `/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/smoke8.log`
- Env: `RESPEC_USER_HOME`, `RESPEC_HOME`, `RESPEC_GIT_BASE_URL=file://…/base`
  and `GIT_CONFIG_GLOBAL=/dev/null`. `base/acme/kit` and `base/acme/prof` are
  bare repos. `~/.claude/skills` starts with `orig-skill/` and `notes.txt`.

1. `profile new work -t claude-code`; `add acme/kit -p work` → added alpha and
   beta at `7d8fa40d234b`. Each item records repo, path, commit and a
   `sha256:` digest.
2. `use work` → takeover backup, 2 items installed. `adopt --all keep` keeps
   the original entries as unmanaged.
3. `update --check` → both up to date. After pushing v2, `--check` shows
   `update available 7d8fa40d234b -> 7a347657ecc9`. `--json` shows
   `update_available: true, modified: false, error: null`.
4. `update --yes` → both `updated`, and the live link shows `# alpha v2`.
   After a local edit to beta and a v3 push, `update --yes` overwrites beta,
   which is what `--yes` documents.
5. Separate run (`home2`): beta tracks the default branch, has a local edit,
   and v5 is pushed. `update --check` shows `update available … (local edits)`.
   `update </dev/null` prompts `Overwrite? [y/N]: Aborted.` and exits rc 1.
   The local edit stays in place. With a commit as `--ref`, the item reports
   `up to date (local edits)`, which is correct because the commit pin does not
   move.
6. fix-4, folder links: `add acme/kit#skills/linky` where the skill holds
   `dirlink -> sub` gives rc 1 with
   `error: symlink 'dirlink' points to a folder; only links to files inside the skill folder are copied`.
   Nothing is left behind (the profile skills folder still holds only alpha
   and beta). After `dirlink` is removed from the repo, the add succeeds and
   `filelink` is copied as a plain file.
7. fix-4, missing commit: `profile install acme/prof`, whose gamma source has
   no commit or digest. `update --check -p prof` →
   `gamma  update available unknown -> a509b1f0a019  (local edits)`, rc 0, and
   `update -p prof --yes` → `gamma  updated unknown -> a509b1f0a019`, rc 0.
   Neither crashes now. The earlier int-fc7912b finding 1 is resolved. The
   commit and digest are recorded afterward. With a recorded commit that does
   not exist upstream (`0123…`), check and update report
   `0123456789ab -> a509b1f0a019` and the update succeeds.
8. `update --home /x` → rc 2, `No such option: --home`.
9. `restore` → `Removed 3 respec items`, restored claude-code, and
   `state.json` is empty. The `~/.claude` snapshot taken before and after is
   identical (`SNAPSHOT IDENTICAL`).

Note: `add "acme/../x"` and `add "acme/kit\n"` are not treated as repo
shorthand, so `add` handles them as local paths and fails with
`… is not a folder` (rc 1). The anchored regexes and control-character
checks are exercised by the unit tests in `tests/test_sources.py`, not by this
CLI path.

## Duplicates and vocabulary

- Resolved in this range: `sources._label` now reuses `unknown.real`. The
  digest helpers now have distinct names, and `fetched_digest` documents that
  it is never compared with `unknown.digest`.
- Still present, from before this range: `switch._real` (switch.py:93) is
  identical to `unknown.real`, and `restore._kind` (restore.py:303) is
  identical to `unknown._kind` (unknown.py:111). Both functions have the same
  body.
- Low: both digest flavors still emit `sha256:<hex>` under a key named
  `digest` (`profile.yaml` `source.digest` vs `state.json`/manifest
  `digest`). This is documented in the docstring and not a bug.
- Info: `restore._within(path, root) -> bool` and
  `sources._within(root, entry) -> None/raise` share a name but have different
  contracts and argument order. They are module-private, so this is not a
  conflict.
- Vocabulary: the README matches the code. It describes file links only,
  `BatchMode=yes` unless `GIT_SSH_COMMAND`/`GIT_SSH`/`core.sshCommand` is set,
  and `file://` refused outside the base URL. The CLI says `source`,
  `update --check`, `(local edits)`, `unknown` for a missing commit, and
  "owned locally", consistent with spec decision 8. No drift found.

## Findings

- No new cross-ticket bugs. The two pre-existing low duplicates remain
  (`switch._real` and `restore._kind`), and both digest kinds still share the
  `sha256:` prefix.
