# Overlap analysis 1: respec-v1

Read-only scheduling analysis. Inputs: `spec.md` (revision 2), tickets 001 to 013
(revision 1), repo at planning commit (README and .gitignore only, no package yet).
Conclusions about shared files come from the spec and ticket bodies, not from code.

## Likely shared files and contracts

001 and 002 will create these, and later tickets will extend them:

| Hotspot                                                    | Created by | Extended by                                                                                                                                                                                 |
| ---------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Switching engine (`use`, install/remove, state recording)  | 002        | 003 (journal wraps every mutation), 004 (pre-switch unknown-entry prompt), 006 (refresh active targets), 009 (global items installed, never removed), 005 (remove managed links on restore) |
| `state.json` schema                                        | 002        | 003 (journal, lock), 004 (owned-folder knowledge), 005 (clear and release ownership), 009 (global item paths)                                                                               |
| `status` output and `--json` shape                         | 002        | 003 (incomplete switch), 004 (unknown entries), 009 (global items), 010 (TUI status panel reads it)                                                                                         |
| `profile.yaml` model, loader, writer                       | 001        | 006 (writes items, enabled), 007 (source fields), 008 (layers), 009 (`system: false`), 004 (adopt adds an item)                                                                             |
| "Add skill folder to profile" (copy plus register in yaml) | 006        | 004 (adopt choice "add to profile"), 007 (remote add dispatch in the same `add` command)                                                                                                    |
| Typer app / `cli.py`                                       | 001        | every ticket (new commands); 010 adds the no-args callback                                                                                                                                  |
| Target registry data file                                  | 001        | 012 (per-target copy mode, if symlinks fail)                                                                                                                                                |
| Shipped `respec` skill text (documents the CLI surface)    | 009        | content depends on 004 (adopt), 007 (sources), 008 (layers)                                                                                                                                 |

When tickets append separate commands to `cli.py`, the conflicts are mechanical and
easy to resolve, so that alone does not justify an ordering edge. The edges below are
for cases where two tickets would implement the same behaviour differently or rewrite
the same function.

## Group 002 -> {003, 004, 005, 006}

- **006 and 004.** Adopt's "add to profile" means copying a folder into the profile and
  registering it in `profile.yaml`. That is the same operation as 006's `add <local-path>`
  (SKILL.md check, name collision handling, refreshing the active target). If both run in
  parallel, two add paths and two yaml-writer conventions will likely appear. Both tickets
  also change target links on an already active profile. **Edge: 006 before 004.** This
  adds one ticket to the 002->004->010->011 path, but 011 already waits for 006->007/008,
  so the total critical path barely changes.
- **004 and 005.** Restore must "refuse to overwrite unknown entries without the adopt
  flow". That requires 004's detection and adopt functions, so this is a real contract
  dependency. If 005 runs first, it would build its own unknown-entry detection.
  **Edge: 004 before 005.**
- **003 and 004/005/006/009.** 003 wraps every target-folder mutation in a journal and
  adds a lock. The other tickets each add mutation paths:
  - 004: back up and remove during a switch.
  - 005: restore.
  - 006: incremental refresh on enable/disable/remove.
  - 009: global items installed into active targets.

  If 003 lands first, each later ticket has to journal its own mutations, and a missed
  path breaks the "exactly one profile's items present" guarantee. If 003 runs in
  parallel, it rewrites the same `use` function and `state.json` schema that 004 and 009
  edit, which makes conflicts very likely. 003 only feeds 013, so putting it last costs
  nothing on the critical path. **Edges: 004 before 003, 005 before 003, 009 before 003**
  (006 is covered transitively through 004).

## Group 006 -> {007, 008, 009}

- **007 and 008.** Both add fields to the item schema in the `profile.yaml` model (source
  record and layer membership). The conflicts are textual and local. 008 rewrites
  enable/disable for exclusivity, and 007 does not touch that code. Divergence risk is
  low. **No edge.** Whichever merges second should rebase onto the other's schema changes.
- **009 and 007/008/004.** 009 ships the `respec` skill, which documents sources,
  layers and the adopt flow. Its test runs `--help` for every documented command. Written
  before those commands exist, the skill either leaves them out or names commands that
  fail the test. 009 also edits the switching engine (global items) and adds
  `system: false` to the profile model. 009 only feeds 013, so delaying it costs nothing.
  **Edges: 007 before 009, 008 before 009, 004 before 009.**

## 010 versus the 006 family

010 uses core functions for profile listing, switching and the adopt dialog, which come
from 002 and 004. It reads `status` data and adds the Typer no-args callback. It does
not write `profile.yaml` items, layers or sources. Running it in parallel with 005, 007,
008 and 009 is safe. The only overlap is in `cli.py` and is mechanical. 003 adds an
"incomplete switch" status that the TUI will not show until 011 or a later tweak, which
is acceptable. **No edge.**

## 012 (human)

If the engineer finds a harness that does not load symlinked skill folders, 012 sets
copy mode for that target in the registry. That needs the per-target install-mode
support that 002 introduces, because 002 owns symlinks with copy fallback. The
verification itself can start at any time. **Edge: 002 before 012** (only for the
registry change part of 012).

## Resulting schedule (no cycles)

001 -> 002 -> 006 -> {004, 007, 008}; 004 -> {005, 010}; {004, 007, 008} -> 009;
{004, 005, 009} -> 003; {010, 007, 008} -> 011; 002 -> 012;
{003, 005, 009, 011, 012} -> 013.

Longest automated chains are 002-006-004-010-011 and 002-006-007/008-009-003, both five
tickets after 002. Before these edges, the declared longest chain was four. In
exchange, far fewer rewrites of the engine and schema run in parallel.

## Shared test resources

- **Home and RESPEC_HOME.** Every test is designed to use a temporary `RESPEC_HOME` and a
  temporary home. With per-test `tmp_path`, targeted suites can run in parallel across
  worktrees. The risk is a code path that falls back to the real `~` when the override
  is missing. Recommendation for 001: add an autouse conftest fixture that always sets
  both variables (and `HOME`) to tmp, and a guard that fails if anything resolves under
  the real home. 012 is the only ticket that touches the real home, and it is manual.
- **Git (007).** Tests use local bare repos over `file://` with no network. Tests should
  isolate git config (`HOME` tmp, `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM`) so the
  engineer's `~/.gitconfig` (insteadOf rules, signing, hooks) cannot leak in. The
  `owner/repo` shorthand must resolve through an injectable base URL, never to
  github.com. No serialization is needed.
- **Textual Pilot (010, 011).** Headless, no ports. Safe to run in parallel.
- **Ports.** None. The board on port 3333 is not part of the test suite.
- **Lock file (003).** Lives under `RESPEC_HOME`, so each test gets its own. Safe.
- **Backup timestamps.** `backups/<timestamp>` can collide within one test when two
  takeovers happen in the same second. The clock should be injectable, or names should
  be unique. This is a correctness issue inside a single test, not a cross-process one.
- **uv environment.** Each worktree has its own `.venv`. uv's shared cache is
  lock-protected. Safe.

Conclusion: targeted tests can run in parallel across worktrees once the 001 conftest
isolation is in place. No serialization is needed.
