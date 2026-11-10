# Ticket 007 review 3 (fresh, independent, security-focused)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t007`. The tree
  was clean at `934b772`.
- Diff reviewed: `d16724a..934b772` (`dc77f56`, `c2ea63f`, `94aa79e`, `2eac847`,
  `934b772`).
- Inputs: ticket 007, spec, reviews 1 and 2, and impl runs 5 and 6. I treated
  the impl runs as claims and checked them. The worktree has no `AGENTS.md`,
  `CONTEXT.md` or decision records.
- Manual attacks ran through the real CLI (`.venv/bin/respec`). Each case had
  its own scratch `HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` under
  `/private/tmp/t007r3/cases/<case>`. `GIT_CONFIG_GLOBAL` pointed at an empty
  file, `GIT_CONFIG_NOSYSTEM=1` was set, and `RESPEC_GIT_BASE_URL` was a
  `file://` dir. Bare repos lived under that dir. A secret tree at
  `/private/tmp/t007r3/secret` held the marker `SECRETBYTES`, and after every
  run `grep -r SECRETBYTES` was run over the respec home and the user home.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS (no blocking findings; non-blocking notes below)
- tests-rerun: PASS

## Gates rerun (fresh)

- `uv run pytest -q`: 218 passed
- `uv run black --check .`: 27 files unchanged
- `npx prettier@3 --check README.md`: clean
- Mutation (scratch `git archive` copy under `/private/tmp/t007r3/mut`):
  dropping `symlinks=True` from the first `copytree` in `copy_fetched` fails
  9 tests (all S1 nested/chain/dir cases for add, update and install, plus
  the loop test). The tests guard the fix.

## Blocking findings

None.

## (a) S1 and variants: no file from outside the skill reached RESPEC_HOME or the targets

`add acme/r#skill -p p`, each refused with rc 1, no leak, and an empty
profile:

| Case                                                                 | Result                                               |
| -------------------------------------------------------------------- | ---------------------------------------------------- |
| prior nested repro `skill/link -> ../other`, `other/evil -> secret`  | refused: "broken, loops or points outside the skill" |
| chain `c1 -> c2 -> ../out`, `out -> /abs/secret/dir`                 | refused                                              |
| absolute file link                                                   | refused                                              |
| absolute dir link (`d -> /abs/secret`)                               | refused                                              |
| `../../../../../../../../../../../private/tmp/.../key`               | refused                                              |
| `SKILL.md -> /abs/secret/key`                                        | refused                                              |
| repo-root skill with `up -> ..`, and `me -> .`                       | refused (outside/ancestor)                           |
| symlinked item folder `skills/a -> /abs/dir` (discovery and `#path`) | refused by `inside()`                                |
| symlinked `#path` component (`lnk/secretskill`), symlinked `skills/` | refused by `inside()`                                |
| sibling dir-link loop (`b -> a`, `a/c -> ../d`, `d/e -> ../b`)       | clean `RespecError` (ELOOP), rollback, no leak       |

Positive controls: an in-skill chain `c1 -> c2 -> sub/f` and
`x -> ../item/SKILL.md` were accepted and copied as plain files. The second
one resolves inside the checked copy, so only skill content can be read.

- `profile install acme/pk` refused these, each with rc 1, no leak and no
  profile created: the nested repro (`skills/a/link -> ../../x`,
  `x/evil -> secret`), an absolute dir link, a symlinked `profile.yaml`
  (refused before the read), and a symlinked `skills/a` item folder. A
  symlinked `skills/` dir fails on the missing items. If it named an existing
  outside folder, `copy_fetched`'s `_within` would refuse it.
- `update --yes`: I added a clean v1 to an active profile, then pushed v2
  with each of: nested repro, absolute dir link, `SKILL.md -> secret`, and
  `skill -> /abs/dir`. `update --check` exited 0, and `update` reported a
  per-row error with rc 1. In every case the profile kept v1, the target
  link was intact, no `.old`/`.incoming` was left behind, and there was no
  leak.
- Hardlinks: git has no way to record a hardlink. Checkout writes separate
  files, and `copytree` copies contents, so this vector does not exist.
