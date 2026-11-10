# respec

Switchable global profiles of agent skills across coding harnesses (Claude Code, oh-my-pi, .agents readers)

## Usage

```sh
respec               # open the TUI (also: respec tui)
respec profile new work --target claude-code --target agents
respec use work      # switch: remove the previous profile's skills, link this one's
respec status        # active profile, targets and managed skills per folder
respec add ./my-skill [-p work]   # copy a skill folder (with SKILL.md) into a profile
respec disable my-skill [-p work] # stop linking it; files and metadata stay
respec enable my-skill [-p work]
respec remove my-skill [-p work]  # drop it from profile.yaml and delete its folder
respec adopt [--add|--remove <entry>] [--all add|remove]
respec restore [<backup>] [--list] [--unknown add|remove] [--overwrite]
respec recover [--rollback]       # finish (or roll back) an interrupted change
respec add owner/repo[#path] [--ref main] [-p work]  # fetch skill(s) from git
respec update --check [-p work]   # which sourced skills have newer commits
respec update [my-skill] [-p work] [--yes]  # apply; --yes overwrites local edits
respec profile install owner/repo[#path] [--name mine]  # copy a whole profile once
```

`add`, `remove`, `enable` and `disable` change the active profile unless `-p`
names another. When the changed profile is active, its target folders are
refreshed right away. Every command accepts `--json`.

`add` also takes `owner/repo[#path]` (resolved against `RESPEC_GIT_BASE_URL`,
default `https://github.com`) or a git URL with an optional `#path`; an
existing local folder of the same name wins. A path holding `SKILL.md` adds that
skill; otherwise every subfolder (or `skills/` subfolder) holding one is added.
Each skill records its source repo, path, ref, resolved commit and a digest of
the fetched files in `profile.yaml`. Updates are explicit and never touch skills
without a source. When a skill's files no longer match the digest, `update`
asks before overwriting them (with `--json` it skips them unless `--yes`).
Fetched skills may only contain symlinks to files inside the skill's own
folder; they are copied as plain files, and links to folders are refused. Git
never prompts: ssh runs with `BatchMode=yes` unless you set your own ssh
command (`GIT_SSH_COMMAND`, `GIT_SSH` or `core.sshCommand`). Each git command
stops after `RESPEC_GIT_TIMEOUT` seconds (default 120); http transfers slower
than 1 KB/s for 30 seconds, and ssh connections not made within 15 seconds,
fail sooner. A source `repo`
must be `owner/repo`, `user@host:path` or an https, http, ssh or git URL; local
paths and other git transports are refused. Skills installed by
`profile install` have no recorded digest, so their first `update` asks before
overwriting.
`profile install` copies a repository's `profile.yaml` and listed `skills/`
once; the profile is then owned locally and its skills keep their own sources.

`respec use` links every enabled skill of the profile into each of its targets'
folders (symlinks, or copies where symlinking fails) and records every created
path in `~/.respec/state.json`. A switch removes only recorded paths, from every
folder, then installs the new profile into its own targets. The first time
respec takes over a target folder it copies the folder's full contents to
`~/.respec/backups/<timestamp>/<target>/`. Installing respec changes nothing.

Some skills survive every switch. respec ships two of its own: `respec` (a
reference of this CLI for agents) and `profile-maker` (a guided interview that
builds a profile through the CLI). Whenever a profile is active they are linked
into every registered target, whatever the profile's targets, so any agent can
edit profiles; a switch therefore takes over all target folders. There is no
opt-out, and `respec restore` removes them with everything else, along with
any folders respec created for them that are empty again. Your own
global skills are listed in `~/.respec/config.yaml`, each in
`~/.respec/global/skills/<skill>/`, and are linked only into the active
profile's targets:

```yaml
global:
  skills: [my-notes]
```

No profile skill may take the name of a global or shipped skill: `add`,
`profile install` and adopt's add refuse such a name before changing
anything. An unknown entry with such a name (for example a replaced
shipped link) can only be removed; it is backed up and respec links its
own skill there again.

