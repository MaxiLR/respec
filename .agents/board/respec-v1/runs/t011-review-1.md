# t011 review 1

- Reviewer: fresh independent reviewer (did not implement)
- Range: `b8d1aee671ac7efa848c1f2992f610117fdd824f..3b62e957eb5c88969a306bfed07ac6924dfc21db`
  (worktree `/Users/maxilr/Documents/GitHub/respec-worktrees/t011`)
- Inputs: ticket 011, the engineer's Sync addition (ledger line 216), the spec, and
  `runs/t011-impl-1.md`, treated as claims to verify

## Verdicts

- spec-compliance: **FAIL**. B1: Sync breaks as soon as it merges with 009.
- code-quality: **FAIL**. B1 comes from a private-API seam. B2: the TUI crashes on
  one kind of typed input.
- tests-rerun: **PASS**

## Gates rerun (fresh, at 3b62e95, clean tree)

| Gate                             | Result                                             |
| -------------------------------- | -------------------------------------------------- |
| `uv sync --frozen`               | Audited 27 packages                                |
| `uv run pytest -q`               | 373 passed in 96.81s                               |
| `uv run black --check .`         | 32 files would be left unchanged                   |
| `npx prettier --check README.md` | All matched files use Prettier code style          |
| Scratch merge with 009 `5dc0cd1` | Clean textual merge; 29/29 TUI tests pass (see B1) |

## Blocking findings

### B1. Sync is never "in sync" once 009 lands (private `switch._plan` seam)

- Location: `src/respec/sync.py` `_link_problems`. The `expected` set comes from
  `switch._plan(active, user_home)`.
- Scenario: I made a scratch merge of 3b62e95 with 009 head `5dc0cd1`. The merge
  was clean. In it I created profile `work` with skill `alpha` and ran
  `switch.use`. The switch installed `alpha` plus the shipped `respec` and
  `profile-maker` skills into all 3 targets. `sync.check` then returned
  `clean: False` with 6 problems of the form
  `respec (claude-code) is linked but no longer enabled in the active profile`.
  After `sync.reapply` there were still 6 problems.
- Cause: 009 adds `switch._plan_all` (profile skills, global skills from
  `config.yaml`, and shipped skills in every registered target). `use`,
  `conflicts` and `_take_over` now use it. `sync.py` still calls the
  profile-only `_plan`, so every global or shipped install falls into
  `NOT_ENABLED`.
- Why the tests miss it: 009's autouse `shipped_skills` fixture turns shipped
  skills off, so the 011 tests still pass on the merge.
- Impact: on a real install, Sync can never say "all in sync". It always offers a
  "Re-apply" that changes nothing. This breaks the engineer's requirement that
  Sync show "all in sync" when the setup is clean.
- Verdict on (a): calling the private `_plan` is not acceptable. Add a public
  seam in `switch.py` that returns everything a switch installs, for example
  `switch.plan(respec_home, user_home, profile)` wrapping `_plan_all`. Have
  `sync` use it, and add a test with shipped or global skills enabled. This has
  to happen at the 009/011 integration, whichever merges second. Otherwise
  fix-7 should own it, but the integration must not be called green before
  then.

### B2. A `~user` path in "Add folder" crashes the TUI

- Location: `src/respec/tui.py` `ProfileScreen._ask_to_add.chosen`, which calls
  `Path(text).expanduser()`. Only `RespecError` is caught.
- Scenario (ad hoc Pilot): open the editor, press `a`, enter
  `~nosuchuser_zz/skill`, then Add. `pathlib` raises
  `RuntimeError: Could not determine home directory.` The app exits with
  `return_code 1` and prints a traceback.
- Impact: a typo in the folder path crashes the whole TUI, which breaks
  requirement (d), "errors are shown, not crashes". `items.add_local` has the
  same `expanduser`, so `respec add ~nosuchuser/x` also tracebacks in the CLI.
  That part predates this ticket and could go to fix-7. The TUI should catch
  `RuntimeError` (and `OSError`) around the add and show it as an error.

## Non-blocking findings

### N1. Git blocks the UI with no cancel and no timeout (answer to c)

- Location: `ProfileScreen.action_check_updates` and `_ask_to_add` (git branch).
  Both call `sources.check` and `sources.add` synchronously on the event loop.
  `sources._git` runs `subprocess.run` with no `timeout`.
- Measured:
  - An unresolvable host fails in 0.7s and shows a clean error.
  - Against a local server that accepts TCP and never replies
    (`http://127.0.0.1:18765/x.git`), "Add from git" froze the TUI until my
    40s kill.
  - A bare `git ls-remote` against the same server was still waiting at 20s
    (`rc=124`).
- Why it can hang: fix-4 only stops prompts (`GIT_TERMINAL_PROMPT=0`, BatchMode
  ssh, closed stdin). It sets no `http.lowSpeedLimit`/`lowSpeedTime` and no ssh
  `ConnectTimeout`. A blackholed network, captive portal or stalled server
  therefore hangs for minutes or indefinitely.
