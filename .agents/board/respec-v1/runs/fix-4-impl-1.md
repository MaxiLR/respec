# fix-4 implementation, round 1

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-4`
- Branch: `codex/respec-v1-fix-4`, base `fc7912b`
- Head: `2734ac0`
- Inputs: `t007-review-3.md` (N9 to N13), `int-fc7912b.md` (medium finding 1,
  low findings 2 and 3)
- AGENTS.md: none in the repository; global CLAUDE.md applies

## Changes

- `src/respec/sources.py`
  - `_check_links` refuses a symlink whose target is a folder: "symlink 'x'
    points to a folder; only links to files inside the skill folder are
    copied". This check replaces the old "points at a folder holding it"
    check, which it covers.
  - `copy_fetched` summarizes `shutil.Error`/`OSError` with `_reason`. The
    message gives the first cause and "(and N more)", with no temporary paths.
  - `_git` sets `GIT_SSH_COMMAND="ssh -o BatchMode=yes"` for `fetch` and
    `ls-remote`. It leaves that variable alone when `GIT_SSH_COMMAND`,
    `GIT_SSH` or `core.sshCommand` is already set (`_own_ssh`). Every git call
    runs with stdin set to `DEVNULL`. `GIT_TERMINAL_PROMPT=0` is kept.
  - `FULL_SHA` is anchored with `\Z`.
  - Optional item: `digest` is renamed to `fetched_digest`, and its docstring
    says it is not `unknown.digest`. `_label` now uses `unknown.real`.
- `src/respec/profiles.py`: `NAME_PATTERN`, `REPO_SHORTHAND` and `REPO_URL`
  use `\Z`. `REPO_SHORTHAND` rejects `.`/`..` as the owner or the repo.
  `source_value_problem` rejects control characters in every source value.
  This covers scp-like repos, refs and commits, which no end-anchored regex
  checks.
- `src/respec/cli.py`: `_short(commit)` renders a missing commit as `unknown`
  in `update` and `update --check` output.
- `README.md`: documents the file-links-only rule and batch-mode ssh.
- `tests/test_sources.py`: adds 18 test cases (the "fix-4: hardening"
  section).

### N9 choice: refuse folder links

I chose to refuse folder links instead of keeping links as links in the
profile copy. Reasons:

1. It is a single check in the existing round-3 validation pass.
2. Kept links would move the problem to the targets: copy-mode installs, and
   any agent tool that follows links, would still expand nested or sibling
   folder links.
3. It also removes the sibling-loop case.

File links that resolve inside the skill folder are still copied as plain
files. Each link adds at most one copy of one file. That growth is linear in
the number of entries in the repository, and a repository can already cause
it at the same fetch cost with duplicate blobs.

Round-3 behavior is unchanged. Links that leave the skill, dangle or loop are
still refused, and every existing symlink test passes.

## Criterion to evidence

1. **N9.** `test_nested_folder_links_cannot_multiply_the_copied_files`: 6
   levels of `a`/`b` links to the previous level, over a 10 kB blob. Red: the
   add succeeded (rc 0). Green: rc 1, the output says "symlink ... folder",
   the profile holds less than 10 kB, and no item was added.
2. **Missing commit.** The tests install a modpack whose `tdd` source has no
   commit.
   - `test_check_of_item_without_recorded_commit_reports_unknown`. Red:
     `TypeError: 'NoneType' object is not subscriptable`. Green:
     `tdd  update available unknown -> <sha12>`.
   - `test_update_of_item_without_recorded_commit_fetches_and_records_it`.
     Red: the same TypeError. Green: rc 0, the output shows
     `updated unknown -> <sha12>`, and the commit and digest are recorded.
   - `test_failed_update_of_item_without_commit_changes_nothing`: upstream
     loses `SKILL.md`, so the update fails. `profile.yaml` stays
     byte-identical, the folders are unchanged and nothing is left over. This
     test was green before the fix; it guards the no-crash path.
   - The integration crash happened after `sources.update` had already saved.
     It came only from CLI rendering, which `_short` removes.
3. **N10.** `test_sibling_folder_link_loop_is_a_short_readable_error`: the
   links are `a/c -> ../e` and `e/c -> ../a`. Red: the output was a raw
   `shutil.Error` list of `respec-check-.../e/c/c/c...` paths. Green: a
   message under 300 characters that names the symlink, with no `Errno` and
   no temporary path. Loops through file links still give the existing
   "broken, loops or points outside" message.
4. **N11.**
   - `test_names_with_a_trailing_newline_are_rejected`: `profile new "bad\n"`.
     Red: rc 0. Green: refused, no folder.
   - `test_source_values_with_a_trailing_newline_are_rejected`, 4 cases
     (shorthand, URL, scp-like, ref). Red: shorthand and URL first, then
     scp-like and ref.
   - `test_commit_ref_with_a_trailing_newline_is_not_taken_as_a_commit`. Red:
     `remote_commit` returned `sha + "\n"`.
5. **N12.** `test_shorthand_with_dot_segments_is_rejected`, cases `../x`,
   `./x`, `acme/..`, `acme/.` and `../..`. Red: git ran against the escaped
   path. Green: the repo is refused before git runs.
6. **N13.** A fake `ssh` on PATH logs its argv and `GIT_TERMINAL_PROMPT`, then
   exits 255.
   - `test_ssh_runs_in_batch_mode_with_prompts_off`. Red: the argv had no
     `BatchMode=yes`. Green: `BatchMode=yes` and `prompt=0` are logged, and
     the call raises `RespecError` without hanging.
   - `test_users_own_ssh_command_is_kept`: `core.sshCommand` is set in the
     isolated `GIT_CONFIG_GLOBAL`, and it is used unchanged (no BatchMode).
     This is a guard test; it was green before the fix.
7. **Optional.** `fetched_digest` rename and docstring; `_label` uses
   `unknown.real`. Done.

No test uses the network or the real git config. All of them use
`isolated_homes` and `isolated_git` (`file://` bare repos, temporary
`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_NOSYSTEM=1`). `--home` is not reintroduced.

## Verification (fresh, at 2734ac0)

| Command                            | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `236 passed` (218 before, plus 18 new)       |
| `uv run black --check .`           | `27 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

## Concerns

- Behavior change: skills that link to a folder inside themselves (for
  example `docs -> shared/docs`) can no longer be added. The README documents
  this, and it is the safe option the review suggested.
- When neither `GIT_SSH_COMMAND` nor `GIT_SSH` is set, each `fetch` or
  `ls-remote` runs one extra `git config --get core.sshCommand` (local and
  cheap). A user-configured ssh command does not get `BatchMode` added, so it
  could still prompt. This follows the "unless the user configured their own"
  rule.
- Control characters are now rejected in every source value, including
  `commit` and `digest`. Real values never contain them.
