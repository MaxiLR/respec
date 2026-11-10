# fix-4 review, round 1

- Reviewer: fresh, independent (did not implement fix-4)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-4`, HEAD
  `2734ac0a274d09d7b840e67b43258caaf3c0727f` (clean)
- Diff: `fc7912b588d02cf9f3aa855733d488b92f43f19f..2734ac0` (README, `cli.py`,
  `profiles.py`, `sources.py`, `tests/test_sources.py`)
- Inputs: `spec.md`, `t007-review-3.md` (N9 to N13), `int-fc7912b.md`
  (medium 1, low 2 and 3), claims in `fix-4-impl-1.md`
- AGENTS.md: none in the repository. The global CLAUDE.md applies.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS
- tests-rerun: PASS
- blocking findings: 0

## Gates rerun (fresh, at 2734ac0)

| Command                            | Result                                       |
| ---------------------------------- | -------------------------------------------- |
| `uv sync --frozen`                 | `Audited 27 packages`                        |
| `uv lock --check`                  | `Resolved 28 packages`                       |
| `uv run pytest -q`                 | `236 passed in 48.04s`, rc 0                 |
| `uv run black --check .`           | `27 files would be left unchanged.`          |
| `npx prettier@3 --check README.md` | `All matched files use Prettier code style!` |

The first pytest attempt was killed (exit 137) when the reviewer session was
interrupted. The full rerun passed.

## Acceptance evidence (manual, real CLI)

All manual runs used scratch dirs under `/private/tmp/claude-501/.../scratchpad`
with temp `HOME`, `RESPEC_HOME`, `RESPEC_USER_HOME`, `GIT_CONFIG_GLOBAL`,
`GIT_CONFIG_NOSYSTEM=1` and a `file://` `RESPEC_GIT_BASE_URL`. I used
`.venv/bin/respec` from the worktree.

1. **N9 (original disk-fill repo).** `l0/blob` is 100 kB of random data, and
   `l{i}/a` and `l{i}/b` both point to `../l{i-1}` for i = 1..12. This is the
   round-3 repository that wrote 800 MB. `respec add acme/bomb -p work`
   returned rc 1 in 0.27 s with
   `error: symlink 'l11/a' points to a folder; only links to files inside the skill folder are copied`.
   `RESPEC_HOME` totals 4 kB, `profile.yaml` has `skills: {}`, and nothing is
   left behind. The first copy keeps links as links (`copytree(symlinks=True)`),
   and `_check_links` refuses the folder link before the dereferencing copy, so
   no expansion happens.
2. **Missing commit.** I used a modpack with item `a` (source without
   `commit`) and item `b` (with `commit`), ran `profile install` and `use`
   (active, symlink mode), and then pushed upstream changes.
   - `update --check` (text and `--json`): no crash. The output shows
     `a  update available unknown -> 639a02093fa9`, and JSON has
     `"current": null`. A snapshot of `RESPEC_HOME` and `HOME` (tree plus file
     hashes) is identical before and after.
   - `update --yes` with `a` succeeding and `b` failing (upstream lost
     `b/SKILL.md`): `a  updated unknown -> 639a02093fa9`,
     `b  error: ... has no SKILL.md in b`, rc 1. `b`'s folder still holds v1,
     and `profile.yaml` changed only `a` (commit and digest added). This is the
     existing per-item design of `sources.update`.
   - `update --yes` with the commit-less item `a` failing: `a  error: ...`,
     rc 1. `a`'s folder keeps v1, and `profile.yaml` keeps no commit for `a`.
     A rerun where only `a` could change (`b` up to date) left the whole
     `RESPEC_HOME` and `HOME` snapshot identical. There is no traceback in any
     run.
3. **N10.** A sibling loop (`a/c -> ../e`, `e/c -> ../a`) is refused with
   `symlink 'a/c' points to a folder; ...`: one short line with no temp path
   and no Errno. File-link loops still give the existing "broken, loops or
   points outside" message (covered by the round-3 tests that still pass).
4. **N11.** `profile new $'bad\n'` is refused ("invalid profile name"), and
   no folder is created. The `REPO_*`, `NAME_PATTERN` and `FULL_SHA` regexes
   use `\Z`. Control characters are rejected in every source value. The unit
   tests for shorthand, URL, scp-like and ref values with a trailing newline,
   and for a commit with a trailing newline, pass.
