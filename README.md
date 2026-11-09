# respec

Switchable global profiles of agent skills across coding harnesses (Claude Code, oh-my-pi, .agents readers)

## Usage

```sh
respec profile new work --target claude-code --target agents
respec use work      # switch: remove the previous profile's items, link this one's
respec status        # active profile, targets and managed items per folder
respec add ./my-skill [-p work]   # copy a skill folder (with SKILL.md) into a profile
respec disable my-skill [-p work] # stop linking it; files and metadata stay
respec enable my-skill [-p work]
respec remove my-skill [-p work]  # drop it from profile.yaml and delete its folder
respec adopt [--add|--backup|--keep <entry>] [--all <choice>] [-p work]
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

Entries in an owned folder that respec did not create are _unknown_: `status`
lists them, and before a switch each one needs a choice: `add` (copy it into
the profile being activated, then manage it), `backup` (move it to
`~/.respec/backups/<timestamp>/<target>/`) or `keep` (leave it, unmanaged, and
stop asking). A terminal asks per entry; other runs stop unless
`respec use <profile> --unknown add|backup|keep` gives the choice. `respec adopt`
resolves unknown entries outside a switch (`--add` copies into the active
profile unless `-p` names another). Nothing is removed before it is copied into
a profile or a backup.

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
