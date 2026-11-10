# Ticket 007 review 2 (fresh, independent)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t007`, clean
  tree at `979625a`
- Diff reviewed: `60224c7..979625a` (`3b78094`, `2ebea13`, `979625a`)
- Inputs: ticket 007, spec, review 1, impl runs 3 and 4 (treated as claims).
  The worktree has no `AGENTS.md`, `CONTEXT.md` or decision records.

## Verdicts

- spec-compliance: PASS
- code-quality: FAIL (one blocking security finding, S1)
- tests-rerun: PASS

## Gates rerun (fresh)

- `uv run pytest -q` at `979625a`: 158 passed
- `uv run black --check .`: 23 files unchanged
- `npx prettier@3 --check README.md`: clean
- Scratch clone (in the session scratchpad, not the repo) of `979625a` merged
  with feature tip `77d592c`: merged cleanly, `pytest -q` 162 passed

Manual runs used a scratch `HOME`/`RESPEC_HOME`, `GIT_CONFIG_GLOBAL` pointing
at an empty file, `GIT_CONFIG_NOSYSTEM=1` and `file://` remotes only.

## Blocking findings

### S1. A directory symlink inside the repository still exfiltrates files from outside it

- Location: `src/respec/sources.py` `copy_fetched` (lines 228-247). The check
  walks `source` with `os.walk`, which does not descend into symlinked
  directories. `shutil.copytree(source, destination)` then runs with the
  default `symlinks=False`. It follows those directory links and dereferences
  every link it finds behind them, and none of those links were checked.
- Failing scenario (reproduced through the CLI). The repository `acme/nest`
  contains:
  - `skill/SKILL.md`
  - `skill/link -> ../other`, which resolves inside the repository and is not
    an ancestor, so it passes the check
  - `other/evil -> /abs/path/secret`, which points outside the repository

  `other/` is outside the checked `source`, so `os.walk` never sees
  `other/evil`. `respec add acme/nest#skill -p p` succeeds (rc 0), and
  `profiles/p/skills/skill/link/evil/key` contains the secret file's bytes.
  The same layout under `skills/a/link -> ../../x` and
  `x/evil -> /abs/secret` makes `respec profile install acme/pk` succeed and
  copy the secret. `update` uses the same function, so it is affected too.
  Plain link chains (`s/k -> ../out`, `out -> /abs/secret/key`) are refused
  correctly, because `resolve()` follows the whole chain.

- Impact: the 979625a fix is bypassable. A third-party repository or modpack
  can still make respec copy arbitrary local files and folders (for example
  `~/.ssh`) into a profile, and from there into agent skill folders.
- Suggested fix: validate every link that `copytree` actually visits. One
  option is an `ignore=` callback that runs `_within` (and the ancestor check)
  on each symlink entry of every directory `copytree` enters, including
  directories reached through links. Another is to walk with
  `followlinks=True` and a visited set of resolved directories. Add a
  regression test with the nested layout above for add, update and install.

## Non-blocking findings

- N6 Non-blocked `<helper>::` transports: `src/respec/sources.py` `_git`.
  `ext::` is refused by git's default `protocol.allow` (verified: "transport
  'ext' not allowed"). Other remote helpers fall under the "user" policy and
  are allowed, though. A modpack `profile.yaml` with
  `skills.e.source.repo: "fd::3"` makes `respec update --check -p mp` and
  `respec update` hang forever in `git remote-fd` (reproduced; I had to kill
  it). Any `git-remote-<name>` helper on PATH is reachable in the same way.
  No command injection resulted. Suggested fix: set
  `GIT_ALLOW_PROTOCOL=file:git:http:https:ssh` (and/or `protocol.allow=never`
  plus explicit allows) in the child environment. That also guards against a
  user config with `protocol.ext.allow=always`.
- N7 Raw traceback on copy errors in `sources.add`: lines 344-346 re-raise
  `OSError`/`shutil.Error` unchanged, and the CLI catches only `RespecError`.
  Scenario: `skill/link -> ../other`, `other/back -> ../skill` (inside-repo
  loop). `respec add acme/loop#skill` prints a Python traceback
  (`shutil.Error` with a long `link/back/link/...` path). Rollback is correct:
  `skills: {}`, no folder is left. Wrap the error in `RespecError`, as
  `install_profile` already does.
