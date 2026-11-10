# t004 review 1: unknown-entry detection and adopt

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/t004`
- Diff: `51360971f75febdccd61baab22dd4b977eee298e..64e9ba57907643c43ca513cef5c95e8c12e81a33`
  (one commit, `64e9ba5`; HEAD verified, working tree clean)
- Inputs: ticket 004, spec (decisions 3, 5, 6), run reports t004-impl-1 and
  t004-impl-2. No AGENTS.md, CONTEXT.md or decision records exist in the worktree.

## Verdicts

- spec-compliance: PASS
- code-quality: PASS (non-blocking findings below)
- tests-rerun: PASS

## Gates rerun (fresh, in the worktree)

- `uv run pytest -q`: `110 passed in 3.08s`
- `uv run black --check .`: `21 files would be left unchanged.`
- `npx prettier@3 --check README.md`: `All matched files use Prettier code style!`
- CLI smoke runs in scratch homes (`RESPEC_HOME`, `RESPEC_USER_HOME`) to check the
  scenarios below. One Python script checked the copy-mode case.

## Acceptance criteria evidence

| Criterion                                              | Verdict | Evidence                                                                                                                                                                         |
| ------------------------------------------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unknown entries reported by `status` and `--json`      | Met     | `unknown.folder_report` feeds `switch.status`. Tests in `tests/test_adopt.py` cover detection. Smoke run: `old  unknown folder` plus the adopt hint.                             |
| Prompt per entry before a switch, 3 choices, no silent | Met     | `switch.use` raises `UnknownEntries` without a handler. `cli.use` prompts on a TTY, `--unknown` sets a policy, and non-TTY or `--json` runs stop. Tests cover all three choices. |
| `respec adopt` with `--json` and per-entry flags       | Met     | `--add/--backup/--keep` (repeatable), `--all`, `-p`, `--json`. Unmatched selectors fail before any change.                                                                       |
| Nothing removed without adoption or backup             | Met     | Within the adopt flow, a copy is made before the original is removed. Copy mode has a gap outside this diff: see F1.                                                             |

## Investigation answers

(a) Data safety. `adopt._add` copies through `items.add_local`, which raises
before deleting on a bad name, an existing item, a non-folder or a missing
SKILL.md. Only then does `_delete` remove the original. `_backup` copies first,
cleans up a partial copy and raises if the copy fails, and only then deletes. For
a symlink entry, only the link is removed. Backup runs use `_new_backup_run`
(exclusive `mkdir`, then `-N`). I confirmed the uniqueness in a smoke run: an
adopt backup taken in the same second as the takeover backup went to
`20261109T215955Z-2`. The test `test_backups_taken_in_the_same_second_do_not_collide`
also passes. A separate, existing gap is described in F1.

(b) Pre-existing entries become unknown after the first takeover. This is
consistent with the spec. Decision 6 backs up the folder but does not empty it.
Decision 5 makes any entry respec did not create unknown in an owned folder. The
first `use` does not ask, because the folder is not owned yet, and the backup
already protects the data. The three test edits are legitimate behavior updates,
not weakened tests:

- `test_folder_is_backed_up_only_on_first_takeover` still asserts that there is
  exactly one backup run with the original contents. `--unknown keep` creates no
  extra run, so the assertion still has meaning.
- `test_backups_taken_in_the_same_second_do_not_collide` still asserts two
  distinct runs with the exact contents. `on_unknown=lambda e: None` leaves the
  entry in place and adds no backup.
- `test_switch_only_removes_recorded_paths_and_keeps_profile_folders` still
  asserts that the foreign folder survives byte for byte. `keep` is the only
  choice that leaves the entry in place, so it is the right choice for this test.

The status JSON test only gains the three new keys. Whether the first takeover
should also ask is listed under open design.

(c) Blocking refresh. The block is safe and consistent with the spec: a refresh
is a switch (`items._refresh` calls `switch.use`), and the rollback works. In a
smoke run, `respec add` failed, profile.yaml was restored and the copied folder
was removed. The UX cost is real, though. Right after the first `respec use` on a
machine with existing skills, every `add/enable/disable/remove/layer ...` fails
until `respec adopt` runs (smoke run: `old` blocked `respec add` immediately). The
refresh is the only path with no prompt and no `--unknown` option. The error hint
points to `respec use --unknown`, which does not help an `add` user much.
Non-colliding unknown entries are not at risk during a refresh, because preflight
already blocks collisions. Blocking there is therefore a policy choice rather
than a safety need: see open design.

(d) Dotfiles. Ignoring them is safe for data, because respec only removes
recorded paths, so a hidden entry is never deleted. It is a small isolation gap:
a hidden skill folder that some harness loads would leak across profiles and
never be reported. Neither the README nor `status` says that hidden entries are
skipped. Minor, see F5.

(e) `add` during `use` copies into the profile being activated. This is
defensible. The prompt names that profile (`add to profile 'b'`), the README says
so, and it is the only profile whose install relinks the entry right away. Spec
decision 5 does not say which profile. See open design.

(f) Orchestrator fixes. All verified:

- A replaced recorded link is flagged `replaced` (`unknown.is_managed` requires a
  symlink into the profiles folder). `switch.use` raises `UnknownEntries`, a
  `SwitchBlocked`, before anything changes. `items._refresh` rolls the change
  back. `_forget_replaced` drops stale records after a handler runs, so preflight
  blocks instead of `_install` hitting `FileExistsError` mid-switch. Both tests
  pass.
- `add_local(..., name=)` keeps the entry name. A symlinked entry `alias -> x` is
  adopted as `alias`. The test passes.
- `status` aliases: `same_as`, with items listed once under the first target in
  registry order. Two tests pass.

(g) Rebase against 008. `layers._apply` goes through `items.commit` and then
`_refresh`, so layer commands on the active profile are blocked and rolled back.
The parametrized test covers `layer use` and `layer disable`. Every other
mutating layer path (`layers.add` and `layers.remove` save directly) does not
refresh. It changes no installs, so it needs no block. 008's preflight test still
passes. No conflict artifacts remain. The README places the unknown-entries text
before `### Layers`.