5. **N12.** I hand-edited `profile.yaml` repos to `../abs`, `acme/..` and
   `..`, with the base `file://.../base/acme`. `update --check` refused each
   repo before git ran ("source repo ... must be 'owner/repo' ..."). `.../x`
   is still accepted, but it is a literal folder name, not traversal (git
   reported `.../x` as not a repository under the base).
6. **N13.** I put a fake `ssh` on PATH and pointed repos at
   `git@evil.example:x/y` and `ssh://evil.example/x`. ssh got
   `-o BatchMode=yes` with `GIT_TERMINAL_PROMPT=0`. A user
   `GIT_SSH_COMMAND="ssh -o Foo=bar"` and a global
   `core.sshCommand = ssh -o Baz=1` were each used unchanged, with no
   BatchMode added, as the "unless user-configured" rule allows. stdin is
   `DEVNULL` for every git call.
7. **Optional.** `sources.digest` is renamed to `fetched_digest`, with a
   docstring that sets it apart from `unknown.digest`. No stale `digest(`
   callers remain (grep). `_label` uses `unknown.real`.

## Round-3 security behavior: not weakened

- Exfiltration: an absolute link to `$HOME/secret` is refused ("points
  outside the skill folder"). A relative `../../../home/.ssh/id` is refused
  ("broken, loops or points outside"), because the check runs on a private
  copy of only the skill folder, so links that leave it dangle there. A
  monorepo skill `sk` with `t -> ../top` (inside the repo, outside the skill)
  is refused. `grep -r 'SECRET|KEY'` over `RESPEC_HOME` found nothing.
- Folder links are refused before the dereferencing copy: `. -> me` and
  `sub/up -> ..` are refused.
- File links are "copied as plain files": `g -> d/f`, `h -> g` (a chain) and
  `self -> ./SKILL.md` were copied as regular files with in-skill content.
  This cannot be abused. `resolve(strict=True)` must land strictly inside the
  private checked copy, and the target must not be a folder. A chain that
  passes through an outside entry dangles in the private copy, so it is
  refused. Folder links are refused, and `os.walk` does not follow links, so
  each file link adds at most one copy of one in-skill file: linear growth,
  the same as duplicate blobs. Git cannot store hardlinks, FIFOs or device
  files.
- Option injection: `--ref='--upload-pack=x'` is refused ("must not start
  with '-'"). `ext::` and `fd::` values are treated as local paths and
  refused. `--end-of-options` and `GIT_ALLOW_PROTOCOL` are unchanged. The new
  `git config --get core.sshCommand` call takes no user-controlled argument.

## Spec impact of refusing folder links

`spec.md` sets no requirement for symlinks inside fetched skills. Its
symlink text covers install-mode target links, which this diff does not
change. Refusing in-skill folder links blocks nothing the spec requires. The
README documents the behavior change (for example, `docs -> shared/docs` can
no longer be added).

## Non-blocking findings

1. **Low, misleading message (pre-existing check order).**
   `src/respec/sources.py` `_check_links`: the "outside" check
   (`base not in target.parents`) runs before the new folder check. A link to
   the skill root itself (`me -> .`) therefore reports "points outside the
   skill folder" instead of "points to a folder". It is still refused, so
   only the wording is affected.
2. **Info, update semantics.** `sources.update` is per item. When several
   sourced items are updated and one fails, the successful items are saved to
   `profile.yaml` and swapped in (rc 1). This matches the pre-fix design and
   `test_failed_update_of_item_without_commit_changes_nothing`, which covers
   the failing item only. I read acceptance item 2 ("a partial failure leaves
   profile.yaml and the folders untouched") per item, and it holds per item.
   If the engineer meant all-or-nothing across items, that is a new design
   decision outside this fix.
3. **Info, pre-existing.** `ls-remote` (and now the `_own_ssh` probe) runs
   with `cwd=None`, that is, the user's current folder. git therefore also
   reads that folder's repository config, which is git's normal trust model.
   A `core.sshCommand` there is honored and also skips BatchMode, as intended
   for a user-configured command. This diff introduces nothing new here.

## Test quality

The new tests check observable behavior: CLI rc and output, profile bytes,
tree size and the fake ssh argv. None of them asserts on source text. Two of
them (`..._changes_nothing`, `..._own_ssh_command_is_kept`) are guards that
were green before the fix, as the implementer disclosed. The dot-segment test
checks only the refusal message, but validation runs before any git call
(confirmed manually).
