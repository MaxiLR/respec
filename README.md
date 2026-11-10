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
command (`GIT_SSH_COMMAND`, `GIT_SSH` or `core.sshCommand`). A source `repo`
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
stderr (and in a `warnings` list with `--json`) with a hint to run
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
already made are kept, not undone. An add that replaces the profile's own copy
of a skill says so and names the backup of the previous copy. `respec adopt`
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

### TUI

`respec` without a command (or `respec tui`) opens a terminal UI: profiles on
the left with the active one marked, each owned target folder on the right.
Select a profile with the arrow keys or a click, then press Enter or click
**Activate**. Unknown entries in the way open a dialog with the same two
choices (add to the active profile, or back up and remove); so do entries found
in a folder the switch took over for the first time. `a` resolves unknown
entries outside a switch, `r` refreshes and `q` quits.

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
was.

Every `--json` output that is an object has one `warnings` list, empty when
there is nothing to warn about. Each warning is an object with a `type` and a
`message`:

- `layer-conflict`: an exclusive layer has several enabled skills; it also
  gives `profile`, `layer`, `skills` and `fix`.
- `unknown-entry`: an entry respec did not place (or an edited or replaced
  copy) in a folder it owns; it also gives `name`, `path`, `kind` (`folder`,
  `file` or `symlink`), `targets` and `replaced`. Commands that change skills,
  layers or the active profile (`use`, `add`, `remove`, `enable`, `disable`,
  `update` and the `layer` changes) report these; `status` and `adopt` list
  unknown entries in their own `unknown` field instead.

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
