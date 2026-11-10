# t011 review 2

- Reviewer: fresh, independent reviewer (did not implement this work)
- Range: `e417ce87a36d965d3385c903e37b4153cd6f3791..e05615eb7e0f98e00a3e70ba6f4a914fea958ae0`
  (`fa23d2a`, `16bfcb0`, `e05615e`), worktree
  `/Users/maxilr/Documents/GitHub/respec-worktrees/t011`
- Inputs: ticket 011; the engineer's Sync addition; the spec; review 1; and
  `t011-impl-1..3.md`, which I treated as claims to verify.
- Method: I read the full diff (`sync.py`, `switch.plan`, `sources._run`, `tui.py`,
  `messages.py`, `items.user_path`, README). I reran the gates. I drove ad hoc Pilot
  and core runs in temporary homes with the **real shipped skills on**
  (`shipped_names() == ('profile-maker', 'respec')`) and a global skill `gnotes` in
  `config.yaml`. The scripts are in the scratchpad (`r2/a_sync.py`, `a_copy.py`,
  `b_inputs.py`, `c_git.py`, `e_global.py`).

## Verdicts

- spec-compliance: **PASS**
- code-quality: **PASS**
- tests-rerun: **PASS**
- Blocking findings: **0**

## Gates rerun (fresh, at e05615e, clean tree)

| Gate                             | Result                                    |
| -------------------------------- | ----------------------------------------- |
| `uv sync --frozen`               | ok                                        |
| `uv run pytest -q`               | 434 passed in 100.83s                     |
| `uv run black --check .`         | 36 files would be left unchanged          |
| `npx prettier --check README.md` | All matched files use Prettier code style |
| `git status --short`             | clean                                     |

## Investigation results

### (a) B1 is fixed: Sync now checks against the full plan

- `switch.plan` returns `_plan_all` unchanged, and `use` installs exactly `_plan_all`
  (`switch.py:612`). The setup: profile `work` on `claude-code` and `agents`, with 4
  skills and an exclusive layer, plus shipped and global skills. After `use`, the
  (target, skill) pairs in `switch.plan` equal those in `state.installed`
  (14 installs, empty symmetric difference). `sync.check` then reports `clean=True`,
  and the TUI says "All in sync".
- Drift is detected and each fix works:
  - **Removed shipped link** (`respec`): reported as `missing`. Re-apply cleans it.
  - **Global skill removed from `config.yaml`**: reported as "no longer enabled".
    Re-apply cleans it.
  - **Replaced link** (`s1` pointed at another folder): reported as an unknown entry
    with `replaced=True`. "Add" copied the replacement into the profile, logged the
    backup of the previous copy, and ended in "All in sync".
  - **Edited copy** (symlinks refused, so everything is installed as a copy; I edited
    `s1` and `gnotes`): both were flagged. `s1` was added (profile now holds
    "EDITED", backup logged). `gnotes` offered only remove; it was backed up and
    respec's own copy came back. Result: all in sync.
  - **Unknown entry**: removed, with the backup path in the log.
  - **Layer conflict**: detected, including the "not linked" lines for the second
    skill.
  - **Broken link to a missing profile folder**: "Disable" is offered (covered by
    `test_broken_link_without_its_profile_folder_offers_disable`).
- N1 below covers how a conflict and an edited copy interact.

### (b) B2 and input validation in every TUI field

All of these ran in one Pilot session, and the app never exited (`return_code None`):

- **Add folder**: `~nosuchuser_zz/skill`, a NUL byte, a 5000-character path, a file,
  a missing relative path, a newline, `~`, an existing skill, and `RESPEC_HOME`
  itself. Each one showed a one-line error.
- **Add from git** (repo and ref): `~user`, NUL, `--upload-pack=touch …`, `-oops`,
  `ext::sh -c …`, a ref of `--upload-pack…`, a ref with NUL, `file:///`, `#../../etc`,
  and 5000 characters. Each was refused before git ran, and the marker file was never
  created.
- **New profile name**: `../evil`, `a/b`, `.`, `..`, 300 characters (shown as
  ENAMETOOLONG), NUL, a space, `~x`, a duplicate, and a non-ASCII name. Each was
  refused in the dialog, and no profile folder was created.
- The CLI `respec add '~nosuchuser_zz/x'` now prints a clean error with rc=1.

### (c) Git runs in a worker, with cancel and a time limit

- The test server accepts TCP and never replies.
- **CLI**: with `RESPEC_GIT_TIMEOUT=3`, `respec add http://127.0.0.1:<port>/x.git`
  failed in 3.7s with "git fetch timed out after 3s (set RESPEC_GIT_TIMEOUT to allow
  longer)", rc=1. `RESPEC_GIT_TIMEOUT=abc` gives a clear error.
- **TUI**, in a Pilot run against the same server:
  - The editor stays responsive and shows "Fetching …" and the Cancel button.
  - `s` is ignored while busy, so Sync cannot run alongside the fetch.
  - `Esc` cancelled in 0.09s with "Cancelled; nothing was added."
  - `pgrep` found 3 git processes before the cancel and none after, so the whole
    process group was killed.
  - A second `Esc` after a cancel goes back to the list.
  - Every file under `RESPEC_HOME` was the same before and after.
- `asyncio.to_thread` copies the context, but `cancel_on` is entered inside the
  thread, so the cancel event is wired correctly.