Entries in an owned folder that respec did not create are _unknown_. So is a
recorded path that no longer holds what respec put there: a symlink replaced by
something else, or a copy whose content was edited or replaced. Each unknown
entry has two resolutions: `add` copies it into the currently active profile
and manages it from then on (an edited or replaced copy of one of that
profile's own skills overwrites the profile's copy, so the edit is kept), and
`remove` backs it up to `~/.respec/backups/<timestamp>/<target>/` and then
removes it. Without an active profile only `remove` is available. Nothing is
removed before it is copied into a profile or a backup.

Unknown entries block a command only when they sit exactly where it would
install or remove a skill. Any other unknown entry is reported as a warning on
stderr (and in the `unresolved` list with `--json`) with a hint to run
`respec adopt`; `status` lists them too. For a switch that is blocked, a
terminal asks per entry; other runs stop unless
`respec use <profile> --unknown add|remove` gives the choice. During a switch,
`add` goes to the profile being switched away from. The first time respec takes
over a folder that already holds entries, a terminal asks about each right
away (after the switch, which has already backed up the whole folder);
`--unknown` given on a terminal answers these too. At the very first takeover
no profile was active yet, so a terminal's `add` goes to the profile being
activated; `--unknown add` always means the profile active now, so it is refused
when none is. Interrupting a prompt leaves the rest unknown. Other runs back the
folder up as always and warn. Whatever was already done is always reported,
with backup paths, also when a switch fails or is interrupted part way: choices
already made are kept, not undone, and skills added to the profile that is
still active are linked. That includes any folder the switch already took over
and backed up: `respec use --json` always gives `backups`, `resolved`,
`linked`, `unresolved` and `warnings`, plus `error` when it failed. An add that replaces the profile's
own copy of a skill says so and names the backup of the previous copy. If an
earlier run was killed while replacing a copy, its hidden
`.<skill>.respec-old`/`.respec-new` folder in the profile is removed only when
its content is held elsewhere (the live folder or a backup run); a missing live
folder is restored from it, and any other leftover is kept and reported.
`respec adopt`
resolves unknown entries at any time (`--add` or `--remove` per entry, or
`--all`).

Hidden entries (names starting with a dot, such as `.DS_Store`) are ignored:
they are never reported as unknown, never asked about and never removed by a
switch. A `.DS_Store` file inside an installed copy does not count as an edit.

`respec restore` undoes respec: it removes every skill respec manages, puts each
owned folder back to the backup taken when respec first took it over (a folder
that did not exist then is removed again once empty), clears `state.json` and
leaves no profile active. `respec restore <backup>` restores the target folders
of that run instead; `--list` shows the runs. respec's own skills in a backup are
skipped and reported: symlinks into profiles, and copies that the run's
`manifest.json` records as installed by respec when the backup was taken.
Entries the backup would overwrite (unknown ones or edited copies whose content
or permissions differ from the backup) stop the restore until they are resolved
with `--unknown add|remove`, a terminal's answer per entry or `respec adopt`, or
until `--overwrite` backs them up and replaces them. Hidden entries the backup
does not hold stay in place and are reported. A restore that fails
part way can be run again to finish.

### Interrupted changes

Every change of several steps is recorded in a journal in `state.json` before
it changes anything, together with the one step in flight: a switch or
refresh (also an edit of the active profile), a restore, adopt, a layer
repair, linking outside a switch, `update`, `add` from git and `profile
install`. If respec is killed or crashes part way, the journal stays behind:

- `respec status` (and every other command that only reads) reports it.
- The next command that changes skills first finishes the change or rolls it
  back, and says which (`finished` or `rolled-back`):
  - A switch that had not yet removed any skill is rolled back (the previous
    profile stays active). One that had is finished, or, if the new profile
    can no longer be activated, rolled back to the previous one.
  - A restore is finished.
  - An adopt keeps every choice it completed; the entry in flight is finished
    once its copy was whole and otherwise left as it was (then it reports
    `rolled-back`).
  - An edit of the active profile, a layer repair, a local `add` and a
    `remove` are finished when `profile.yaml` was already saved, and rolled
    back when it was not; the links then match `profile.yaml` either way. A
    local `add` that is rolled back drops its copy (the source folder is never
    touched); a finished `remove` deletes the skill folder it was removing.
  - An `update` or git `add` is rolled back until `profile.yaml` records the
    new skills and finished after. A rollback only touches what that run
    made: the skills it swapped (when the folders are still the ones it
    recorded) and the skill folders it created. A folder that was there before
    is never removed.
  - A half-copied `profile install` is removed.