- N8 Profile-file `repo` is not shape-checked. `_parse_source` only rejects a
  leading `-`, so a modpack can name a local absolute path or `file://` repo
  of the user's machine. `update` then copies that local repository's files
  into the profile. This needs local knowledge, and the data stays on the
  machine. Consider requiring `is_git_spec` for profile `repo` values.
- Note: items installed by `profile install` carry no `digest`, so `check`
  marks them "(local edits)" and `update` asks before overwriting. This is
  conservative and matches review 1 (b), but deserves a README line or
  recording a digest at install time.

## Requested investigations

- (a) B1 option injection: fixed, and no command ran in any variant.
  `--ref=--upload-pack=...` on `add` and `profile install`, `-u ...` and
  `--upload-pack=...` as SOURCE, and `#-x` paths are all refused.
  - Leading whitespace in `--ref` reaches git as a refspec ("invalid refspec").
  - Leading whitespace in a profile `repo` is treated as a path ("does not
    appear to be a git repository").
  - Leading whitespace in a profile `ref` gives "has no ref".
  - `ssh://-oProxyCommand=...` and `ssh://u@-oProxyCommand...` are rejected
    by git.
  - `ext::sh -c touch ...` in `profile.yaml` (via install, then
    `update --check` and `update --yes`) gives "transport 'ext' not allowed".
  - `--upload-pack` in a profile `repo` or `ref` and `../..` in a profile
    `path` are refused at install by `_parse_source`.
  - `--end-of-options` comes before the URL/ref in `ls-remote` and both
    `fetch` forms (git 2.50.1). The `checkout --detach` ref must be a full
    SHA.
  - No `PWN*` marker file was created. The remaining gap is N6.
- (b) Symlinks: these are refused correctly:
  - direct outside links
  - link chains ending outside
  - a symlinked `profile.yaml`
  - a symlinked item folder
  - a symlinked `skills/` directory, through `_within(source)`
  - a symlinked `#path` component, through `inside()`

  In-repo file links are copied as files (test plus manual run). Nested links
  behind an in-repo directory link are not checked: S1.

- (c) N1: `source_value_problem` is applied in `_parse_source`,
  `parse_spec` and `inside()`, and has tests. N2: `_replace` restores inline
  (test). N3: `.old` folders are removed in `finally`, and `BaseException`
  during the loop (including the confirm abort) restores (test). N4: the
  digest covers directories, symlinks and the exec bit (test). A FIFO in an
  item folder would block `read_bytes`; this is negligible. N5: repository
  variables and `GIT_CONFIG_KEY_*/VALUE_*` are stripped, while
  `GIT_CONFIG_GLOBAL`/`NOSYSTEM` stay (test).
- (d) 004 and 008 are intact. With an active profile and a foreign
  `~/.claude/skills/foreign`, a sourced `add` was blocked with "Profile 'q'
  was left unchanged": no item, `profile.yaml` unchanged. An `update --yes`
  was blocked too: old content, old commit, no `.old`/`.incoming` leftovers.
  `update` saves `dataclasses.replace(profile, skills=...)`, so `layers` are
  kept. `profile install` goes through `parse_profile`, which includes layer
  validation. `profiles.py` changes are additive. Interaction with
  `77d592c`: `source.digest` (`sources.digest`, which describes profile item
  files as fetched) and `Installed.digest` (`unknown.digest`, which describes
  a copy-mode target entry) are separate fields with different algorithms,
  and they are never compared. After `update` replaces a profile folder,
  the target copy still matches its recorded `Installed.digest`. It therefore
  counts as managed, and `switch.use` replaces it. A user-edited target copy
  is flagged unknown, so the update is refused and rolled back. There is no
  conflict, only two hashing helpers to keep in mind (consider sharing one
  later).
- (e) Test isolation: the autouse `isolated_git` sets `GIT_CONFIG_GLOBAL` to a
  temporary file, `GIT_CONFIG_NOSYSTEM=1` and a `file://` base URL. The
  conftest sets temporary homes and guards against the real home.
  `tests/test_sources.py` contains no `https`/`ssh`/`github` URL.
  Option-like URLs in the defense-in-depth test resolve as local paths. No
  network access, and the real git config is never touched.

## Acceptance evidence

All three criteria have passing tests and were reproduced manually:

- `add` records repo, path, ref, commit and digest.
- `update --check` and `update [item]` refresh active links, leave unsourced
  items unchanged, and prompt before overwriting edits.
- `profile install` installs once, keeps item sources, and the profile is
  then owned locally.

Scope stays within the ticket.
