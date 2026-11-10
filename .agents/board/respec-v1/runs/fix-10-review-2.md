# fix-10 review 2: `respec profile remove` (fix round 1)

- Reviewer: fresh and independent. I did not implement this work.
- Diff: `4092c83fc1d41bd68a9cc763b1fe36694b5d0f00..b25f79c038fdd021c4ce3718aa06001c74e57c92`
  (focus `b3b1fb3..b25f79c`)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-10`. It was
  clean before and after the review.
- Verdicts: spec-compliance **PASS**, code-quality **PASS**, tests-rerun
  **PASS**. Nothing is blocking.
- Every manual run used the real CLI (`.venv/bin/respec`) with temp homes under
  the session scratchpad (`RESPEC_USER_HOME` / `RESPEC_HOME`). The volume is
  APFS and case-insensitive. No guard denials occurred.

## Gates rerun (fresh, in the worktree)

- `uv sync --frozen`: ok. `uv lock --check`: `Resolved 28 packages`.
- `uv run black --check .`: `45 files would be left unchanged.`
- `npx --yes prettier@3.3.3 --check README.md src/respec/shipped/respec/SKILL.md src/respec/shipped/profile-maker/SKILL.md src/respec/targets.yaml`:
  `All matched files use Prettier code style!`
- `uv run pytest -q -p no:cacheprovider`: `589 passed in 209.18s`. The two
  real-filesystem case tests ran; they were not skipped.

## B1 (blocking in review 1): fixed

These commands ran in a temp home:
`profile new work -t claude-code; add <tdd> -p work; use work`.

- `profile remove WORK` exits 1 with
  `profile 'WORK' does not exist (names are case-sensitive; did you mean 'work'?)`.
- `profile remove Work --json` exits 1 and returns `{name, error, warnings}`.
- `profile remove work` exits 1 with the "is active" refusal.
- After all three, `profiles/work` and the `~/.claude/skills/tdd` link are
  intact, no `removed-profiles/` exists, and `status` still reports
  `Active profile: work`.
- Legacy state: I used the base code (`git archive 4092c83`) to run
  `use WORK`, which recorded `active_profile: "WORK"`. With the new code,
  `profile remove work` is still refused as active (the `samefile` branch).
  `status` still works. `add` without `-p` fails with the clear did-you-mean
  message. `use other` cleans up and switches normally. I found no data loss.

## Regression matrix: `load_profile` now rejects case variants

**Exact mixed-case name.** I created the profile as `Work`. Every command
below exited 0 and did the expected thing:

- `profile show Work`
- `add <local> -p Work`
- `add git://…/gitsrc.git -p Work`, using a local `git daemon` on 127.0.0.1
- `use Work`
- `add` without `-p`, which targets the active `Work`
- `enable` / `disable` / `remove lint -p Work`
- `layer add grp --exclusive -d … -p Work`, then `add-skill`, `use`,
  `disable`, `repair`, `off`, `on`, `remove-skill` and `rm`. `layer enable`
  on an exclusive layer gave its usual, unrelated refusal.
- `update --check -p Work` and `update -p Work`. After I pushed a v2 commit,
  `update` reported `updated 26d8106763da -> b2530eae3528`, and the linked
  file showed v2.
- `adopt --add stray` into the active `Work`
- `profile install git://…/profrepo.git --name Remote`, then
  `profile show Remote` and `use Remote`
- `profile remove Work` after switching away. The profile moved to
  `removed-profiles/<run>/Work`.

**Case variants.** I tried `work`, `WORK` and `wORK` with `use`,
`profile show`, `add -p`, `enable -p`, `disable -p`, `remove -p`,
`layer add -p`, `layer enable -p`, `layer rm -p`, `update -p`,
`update --check -p` and `profile remove`. Each exits 1 with
`profile '<v>' does not exist (names are case-sensitive; did you mean 'Work'?)`.
`profile show remote` reports `did you mean 'Remote'?`. Nothing changed in
any of these runs.

**Creation commands.** `profile new work` / `WORK` and
`profile install … --name REMOTE` / `wOrK` are refused when a case variant
exists, because their exists checks fold case. This is unchanged behavior.

**TUI.** I ran a headless pilot of the real `RespecApp` with profiles `Work`
(active), `Spare` and `Other`:

- `#remove` is disabled for `Work`.
- Pressing `d` on `Work` shows the refusal and opens no dialog.
- On `Spare`, Remove is enabled, and confirming moves the profile to
  `removed-profiles/<run>/Spare`.
- After I activated `Other`, `Work`'s Remove is enabled.
- Edit opens `ProfileScreen` for `Work`.