- `respec recover` does the same on its own; `respec recover --rollback`
  undoes the change instead where that is still possible (a switch activates
  the previous profile again; a restore that already removed skills, and the
  choices adopt completed, cannot be undone).
- While a restore waits, `respec restore` finishes that same restore and
  refuses another backup.
- In the TUI, Sync shows the interrupted change with Finish and Roll back;
  until it is resolved, Sync offers nothing else and the TUI refuses every
  change to skill folders.

Nothing is lost on the way: an entry a step left half made (a copy cut short,
or a staging folder of an adopt overwrite) is moved to a fresh backup run and
reported under `set_aside`, unless it is verifiably what that step was making,
in which case it is recorded. An `update` that already saved `profile.yaml`
removes its own `.<skill>.old` (the previous files), also when the
interruption had deleted it part way. A `.<skill>.old` that no journaled
`update` made is never used to replace a skill: like adopt's staging folders,
it is put back when the skill folder is gone, removed when its content is
verifiably in the skill folder or a backup run, and otherwise kept, with
`update` refusing that skill until it is moved out of the way. A journal that
respec does not recognise, or that is malformed, is only dropped by
`respec recover --rollback`. `state.json` and `profile.yaml` are written to a
temporary file, flushed to disk (`F_FULLFSYNC` on macOS) and renamed.

### TUI

`respec` without a command (or `respec tui`) opens a terminal UI: profiles on
the left with the active one marked, each owned target folder on the right.
Select a profile with the arrow keys or a click, then press Enter or click
**Activate**. Unknown entries in the way open a dialog with the same two
choices (add to the active profile, or back up and remove); so do entries found
in a folder the switch took over for the first time. `a` resolves unknown
entries outside a switch, `r` refreshes and `q` quits.

**Edit** (`e`) opens the selected profile: its skills grouped by layer, with a
toggle per skill and, in an active exclusive layer, a choice of one skill (or
none). **Add folder** (`a`) and **Add from git** (`g`) add skills, and
**Check updates** (`u`) marks sourced skills that have a newer commit. Git runs
in the background with a **Cancel** button (or `Esc`). Every
change goes through the same code as `respec enable`, `respec layer use` and
`respec add`, so an active profile is re-applied at once and a refused change
leaves the profile as it was. **New profile** (`n`) asks for a name and targets.

**⟳ Sync** (`s`) is a manual check of the setup and every profile; nothing is
watched in the background. It lists unknown entries and edited or replaced
copies (add to the active profile, or back up and remove, as `respec adopt`),
exclusive layers with several enabled skills (keep one, as `respec layer
repair`), and links respec placed that are missing, broken or out of line with
the active profile (re-apply it). Each fix is listed with its backups; with
nothing found it says everything is in sync. Shipped and global skills are marked
in the status panel and the editor; Sync expects them where `respec use` puts
them, and an entry in their place can only be removed.

### Layers

```sh
respec layer list [-p work]                     # built-in and custom layers
respec layer use design-principles my-design    # exclusive: the others are disabled
respec layer add review --additive -d "Code review helpers"
respec layer add-skill review my-review         # group skills; enable/disable as one
respec layer disable review
respec layer off design-principles              # its rules lapse; skills stay
respec layer repair design-principles --keep my-design  # fix a hand-edited conflict
```

A layer is a named group inside one profile that only decides which skills are
enabled; it never changes where they are installed. An exclusive layer keeps at
most one skill enabled. Built-in layers are `design-principles` (design principles
only, never component libraries or project tokens) and `output-style`, which
accepts no skills until output styles are supported. Built-ins cannot be
removed, only turned off. Skills outside layers, and skills of a layer that is
off, are plain additive skills.

