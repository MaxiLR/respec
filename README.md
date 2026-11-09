# respec

Switchable global profiles of agent skills across coding harnesses (Claude Code, oh-my-pi, .agents readers)

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