The TUI only passes exact names from `list_profile_names`.

I checked the code for other lookups. Every name-based lookup goes through
`profiles.load_profile` / `existing_folder`: `items`, `layers`, `sources`,
`switch`, `adopt`, `journal`, `tui`, `sync` and `cli`. `sync`, `tui` and
`cli list` iterate the exact listed names. Names are ASCII-only
(`NAME_PATTERN`), so Unicode normalization differences on APFS/HFS+ cannot
affect the `name in os.listdir(...)` check.

## Prior non-blocking findings

- **N1, linked profile: fixed.** I ran `use work`, emptied `state.json`, and
  ran `recover`, which rebuilt the state with no active profile. Then
  `profile remove work` (text and `--json`) exits 1, names
  `~/.claude/skills/tdd`, and the link still resolves. After `use spare`, the
  removal succeeds. On the top-level-only scan: respec creates exactly one
  entry per skill at the top level of each target's skills folder, and a
  skill is a whole folder link. A link nested deeper would have to be one the
  user made inside a real folder. It is not a respec link, `use`/`restore`
  would not manage it either, and the profile is still recoverable from
  `removed-profiles/`. Scanning only the top level is the right scope.
  Following nested links would add cost and false positives, such as user
  repos that contain links. I judge this not to matter.
- **N2, TUI: fixed.** See the TUI section above. The test in `test_tui.py`
  asserts the disabled button, the missing dialog, and that the button is
  enabled for `beta`.
- **N3, wording: fixed in the refusal, with a small remainder.** The error is
  now "cannot remove profile 'spare' while an interrupted change waits;
  nothing was changed. … then remove the profile." See N5 below.
- **N4, empty runs: fixed.** A real SIGKILL at `profile-remove:move` left an
  empty `removed-profiles/20261110T155238Z/`. The next `profile remove other`
  reused the slot and left no empty folders. A SIGKILL at
  `profile-remove:moved` left the backup complete and `status` working.
  `_drop_empty_runs` only `rmdir`s, under the lock, and never deletes
  content.

## Non-blocking findings (new)

### N5. The interrupted-operation warning that accompanies the refusal still says the command would finish the change

- Location: the pre-existing `journal.pending_message`
  (`src/respec/journal.py:197-205`), which `profile remove` still emits as its
  `warnings[0].message` (JSON) and its stderr `warning:` line (text).
- Scenario: SIGKILL `use other` at `use:begin`, then run
  `profile remove spare --json`. The `error` is correct, but
  `warnings[0].message` ends with "any respec command that changes skills
  finishes it first." That contradicts the refusal in the same output.
- Impact: cosmetic and confusing, with no behavior change. A fix would either
  suppress the generic warning for this command or reword it.

### N6. The "already exists" message for a case variant names a path that is not on disk

- Location: `profiles.create_profile` / `sources.install_profile`, which are
  outside this diff and pre-existing.
- Scenario: with `Work` on disk, `profile new work` reports
  "already exists at …/profiles/work".
- Impact: cosmetic, and it now differs from the did-you-mean style the rest
  of the CLI uses. This is optional follow-up work, not part of fix-10.

## Acceptance criteria

1. Refuses the active profile: yes, for the exact name, a case variant
   (refused as unknown), and a legacy case-variant active state (`samefile`).
2. Never hard-deletes: the profile is moved to
   `removed-profiles/<run>/<name>` and the path is printed. I moved one back
   by hand and it worked in review 1. Re-observed here.
3. Lock, pending journal and crash safety: re-observed the pending refusal,
   the SIGKILL at move/moved, and empty-run cleanup. The lock refusal is
   covered by `BUSY_SHAPES` and passing tests, and it is unchanged since
   review 1.
4. Name validation, including case: yes, see the matrix.
5. TUI delete with confirmation, disabled for the active profile: yes.
6. Docs, help test and JSON contract: README and SKILL.md cover the
   linked-profile refusal, case-sensitive names, that `restore` never brings
   a profile back, no pruning, and empty-folder cleanup. The JSON contract
   tests cover the success, failure and busy shapes.
7. Vocabulary: no "item(s)" in the added lines. The text says "skills".

## Tests and quality

The new tests check observable behavior: real filesystem case tests, which
skip only when the filesystem is case-sensitive, a monkeypatched
case-folding `is_dir` so the case check runs on any filesystem, a real
recover/rebuild for N1, and a real SIGKILL for N4. None of them assert on
source text. One weak spot: the N3 test only checks for the absence of
"finishes it first" in `error`, so it does not catch N5. The code is small
and well scoped. `remove_profile` gained an optional `user_home` argument,
and both callers pass it. There is no unrelated churn.