- No way to cancel: the event loop is blocked, so the TUI draws nothing (not even
  a "checking…" line), and Textual's raw mode means Ctrl+C sends no SIGINT. The
  only way out is to kill the process from elsewhere, which can leave the
  terminal in raw mode.
- With no network at all, DNS fails fast, so the common offline case is fine.
- Judgement: a real defect, but outside the written acceptance criteria and
  disclosed by the implementer. I accept it for v1 only if it is tracked.
  Recommended fix: run git in a Textual thread worker with a busy state and a
  Cancel button, and give git timeouts in `sources._git`
  (`-c http.lowSpeedLimit=1 -c http.lowSpeedTime=30`,
  `ssh -o ConnectTimeout=15`, and a `subprocess` timeout).

### N2. "Re-apply" can never fix a broken link

- Location: `SyncScreen._link_section` and `_relink`.
- Scenario: delete the folder of an enabled skill in the profile. Sync reports
  `s2 … is a broken link (its skill folder is gone)` and offers
  "Re-apply profile work". Re-apply fails:
  `cannot refresh profile 'work': skill 's2' has no folder at …`. The problem
  stays, and Sync offers no other fix.
- Impact: Sync detects the problem, as required, but the only button it offers
  always fails. Offer "disable s2" (`items.set_enabled`) or say what to do.

### N3. Message formatting is duplicated in the TUI

- Location: `_skill_change_lines`, `_layer_change_lines` and the source-add lines
  in `tui.py`. They copy `cli.py` (lines ~574, ~642, ~716-725) word for word.
- Impact: the wording can drift, as already happened in 010. Add this to fix-7's
  duplicate-helper cleanup.

### N4. Smaller points

- `e` with no profile selected says "Select a profile to edit first". The active
  profile is not selected on launch, so `e` right after start does nothing
  useful.
- `profiles.create_profile` raises `OSError` from `mkdir` (for example a
  read-only `RESPEC_HOME`), which the dialog does not catch.
- `SyncScreen` keys choices by entry path. If an entry is replaced between the
  check and "Resolve chosen", the old choice applies to the new entry. This is
  acceptable for a manual check.
- The editor has no remove-skill or layer on/off controls; the CLI covers them,
  and the implementer disclosed this.

## Investigation results

(a) Core paths. Editing calls `items.set_enabled`, `layers.use`,
`layers.set_enabled(False)`, `items.add`, `sources.add` and `sources.check`.
Sync calls `adopt.adopt` (not bare `resolve`), `layers.repair(keep=)` and
`switch.use(action="refresh")`. All of these are the CLI's own functions, with
their refusals and rollback. A refused toggle redraws from disk, so the switch
snaps back. Logic is not duplicated apart from the display text (N3). The
private `_plan` call is not acceptable, and it collides with 009 (B1).

(b) Sync, covered by the implementer's Pilot tests and by my own ad hoc Pilot runs
in temp homes:

- Unknown entry: add (implementer test) and remove with backup path in the log
  (test). With no active profile, only "Back up and remove" is offered.
- Edited copy: labelled "edited or replaced copy". Add replaced the profile copy;
  the log gives the backup path of the previous copy. Afterwards it shows "All
  in sync", the link is restored, and the profile holds the edited content.
- Layer conflict, including one in an inactive profile: repair keeps the chosen
  skill and logs it.
- Broken and missing links are detected. Missing is relinked; broken is not
  fixable (N2).
- Refused add on a conflicted profile: one entry chosen "add" and one "remove".
  The log shows the `cannot adopt into profile 'work'` refusal. A file listing of
  `RESPEC_HOME` was identical before and after, and the entry chosen for removal
  was still there. Nothing changed.
- "All in sync" appears with a clean profile and with no profiles at all.
- Long lists: 30 unknown entries, all removed in one run. The log held all 30
  lines and the body scrolled (`max_scroll_y` 123), and the summary showed "All
  in sync". Neither result area keeps the old 6-line cap: the Sync log scrolls,
  and the editor log has `max-height: 8` and scrolls.
- Sync is manual: `test_sync_does_not_watch_the_folders_by_itself`. There is no
  timer or watcher in the code.

(c) See N1.

(d) Errors from core functions (`RespecError`) are shown in place: an invalid
profile name in New profile, a bad git host, an add of a folder that is not a
skill, refusals, and a failed check. Exception: B2. `cli.py` is untouched, so
non-TTY behaviour is unchanged.

(e) The TUI's source and rendered screens contain no user-facing "item". I grepped
`tui.py` strings and a rendered Sync SVG.

## Scope

The diff touches `README.md`, the new `sync.py`, `tui.py` and two new test files.
`switch.py` is untouched. The README additions match the behaviour.
