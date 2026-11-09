# respec

Switchable global profiles of agent skills across coding harnesses (Claude Code, oh-my-pi, .agents readers)

## Usage

```sh
respec               # open the TUI (also: respec tui)
respec profile new work --target claude-code --target agents
respec use work      # switch: remove the previous profile's items, link this one's
respec status        # active profile, targets and managed items per folder
respec add ./my-skill [-p work]   # copy a skill folder (with SKILL.md) into a profile
respec disable my-skill [-p work] # stop linking it; files and metadata stay
respec enable my-skill [-p work]
respec remove my-skill [-p work]  # drop it from profile.yaml and delete its folder
respec adopt [--add|--backup|--keep <entry>] [--all <choice>] [-p work]
respec restore [<backup>] [--list] [--unknown add|backup|keep] [--overwrite]
```

`add`, `remove`, `enable` and `disable` change the active profile unless `-p`
names another. When the changed profile is active, its target folders are
refreshed right away. Every command accepts `--json`.

`respec use` links every enabled skill of the profile into each of its targets'
folders (symlinks, or copies where symlinking fails) and records every created
path in `~/.respec/state.json`. A switch removes only recorded paths, from every
folder, then installs the new profile into its own targets. The first time
respec takes over a target folder it copies the folder's full contents to
`~/.respec/backups/<timestamp>/<target>/`. Installing respec changes nothing.

Entries in an owned folder that respec did not create are _unknown_. So is a
recorded path that no longer holds what respec put there: a symlink replaced by
something else, or a copy whose content was edited or replaced. `status` lists
them, and before a switch each one needs a choice: `add` (copy it into
the profile being activated, then manage it), `backup` (move it to
`~/.respec/backups/<timestamp>/<target>/`) or `keep` (leave it, unmanaged, and
stop asking). A terminal asks per entry; other runs stop unless
`respec use <profile> --unknown add|backup|keep` gives the choice. `respec adopt`
resolves unknown entries outside a switch (`--add` copies into the active
profile unless `-p` names another). Nothing is removed before it is copied into
a profile or a backup.

`respec restore` undoes respec: it removes every item respec manages, puts each
owned folder back to the backup taken when respec first took it over (a folder
that did not exist then is removed again once empty), clears `state.json` and
leaves no profile active. `respec restore <backup>` restores the target folders
of that run instead; `--list` shows the runs. Symlinks into profiles, and copies
of profile items in a backup taken after respec owned the folder, are never put
back. Entries the backup would overwrite (unknown ones, edited copies, or kept
entries that differ from the backup) stop the restore until they are resolved
with `--unknown` or `respec adopt`, or until `--overwrite` (or a yes in a
terminal) backs them up and replaces them. A restore that fails part way can be
run again to finish.

### TUI

`respec` without a command (or `respec tui`) opens a terminal UI: profiles on
the left with the active one marked, each owned target folder on the right.
Select a profile with the arrow keys or a click, then press Enter or click
**Activate**. Unknown entries open a dialog with the same three choices; `a`
resolves them outside a switch, `r` refreshes and `q` quits.

### Layers

```sh
respec layer list [-p work]                     # built-in and custom layers
respec layer use design-principles my-design    # exclusive: the others are disabled
respec layer add review --additive -d "Code review helpers"
respec layer add-item review my-review          # group items; enable/disable as one
respec layer disable review
respec layer off design-principles              # its rules lapse; items stay
```

A layer is a named group inside one profile that only decides which items are
enabled; it never changes where they are installed. An exclusive layer keeps at
most one item enabled. Built-in layers are `design-principles` (design principles
only, never component libraries or project tokens) and `output-style`, which
accepts no items until output styles are supported. Built-ins cannot be removed,
only turned off. Items outside layers, and items of a layer that is off, are
plain additive items.

## Development

```sh
uv sync
uv run respec --help
uv run pytest
uv run black --check .
```

`RESPEC_HOME` relocates respec's data folder (default `~/.respec`).
`RESPEC_USER_HOME` or `respec --home <dir>` relocates the home that target
folders such as `~/.claude/skills` resolve against. The test suite points
`HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` at temporary folders for every test
and fails any test that resolves a respec path under the real home.