In `profile.yaml` a layer lists its members under `skills:` (the older `items:`
key is still read; respec always writes `skills:`). If a hand edit leaves an
exclusive layer with several enabled skills, every command that reads, creates or
installs the profile warns on stderr, and `respec use` refuses the profile. The warning reflects the
profile as the command left it, so a command that fixes the conflict does not
warn. `respec layer repair <layer>` keeps one skill and disables the rest, also
in a layer that is turned off: `--keep <skill>` picks it, a terminal asks, and
other runs keep the first listed skill. The `--json` output of every `respec
layer` change lists the skills it disabled under `disabled`.

Turning a layer off (or on) in the active profile re-applies the profile once it
has no conflicts left, so skills that a conflict kept out of the target folders
are linked right away. A change that cannot be applied to the active profile is
refused with `cannot refresh profile '<name>'` and leaves `profile.yaml` as it
was. `respec layer repair` is the one exception for unknown entries: a repair
only disables skills, so when unknown entries refuse the refresh it still
saves the repair, unlinks the disabled skills and links the kept one. It only
removes links that still hold what respec placed and only links into free
paths, so an unknown entry (also an edited copy of a skill of that layer) is
never touched and waits for `respec adopt`: add keeps the edit in the profile,
remove backs it up. So a conflict and an edited copy never block each other's
fix. Other refusals (such as a missing skill folder) still leave the profile
unchanged.

Every `--json` output that is an object uses one vocabulary:

- `resolved`: the unknown entries a command resolved, each with its `choice`
  (`add` or `remove`), and the `profile` it went to or the `backup` it went to.
- `unresolved`: unknown entries still waiting for a decision, each with
  `name`, `path`, `kind` (`folder`, `file` or `symlink`), `targets` and
  `replaced` (an edited or replaced copy of a skill respec installed). `use`,
  `adopt`, `restore`, `status` and every command that changes skills or
  layers (`add`, `remove`, `enable`, `disable`, `update` and the `layer`
  changes) give it. A refused `use` or `restore` also lists the entries in its
  way there, including ones outside the folders respec owns.
- `backups`: the folders `use` took over, with their takeover backups.
- `warnings`: always present, empty when there is nothing to warn about. Each
  warning is an object with a `type` and a `message`. The types:
  - `layer-conflict`: an exclusive layer has several enabled skills; also
    gives `profile`, `layer`, `skills` and `fix`.
  - `interrupted-operation`: a change that was cut short (see
    [Interrupted changes](#interrupted-changes)); also gives `operation`
    (`use`, `restore`, `adopt`, `links`, `update`, `add` or `install`),
    `outcome` (`finished` or `rolled-back` when this command recovered it,
    `pending` when it still waits), `set_aside` (paths moved to a backup
    run) and `profile` when it concerns one. `respec recover --json` gives
    `active_profile`, `recovered` (whether there was anything to recover)
    and this warning.
- `error`: present only when the command failed. `use`, `adopt` and
  `restore` then print every other key of their success output too, filled
  with what was done before the failure. Other commands print their error on
  stderr only.

A field that does not apply is left out rather than given as `null`: for
example a resolved entry has `profile` only when it was added and `backup`
only when it was removed, a linked skill has no `digest`, a layer change has
`skill` only when it names one, a skill without a git source has no `source`,
and `restore` gives `backup` only when a backup run was named. Only these
fields can be `null`, each meaning "none": `active_profile` and
`previous_profile` (no profile), `same_as` (the folder is not shared with
another target) and a value under `restored` (that folder did not exist at
takeover). In `status`, each skill of a folder gives its `origin`: `profile`,
`shipped` (respec's own skills) or `global` (from `config.yaml`); a link is
judged by the folder it points into.

The same warnings are printed on stderr. `respec restore --list --json` prints a
bare list of backups instead: it reads no profile, so it has nothing to warn
about.

## Development

```sh
uv sync
uv run respec --help
uv run pytest
uv run black --check .
```

Two environment variables are advanced/testing overrides, not everyday options:
`RESPEC_USER_HOME` relocates the home that target folders such as
`~/.claude/skills` resolve against, and `RESPEC_HOME` relocates respec's data
folder (default `.respec` inside that home). The test suite points
`HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` at temporary folders for every test
and fails any test that resolves a respec path under the real home.
