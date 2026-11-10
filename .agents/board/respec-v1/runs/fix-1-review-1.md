# fix-1 review 1 (fresh, independent)

- Worktree: `/Users/maxilr/Documents/GitHub/respec-worktrees/fix-1`
- Diff: `60224c7af58897549aac1253b7a49996833c1733..ba249cd6201ee01409bb2c7f4ecb8349c8ba8c3a`
  (one commit: README, `state.py`, `switch.py`, `unknown.py`, `tests/test_adopt.py`)
- Verdicts: spec-compliance PASS, code-quality PASS, tests-rerun PASS
- Blocking findings: 0

## Gates rerun (in the worktree, at ba249cd, clean tree)

| Gate                               | Result                                     |
| ---------------------------------- | ------------------------------------------ |
| `uv run pytest -q`                 | 114 passed                                 |
| `uv run black --check src tests`   | 21 files would be left unchanged           |
| `npx prettier@3 --check README.md` | All matched files use Prettier code style! |
| `git diff --check 60224c7 ba249cd` | clean                                      |

## Criterion 4: regression tests against 60224c7

I extracted 60224c7 with `git archive` into the scratch area
(`/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/rev-fix1`).
I replaced only `tests/test_adopt.py` with the ba249cd version and ran
`pytest tests/test_adopt.py -k copy`. Result: 3 failed, 1 passed.

- `test_replaced_copy_is_reported_as_unknown_not_as_managed`: `items` lists `tdd` as `copy`.
- `test_replaced_copy_blocks_switch_and_is_not_deleted`: `use b` exits 0, so the foreign content is deleted.
- `test_edited_copy_is_backed_up_before_the_switch_removes_it`: backups are `{}`.
- `test_unmodified_copy_stays_managed_and_is_replaced_on_switch` passes on the base. This is expected because it guards criterion 3.

All four pass at ba249cd. Criterion 4 is confirmed.

## Acceptance criteria

1. PASS. A copy that was edited or replaced fails `is_managed`, because its digest differs. `find_unknown` then reports it as `replaced`. A non-interactive `use` refuses, and `--unknown backup` copies it into backups before deleting it. `_remove` also checks `is_managed` again, so even a path that skipped the unknown flow is left alone and not deleted.
2. PASS. `status` filters `items` through `is_managed`, so the test shows `items == []` and `tdd` under unknown with `replaced: true`.
3. PASS. Both the new test and the existing `test_switch_removes_copied_items_too` cover this.
4. PASS. See above.
5. PASS. The README now names edited or replaced copies as unknown. Removal only touches paths that `is_managed` confirms, and `add` and `backup` copy before they delete, so the claim "nothing is removed before it is copied" holds.

## Requested probes

I ran extra scratch tests against a ba249cd copy in
`/private/tmp/claude-501/-Users-maxilr/5b61f2f4-75a0-4c28-a72a-0a819912c26c/scratchpad/rev-fix1-head/tests/test_adopt.py`, in the `reviewer probes` section.

- Empty directories and symlinks inside a copy: the digest changes when an empty dir is added, when a symlink is added, and when a symlink is retargeted. Symlinks are not followed. `copytree(symlinks=True)` keeps links, so the digest taken at install matches. OK.
- File mode changes: `chmod 755` on `SKILL.md` keeps the item managed, because the digest ignores modes. On the next switch it is removed with no backup. Only the permission bit is lost, not content. Non-blocking (N2).
- Large trees: each `status` and `use` hashes every copy in full, and `read_bytes()` loads whole files into memory. This is fine at skill size. Non-blocking (N3).
- Legacy records without a digest: confirmed. `use b` exits 1 and lists `tdd` as "replaced an item respec installed". `--unknown backup` backs it up (`claude-code/tdd/SKILL.md: "# tdd from a"`) and switches. The next `use a` works normally. The engineer gets one prompt and loses no data. Acceptable.
- Symlink mode: no regression. state.json records symlinks without a `digest` key. `use a` then `use b` unlinks normally. The existing replaced-symlink tests pass. `_remove` now runs `is_managed` before it unlinks. The only change is that a recorded symlink that no longer points into the profiles folder is left in place, where before it was unlinked. That entry is already reported as unknown before removal, so the change is stricter and safe.

## Non-blocking findings

- **N1: `.DS_Store` inside a copied skill makes it unknown.**
  Location: `src/respec/unknown.py` `digest()`, which hashes every child, hidden ones included.
  Scenario: a copy-mode skill is opened in Finder, and macOS writes `tdd/.DS_Store`. `status` then lists `tdd` as unknown and `replaced`, and a non-interactive `use` refuses.
  Impact: a false positive that needs a manual choice. It fails safe, with no data loss. Copy mode is a fallback, and symlinks normally work on macOS, so exposure is low. A possible follow-up is to skip OS junk files (`.DS_Store`, `Thumbs.db`) in the digest.
- **N2: mode-only changes are not detected.** See the probes above. A chmod-only edit is deleted on the next switch without a backup. The content was what respec installed, so the impact is minimal.
- **N3: the digest reads whole files and blocks on FIFOs.**
  Location: `unknown.digest`, `entry.read_bytes()`.
  Scenario: a large file inside a copy is read fully into memory. A FIFO or socket inside a copy makes `read_bytes()` block, and `status` hangs.
  Impact: unlikely in skill folders. Hashing in chunks and treating non-regular files by type would harden it.
- **N4: an unreadable file leaves an untracked copy.**
  Location: `src/respec/switch.py` `use`, where `digest=unknown.digest(destination)` runs after `_install`.
  Scenario: the copy succeeds, but hashing raises `OSError` (for example a file that cannot be read). The copy stays at the destination with no record, and the `RespecError` says "items installed so far are recorded".
  Impact: the next run reports the orphan as unknown, so no data is lost. The error message is inaccurate for that one path.
- **N5: `use --json` gains a field.** `cli.py:295` serialises `vars(item)`, so `installed[]` now carries `"digest"`, which is `null` for symlinks. This is an additive change to the JSON output and is not documented.
- **N6: docstring line length.** In the `state.py` module docstring, one line is longer than 88 columns ("copy recorded without one ... listed in"). Black does not reflow docstrings, so this is cosmetic only.

## Scope

The diff stays within F1. It also removes the dead `_remove` branch that the integration report listed as item 5, which follows directly from the new `is_managed` gate. There are no unrelated changes.