### (d) Reserved names can only be removed

- In my run, Sync offered only `sync-unknown-0-remove` for `gnotes`, and both choices
  for ordinary skills.
- `AdoptDialog` builds its choices from `adopt.choices(profile, entry, respec_home)`,
  the same function the CLI uses, for the `a`, switch and takeover dialogs.
- `test_entry_named_like_a_shipped_or_global_skill_can_only_be_removed` covers both
  screens, and I checked that it passes.

### (e) A global skill with no folder: acceptable, with a wording nit (N2)

- Reproduced with a global skill `ghost` listed in `config.yaml` that has no folder.
- Sync reports `ghost (claude-code) is enabled in the active profile but not linked`
  and offers "Re-apply profile work".
- Re-apply fails cleanly and logs "global skill 'ghost' (listed in …/config.yaml) has
  no folder at …/global/skills/ghost". That message says what to fix, nothing changed
  on disk, and nothing crashed.
- This is acceptable for a manual v1 check. The weak point is the first line, which
  blames "the active profile" for a global skill (N2).
- I could not reproduce the variant where the folder of an already-linked global
  skill is deleted: the guard denied that command (see "Guard denial"). Reading the
  code, it follows the same path: a `broken` row, `folder_gone=None` (that field only
  covers profile skills), Re-apply offered, and the same refusal from
  `_check_global`.

### (f) Profile editing uses core paths

- Toggles call `items.set_enabled`. Exclusive layers call `layers.use`, or
  `layers.set_enabled(False)` for "None". Adding calls `items.add` with
  `items.user_path`, or `sources.add` in the git worker. Checking for updates calls
  `sources.check`.
- Sync calls `adopt.adopt`, `layers.repair`, `sync.reapply` (which is
  `switch.use(action="refresh")`) and `items.set_enabled`.
- Each handler catches `FAILURES = (RespecError, OSError, RuntimeError, ValueError)`
  and redraws from disk.
- A refused add leaves `RESPEC_HOME` unchanged, verified with a file listing.
- Duplicate DOM ids cannot occur: a skill can belong to only one layer
  (`profiles.py:524`), and names are escaped.
- Moving the CLI wording into `messages.py` keeps the same lines in the same order,
  which settles review 1's N3.

## Blocking findings

None.

## Non-blocking findings

### N1. Sync cannot keep an edited copy while the active profile has a layer conflict

- Where: Sync's add path (`adopt.adopt`) and its "Repair layer" path
  (`layers.repair`, then a refresh of the active profile).
- Scenario: the active profile `work` has an exclusive layer with 2 enabled skills,
  and `~/.claude/skills/s1` is an edited or replaced copy.
  - Choosing **Add** for `s1` fails with "cannot adopt into profile 'work': layer
    'lay' … fix it with 'respec layer repair'". The whole run is refused, including
    the removes chosen alongside it.
  - **Repair layer** fails with "cannot refresh profile 'work': these entries are not
    managed … Resolve them with 'respec adopt'".
  - **Re-apply** fails with both messages.
  - Each error points to the other fix, so they form a loop.
- The only ways out are to choose **remove** for `s1` (it is backed up), or to edit
  `profile.yaml` by hand. Nothing is lost and nothing crashes; refusal and rollback
  work as specified.
- Impact: in this case, "add to the active profile" cannot be done from Sync. The
  rules causing it are 009's core rules; Sync only exposes them. It is rare, because
  the conflict has to come from a hand edit.
- Suggestion (fix-7 or later): let the repair disable skills without refreshing
  paths that do not change, or have Sync say "remove the entry or repair the layer by
  hand first".

### N2. Link rows for global skills blame the active profile

- Where: `sync.LinkProblem.describe`, for `NOT_LINKED` and `NOT_ENABLED`.
- Scenario: a global skill that is listed but has no folder shows "ghost
  (claude-code) is enabled in the active profile but not linked". A global skill
  that was removed from `config.yaml` shows "linked but no longer enabled in the
  active profile".
- Impact: this misleads about where to fix the problem. The Re-apply error does name
  `config.yaml` correctly.
- Suggestion: name the source ("global skill (config.yaml)" or "shipped skill") in
  these rows, and do not offer Re-apply when `_check_global` would refuse (answers
  (e)).

### N3. Smaller points

- Sync's summary says "The check failed; see above", but the log is shown below the
  summary.
- With unknown entries present, Sync still offers "Re-apply", which always fails
  (the error does say to resolve them first).
- When git starts, `_set_busy` focuses `#cancel-git`, but Pilot showed the focus on
  `#editor-log`. So `Enter` does not cancel; `Esc` and a click do.

## Guard denial

One ad hoc command was denied: _"Permission for this action was denied by the
Claude Code auto mode classifier. Reason: [Irreversible Local Destruction]."_ The
command deleted folders inside a temporary scratch home to simulate a global or
shipped skill source going missing. I stopped that action and did not retry it.
Instead I covered (e) with a global skill listed with no folder (nothing deleted)
and by reading the code.

## Scope

- Files changed: README, `cli.py` (wording moved to `messages.py`), `items.user_path`,
  `sources.py` (time limit and cancel), the one-wrapper `switch.plan`, the new
  `sync.py`, `tui.py`, and tests.
- Everything is in scope for 011 plus the engineer's Sync addition and review 1's
  fixes. The README matches the behaviour I observed.
