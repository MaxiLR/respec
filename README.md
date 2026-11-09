# respec

Switchable global profiles of agent skills across coding harnesses (Claude Code, oh-my-pi, .agents readers)

## Usage

```sh
respec profile new work --target claude-code --target agents
respec use work      # switch: remove the previous profile's items, link this one's
respec status        # active profile, targets and managed items per folder
```

`respec use` links every enabled skill of the profile into each of its targets'
folders (symlinks, or copies where symlinking fails) and records every created
path in `~/.respec/state.json`. A switch removes only recorded paths, from every
folder, then installs the new profile into its own targets. The first time
respec takes over a target folder it copies the folder's full contents to
`~/.respec/backups/<timestamp>/<target>/`. Installing respec changes nothing.

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
