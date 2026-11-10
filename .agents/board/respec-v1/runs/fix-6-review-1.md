# fix-6 review 1: unknown-entry model v2

- Reviewer: fresh independent reviewer (did not implement)
- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-6`
- Diff: `f6296447b3fc3462d2cc8656b36e23a9cc4778bb..56ed20146bf103280e68f6909b4b6561625eedd0`
  (one commit, verified `HEAD == 56ed201`)
- Verdicts: spec-compliance **FAIL**, code-quality **FAIL**, tests-rerun **PASS**
- Blocking findings: 2 (B1, B2). Both are about partial results that are applied
  but not reported. No path deletes user content without a backup.

## Gates rerun (fresh, in the worktree, at head)

| Gate                                | Result                                    |
| ----------------------------------- | ----------------------------------------- |
| `uv run pytest -q`                  | 268 passed                                |
| `uv run black --check .`            | 28 files unchanged                        |
| `npx prettier@3 --check README.md`  | All matched files use Prettier code style |
| `uvx ruff check src --select F`     | All checks passed                         |
| `uv lock --check`                   | Resolved 28 packages                      |
| New tests vs base `src` (red check) | 59 failed + 14 errors, 195 passed         |

For the red check, I ran the head `tests/` against a `git archive` of base `src`
in the scratch dir. The new tests fail against the old code, which supports the
red-first claim. The tests are behavioural: they check disk, state and output,
and none of them assert on source text.

## Real-CLI scenarios (temp homes, `RESPEC_HOME` and `RESPEC_USER_HOME`)

TTY runs were driven through a Python `pty` harness.

1. **First takeover, non-TTY**: a `foo` folder already exists in
   `~/.claude/skills`, then `use a`. Result: exit 0, a full-folder takeover
   backup, `foo` left in place, and a warning on stderr with an `adopt` hint.
   PASS.
2. **Unrelated unknown entry**: with `foo` present, `add ./s2`,
   `disable s2 --json` and `enable s2` all succeed. Each prints a stderr warning,
   and the JSON output carries `warnings: [{name, path, kind, targets, replaced,
message}]`. Nothing was blocked. PASS.
3. **First takeover, TTY, no active profile**: only `remove` is offered, and
   `skip` is rejected. Both entries were backed up to a separate run, and the
   takeover run still holds the original. PASS (see N2 on the UX).
4. **TTY switch a->b, where b takes over `agents` and `agents/s2` sits at
   b's install path**:
   - Non-TTY: blocked, with an accurate message.
   - TTY: asked about `s2` (the blocker) and then `ext` (a takeover entry).
     `add` went to the outgoing profile `a` (criterion 3). PASS.
5. **Replaced copy of the active profile's `s1`**:
   - `disable s2` is blocked with "cannot apply this change to active profile
     'a' ... left unchanged".
   - `adopt --add s1` overwrote the profile copy with `EDITED` and relinked it
     (criterion 5). PASS.
   - `adopt --add stray` in the same home fails. See **B1**.
6. **Legacy `unmanaged` record**: the entry shows as unknown again, and the key
   is dropped on the next save. A TTY `restore` asked add/remove, added the entry
   to `a`, and restored the folder. PASS.
7. **TTY switch with a takeover add that clashes on name**: see **B2**.

## Blocking findings

### B1: `respec adopt --add <x>` reports a false failure when another unresolved entry remains

- **Location**: `src/respec/adopt.py` `link_added()` and `adopt()`, and
  `src/respec/cli.py` `adopt` (the `except RespecError` around
  `adopt_entries.adopt`).
- **Failing scenario**: profile `a` is active and its `s1` link was replaced by
  an edited folder. A stray folder `stray` also exists. Run
  `respec adopt --add stray` (non-interactive).
  - `resolve` copies `stray` into profile `a`, enables it, and deletes the
    original.
  - `link_added` then calls `switch.use(active)` with no handler. That raises
    `UnknownEntries` for `s1`.
  - The CLI prints
    `error: cannot switch to profile 'a': these entries ... sit where it would install or remove a skill: - .../s1`
    and exits 1.
- **Impact**:
  - The output never says that `stray` was added to profile `a` and removed
    from the folder. The message says "cannot switch", and the user did not ask
    for a switch. Criterion 2 requires misleading block messages to be replaced.
  - `stray` is now enabled in the profile but not linked, and `status` does not
    show it at all. The data is safe (it is in the profile), but the user is
    told the command failed while it applied part of its change.
- **Fix direction**:
  - Report the resolutions already applied (as `use` and `restore` do with
    `done=`).
  - Re-raise from `link_added` with an adopt-specific lead, for example "added
    to profile 'a' but not linked yet: ...". Or let `link_added` skip the
    relink, warn, and leave the entry for the next refresh.
  - Add a test that runs `adopt --add` on one entry while an edited copy is
    present.

### B2: a failure in the first-takeover prompt after a successful switch hides what was done

- **Location**: `src/respec/cli.py` `_ask_about_takeover()` (it calls
  `adopt_entries.resolve(...)` without `done=`) and its caller in `use`, where
  `_ask_about_takeover` is inside the same `try` as `switch.use`. The TUI
  `RespecApp._ask_about_takeover.chosen` has the same pattern: it calls
  `self._failed(error)` with no resolutions.
- **Failing scenario (reproduced)**: `a` (claude-code, skill `s1`) is active.
  Profile `b` targets claude-code and agents, and `~/.agents/skills` holds `aa`
  and `s1`. On a TTY, run `respec use b` and answer `aa: remove`, then
  `s1: add` (it clashes with `a`'s `s1`).
  - Output: only `error: profile 'a' already has a skill 's1'; ...`, with
    exit 1.
  - On disk, the switch to `b` completed, the agents takeover backup was made,
    and `aa` was backed up and removed.
  - None of "Backed up aa to ... and removed it", "Backed up agents folder to
    ..." or "Switched to profile 'b'" was printed.
  - Ctrl-C at the takeover prompt does the same: it prints "Aborted." with
    exit 1, although the switch succeeded and earlier removals happened.
- **Impact**: An entry is removed from the user's folder with no message saying
  so or naming the backup location. The engineer's requirement was that nothing
  is silently lost. The backup exists, but the user has to find it themselves.
  The command also reports failure for a switch that succeeded.
- **Fix direction**:
  - Pass `done=` from `_ask_about_takeover`.
  - Move the takeover step out of the switch's `try`, so the switch summary is
    always printed.
  - Report a takeover-resolution error as a warning or a separate error after
    the summary. Handle `typer.Abort` the same way.
  - Mirror this in the TUI with `_failed(error, resolved)`.

## Non-blocking findings

- **N1: `--unknown` on a terminal also resolves every takeover entry.**
  - Location: `cli.py` `use`: `ask = decide or ...` is passed to
    `_ask_about_takeover`.
  - Scenario: on a TTY, `respec use b --unknown remove` backs up and removes
    every entry already in a newly owned folder. The same command off a TTY
    only warns.
  - The `--unknown` help ("where this switch installs or removes a skill") and
    the README do not say this. The data is backed up, but the same flags
    behave differently depending on the terminal.
  - Either document it, or limit `--unknown` to the blockers and always prompt
    for takeover entries.
- **N2: the first-ever `use` on a TTY forces `remove` for every existing
  entry.**
  - No profile is active, so criterion 3 allows only remove. The prompt does not
    accept a "leave for now" answer, so Ctrl-C is the only way out (and see B2).
  - This follows the spec as written. Raise it with the engineer, because a
    user with many hand-installed skills is pushed to remove them all at
    onboarding. A skip answer that leaves the entry unknown and warns would
    still match "not untracked".
- **N3: the restore overwrite confirm is effectively dead code** (question d).
  - Location: `cli.py` `restore`, at
    `except RestoreBlocked ... typer.confirm("Back these up and overwrite them?")`.
  - On a TTY without `--overwrite`, every conflict goes through
    `_prompt_choice`, which never returns `None`. With `--unknown`, the policy
    resolves everything, and with `--overwrite` the restore never blocks.
  - It is reachable only when an entry appears between the prompt and the
    re-check (a race). This is not a missing path: `--overwrite` is the
    documented non-interactive route, and the README no longer mentions "a yes
    in a terminal".
  - Remove it, or comment it as a race fallback.
- **N4: criterion 5's overwrite discards the profile's previous copy with no
  backup.**
  - Location: `adopt._overwrite` calls `shutil.rmtree(retired)`.
  - The output still says "Added ... to profile 'a'" rather than saying it
    replaced the profile's copy.
  - This matches the engineer's "overwrites" wording. For local (unsourced)
    skills, though, the old version is unrecoverable. Consider moving `retired`
    into a backup run and saying "replaced".
- **N5: one-time effect of the digest change.**
  - `unknown.digest` now skips `.DS_Store`. Copy installs that were recorded
    under fix-1 while the profile's folder held a `.DS_Store` will no longer
    match their stored digest. They become "edited or replaced" and block
    refreshes until the user adopts them.
  - This is rare: it needs copy mode plus a Finder-touched profile folder. It
    is data-safe.
  - On the restore side the change is conservative. A 005 manifest digest
    mismatch only restores more, and `_modes` still lists `.DS_Store`, so
    `_same` stays strict.
  - The 005 manifest and fix-1 digests are otherwise still honored.
- **N6: no up-front check on `restore --unknown add` without an active
  profile.**
  - `use` checks this up front. `restore` instead fails at the first `add`
    inside `on_unknown`, with nothing changed (all entries are `add`), so it is
    safe.
- **N7: core API for a TUI "Sync" action** (question e). It is usable:
  `unresolved()`, then `choices(active)`, then `resolve(..., active, done=)`,
  then `link_added()`. Rough edges:
  - `link_added` surfaces `UnknownEntries` with switch wording (B1).
  - `adopt()` loses its partial `resolved` list on error.
  - The takeover-entry filter (`set(entry.targets) & set(result.backups)`) is
    duplicated in `cli.py` and `tui.py`. It belongs in `adopt` (for example
    `adopt.taken_over(result)`).
  - `done` as an out-parameter works but is awkward. Returning partial results
    on an exception attribute would be cleaner.

## Specific questions

- **(a) Data safety.**
  - `remove` always copies to a backup run before `_delete`.
  - `add` copies into the profile, or overwrites the profile's copy through a
    staged swap, before deleting.
  - `switch.use` no longer drops records of replaced paths: recorded,
    replaced paths are conflicts and block before removal.
  - `remove_installed` still skips unmanaged paths.
  - A takeover backup is taken before any resolution, so `restore` gets the
    exact original folder (verified in scenario 3).
  - I found no path that deletes user content without a backup. The gaps are
    in reporting (B1, B2) and the profile-copy overwrite (N4).
- **(b) `-p` removed from `adopt` and `restore`.** This is consistent with
  criteria 1 and 3: add always targets the active profile. Restore's documented
  uses (`<backup>`, `--list`, `--unknown`, `--overwrite`) are intact. README
  usage and help no longer mention `-p` for either command, and there is no
  "item" in the help of `adopt`, `restore` or `use`.
- **(c) An edited copy blocks refreshes of the active profile.** This is
  consistent with criterion 2. A refresh is implemented as a full re-apply, so
  respec really would remove that recorded path and install to it. The block
  names the path and `respec adopt`. The cost is that an edit to `s1` blocks
  `disable s2`. A finer-grained refresh could avoid that, but it is outside
  this scope. It is rare, because symlink mode writes edits straight into the
  profile.
- **(d) Restore confirm.** Effectively unreachable (N3).
- **(e) Core API.** See N7.
- **(f) Scenarios.** See above.

## Collision with fix-5's shared `warnings` field (must address at rebase)

- fix-5 (`a50e03d`) changes `cli._print_json` so that every dict gets
  `data = {**data, "warnings": [conflict.to_dict() ...]}`.
- This branch builds `{**change.to_dict(), "warnings": unknown_warnings}` and
  then calls `_print_json`. After the rebase, fix-5's spread runs last and
  **silently replaces the unknown-entry warnings with the layer conflicts**,
  and the existing fix-6 tests that assert JSON `warnings` would break.
- The element shapes also differ:
  - fix-5: `{profile, layer, skills, message, fix}`
  - fix-6: `{name, path, kind, targets, replaced, message}`. Here `kind` means
    folder, file or symlink, not a warning type.
- Both sides also print to stderr: fix-5 through `call_on_close`, fix-6 inline.
- At rebase:
  - Merge both lists in one place (`_print_json`).
  - Add a discriminator such as `"type": "layer-conflict" | "unknown-entry"`.
  - Decide whether every JSON command, including `status`, `adopt` and
    `restore`, carries unknown-entry warnings, as fix-5 does for layer
    warnings.