## Findings

All findings are non-blocking.

### F1 (major, existing behavior outside this diff): a copy-mode item replaced by a foreign folder is deleted without a backup

- Location: `src/respec/unknown.py` `is_managed` (copy branch: `os.path.lexists`)
  and `src/respec/switch.py` `_remove` (`shutil.rmtree` for `mode == "copy"`).
- Failing scenario: the symlink fails, so profile `a` installs `tdd` as a copy.
  Another tool then replaces `~/.claude/skills/tdd` with its own folder, and the
  user runs `respec use b`. The reproduction script printed
  `tdd exists after switch: False backups: None`: the user's content was deleted,
  with no prompt and no backup.
- Impact: this contradicts the acceptance criterion "Nothing is removed without
  being adopted or backed up" and the claim in the `unknown` and `adopt`
  docstrings. It only happens on the copy fallback, which is rare on macOS and
  Linux, and the code dates from ticket 002. The docstring documents the
  limitation ("a recorded copy must still exist").
- Suggested fix: back up copy-mode items into a backup run before `_remove`
  deletes them. That is cheap and needs no fingerprint. Alternatively, record a
  content hash at install time and treat a mismatch as `replaced`.

### F2 (minor): `use --json` failure after resolutions prints human text on stdout

- Location: `src/respec/cli.py` `use`, the `except RespecError` branch calls
  `_report_resolution` regardless of `as_json`.
- Failing scenario: `respec use b --unknown keep --json` while a foreign `lint`
  occupies b's install path. stdout was
  `Kept .../lint unmanaged` (not JSON), with the error on stderr and exit 1.
  `--unknown backup` hits the same path whenever preflight still blocks
  afterwards.
- Impact: agents parsing `--json` get invalid JSON and lose the
  machine-readable record of what was already backed up, removed or added
  (including backup paths).

### F3 (minor): resolutions persist when the switch is then refused, and `keep` cannot be undone through the CLI

- Location: `src/respec/switch.py` `use` (the handler runs before `_preflight`)
  and `src/respec/adopt.py` `_settle` (adds to `state.unmanaged`). There is no
  inverse command.
- Failing scenario: in the same run as F2, `keep` was saved to `state.unmanaged`
  although the switch failed. `respec adopt --json` then lists nothing, and
  `respec adopt --backup lint` fails with `no unknown entry matches 'lint'`.
  Preflight keeps saying "move it out of the way", so the user has to move the
  folder by hand.
- Impact: no data loss, but the documented resolution tool cannot reach kept
  entries. A `keep` that collides with the target profile can never let the
  switch succeed. Consider checking for collisions before applying choices, or
  letting `adopt` re-select kept entries.

### F4 (minor): stale `state.unmanaged` paths are never pruned

- Location: `src/respec/unknown.py` `find_unknown` (`kept` skips the path
  outright). `folder_report` only hides paths that no longer exist.
- Failing scenario: the user keeps `foo` and later deletes it. A different
  foreign `foo` appears at that path and is never reported or asked about.
- Impact: low. The entry is never removed, so it is only a reporting gap.

### F5 (minor): skipping hidden entries is undocumented

- Location: `src/respec/unknown.py` `find_unknown` (`entry.name.startswith(".")`).
- Impact: a hidden skill folder would leak across profiles without being
  reported. Mention it in the README, or limit the skip to known noise such as
  `.DS_Store`.

### F6 (UX, minor): the refresh block hint does not fit item and layer commands

- Location: the `UnknownEntries` message in `src/respec/switch.py`, wrapped by
  `items._refresh`.
- Scenario: `respec add ./x` fails, and the message suggests
  `pass '--unknown add|backup|keep' to 'respec use'`. That is not an option of
  `add`. The user has to switch to `respec adopt`.

## Scope

The diff stays within the ticket (detection, the switch hook, adopt, status,
README, tests). There is no TUI work. CLI behavior for `--home` and
`RESPEC_USER_HOME` is unchanged.

## Open design (for the engineer)

1. Should item and layer refreshes block on non-colliding unknown entries, or
   only `respec use`? (Preflight already protects collisions.)
2. Should the first takeover ask about pre-existing entries right away, instead
   of at the next switch or refresh?
3. Should `add` during `use` target the profile being activated (current
   behavior) or the previously active one?
4. Should hidden entries be skipped? See F5.
5. How should copy-mode items be protected from replacement? See F1.