- TOCTOU: the fetched tree (`respec-git-*`) and the check copy
  (`respec-check-*`) are `mkdtemp` folders with mode 0700, owned by the user.
  The remote cannot change them between `_check_links` and the dereferencing
  copy, and only a same-user local process could. The remote can change
  between `ls-remote` and `fetch`, but the recorded commit comes from the
  actual checkout (`rev-parse HEAD`), so that race only shifts which commit
  is recorded. Not exploitable.
- Git's own symlink-collision write (a case-colliding `a -> /victim`
  symlink plus `A/pwn`, built with `mktree`) did not happen. git 2.50.1 wrote
  nothing outside the tree, and respec refused the link.
- Why the fix is structural: the first copy never follows links. `os.walk`
  then checks every link in that private copy, and relative links are
  re-anchored to the copy, so a link that leaves the copy cannot resolve to
  repository or host files. Only after the check does the second
  `copytree` dereference links, and every link it follows resolves into the
  checked copy.

## (b) B1 and variants: no command ran and no marker was created

- CLI SOURCE values:
  - `--upload-pack=...` and `-u ...` are rejected by click.
  - After `--`, a leading `-` falls back to the local-folder path ("is not a
    folder") or gets "must not start with '-'".
  - `#-s` and `#../x` are refused.
  - `ext::...`, `fd::3` and `evil::x/y` are not git specs, so they are
    treated as local folders and not found.
  - `ssh://-oProxyCommand=...` gives git's "strange hostname blocked", and
    `git@host:-oProxyCommand=x` gives "strange pathname blocked".
- `x@-oProxyCommand:r` and `ssh://u@-oProxy/x` reach ssh (logged through a
  `GIT_SSH_COMMAND` stub) only as `x@-oProxyCommand`. The `user@` prefix keeps
  ssh from reading it as an option, so this is harmless.
- `--ref` on `add` and `profile install`:
  - `--upload-pack=...` and `-c` are refused.
  - A leading space, an embedded newline plus option, and `HEAD:refs/...`
    reach git only after `--end-of-options` and end in "invalid refspec" or a
    fetch error.
- `profile.yaml` from `profile install`:
  - `repo: fd::3`, `ext::...`, `x@-oProxyCommand=touch:r` and `../../..` are
    refused by `_repo_problem`.
  - `ref: --upload-pack=...` is refused.
- `GIT_ALLOW_PROTOCOL=file:git:http:https:ssh` is set on every git call, so a
  user `protocol.*.allow` setting and http redirects cannot enable helpers.
  Unit test `test_remote_helper_transports_are_refused` covers this.
- The child env drops `GIT_DIR`, `GIT_WORK_TREE`, `GIT_CONFIG_PARAMETERS` and
  `GIT_CONFIG_COUNT/KEY_*/VALUE_*` (test `test_inherited_git_dir_is_ignored`).
  No user value can land before `--end-of-options`, and `checkout --detach`
  only ever gets a full 40-hex SHA.

## (c) New behavior changes against the spec

- In-repo links that leave the skill folder are refused. The spec and ticket
  are silent on symlinks: decision 8 and the user story only require "add a
  skill from a GitHub repo in one command". A legitimate monorepo skill that
  symlinks a shared file (`skills/a/g.md -> ../../shared/g.md`, reproduced
  through `profile install`) can no longer be added at all. The error message
  is clear and README documents the rule. This is a usability limit and does
  not violate the spec, so it is non-blocking. See N9 for a safe way to lift
  it.
- CLI `add file://...` outside the base URL is refused. The spec requires
  GitHub `owner/repo` and git URLs, and `file://` only as the test seam
  (testing seams: "local bare repositories (`file://`), no network"). Local
  folders are still added by path. This blocks nothing the spec requires.

## (d) Rebase correctness: confirmed

- `grep -- --home src README.md` finds nothing. The commands use `_homes(ctx)`.
- `switch.py`, `state.py`, `unknown.py`, `restore.py`, `layers.py` and the
  TUI are unchanged by the diff (`git diff --stat` empty for them). Sourced
  changes reach targets only through `items.refresh_active -> _refresh ->
switch.use`, so fix-1 copy digests and 005's backup manifest still apply.
  `test_update_in_copy_mode_refreshes_copies_and_records_their_digest`
  passes. It is an integration test that uses `unknown.digest` as the oracle.
  This is acceptable, but it was not red-first.
- 004 blocking and rollback, reproduced manually:
  1. With an active profile and a foreign `~/.claude/skills/foreign`,
     `update --yes` is blocked ("Profile 'p' was left unchanged").
  2. The profile kept v1, `profile.yaml` stayed byte-identical, and no
     leftovers were found.
  3. After the foreign entry was removed, the update applied v2.
- 008 layers: `update` saves `dataclasses.replace(profile, skills=...)`, so
  the `layers` block is preserved. All suites pass (218).

## (e) Test isolation: confirmed

- The autouse `isolated_git` sets `GIT_CONFIG_GLOBAL` to a temp file and
  `GIT_CONFIG_NOSYSTEM=1`. `GIT_CONFIG_GLOBAL` also overrides the XDG
  config. It sets `RESPEC_GIT_BASE_URL` to a temp `file://` dir.
- The conftest gives temp homes and guards the path resolvers against the
  real home.
- `tests/test_sources.py` contains no http, https, ssh or git URL. The
  option-like values in the defense-in-depth test resolve as local paths.

## Non-blocking findings

- N9 Exponential copy amplification through in-skill directory links.
  - Location: `src/respec/sources.py` `copy_fetched` / `_check_links` (lines
    244-287). Links to sibling folders inside the skill pass the check, and
    the second `copytree` dereferences every one of them.
  - Scenario: `l0/blob` is 100 KB, and `l{i}/a`, `l{i}/b` both link to
    `../l{i-1}` for i = 1..12. The repo is 104 KB. `respec add acme/r#skill`
    succeeded in 20 s and wrote an 800 MB profile with 8,191 copies of
    `blob`. With N = 20 it would be about 200 GB, and copy-mode targets would
    double it. `digest()` then reads all of it.
  - Impact: a malicious repo or modpack can fill the disk. Nothing is read
    from outside the skill, and git tree reuse already allows similar
    "tree bombs" in a plain checkout, so this is not blocking.
  - Suggested fix: keep only file links (refuse links to directories), or
    cap the total copied bytes or entries. Refusing directory links would also
    remove the sibling-loop ELOOP case.
- N10 The sibling-loop error is unreadable. The `RespecError` embeds the whole
  `shutil.Error` list: three long `.../a/c/e/c/e/...` temp paths. Summarize it,
  for example "symlinks form a loop".
- N11 `REPO_URL`/`REPO_SHORTHAND` use `$`, which matches before a trailing
  `\n`, so `"a/b\n"` passes shape checks. git rejects newlines in URLs
  (verified: fetch error), so this is harmless. Prefer `fullmatch` or `\Z`.
- N12 `REPO_SHORTHAND` accepts `..`/`.` segments (`../x`). With the default
  https base this is harmless. With a user-configured `file://` base, a
  profile repo `../x` would escape the base dir and bypass the N8 rule that
  the `file://` branch enforces. Reject `.`/`..` owners and repos.
- N13 A modpack `user@host:path` repo makes `update --check` run ssh to an
  arbitrary host. On a TTY, ssh may show a host-key prompt, because
  `GIT_TERMINAL_PROMPT=0` does not affect ssh. Consider
  `GIT_SSH_COMMAND`-free `-o BatchMode=yes` via `GIT_SSH_VARIANT`/config, or
  document the behavior.
- Carried note: in-repo links outside the skill are now refused (see (c)).
  Dereferencing them from the private fetched tree after a strict
  within-repo check, instead of refusing, would be safe only if the
  dereferenced content is itself re-checked. The current refusal is the
  simpler safe choice.

## Acceptance evidence

All three criteria have passing tests. I reproduced them in this round:

- add records repo, path, ref, commit and digest.
- `update --check` and `update` refresh the active target and roll back
  when blocked.
- `profile install` installs once, keeps item sources, and owns the profile
  locally (review 2 evidence is unchanged).

Scope stays within ticket 007, and the last commit is test-only.
