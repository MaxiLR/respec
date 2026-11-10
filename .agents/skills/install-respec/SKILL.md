---
name: install-respec
description: Install respec from this repository checkout so the `respec` command works from any directory, by adding a shell alias to ~/.bashrc (and ~/.zshrc for zsh users). Use it when asked to install, set up or uninstall respec on this machine.
---

# Install respec

This installs respec as a shell alias that runs it from this checkout with
`uv`. The alias keeps the caller's working directory, so relative paths such as
`respec add ./my-skill` still work.

## Steps

1. Find the absolute path of this repository and check `uv` is available:

   ```sh
   REPO="$(git rev-parse --show-toplevel)"
   test -f "$REPO/pyproject.toml" && grep -q '^name = "respec"' "$REPO/pyproject.toml"
   command -v uv
   ```

   If `uv` is missing, stop and tell the user to install it
   (<https://docs.astral.sh/uv/getting-started/installation/>). Do not install
   it for them without asking.

2. Install the dependencies:

   ```sh
   uv sync --frozen --project "$REPO"
   ```

3. Choose the startup files. Always use `~/.bashrc`. If the user's login shell
   is zsh (`echo "$SHELL"` ends in `zsh`, the macOS default), also use
   `~/.zshrc`, because zsh never reads `~/.bashrc`.

4. In each chosen file, add the alias once. Create the file if it does not
   exist. If a line starting with `alias respec=` is already there, replace
   that line instead of adding a second one, and tell the user what it was.

   ```sh
   # respec: switchable profiles of global agent skills
   alias respec='uv run --project "/absolute/path/to/respec" respec'
   ```

   Write the real value of `$REPO` in place of `/absolute/path/to/respec`. Keep
   the single quotes outside and the double quotes around the path. Change
   nothing else in the file.

5. Verify from another directory, in a new interactive shell so the startup
   file is read:

   ```sh
   cd / && bash -ic 'respec --help'
   cd / && zsh -ic 'respec --help'   # only if ~/.zshrc was changed
   ```

   Each must print respec's help, starting with `Usage: respec`.

6. Tell the user which files changed, and that shells already open need
   `source ~/.bashrc` (or `source ~/.zshrc`) or a restart to see the alias.

## Limits to tell the user about

- On macOS, a bash **login** shell reads `~/.bash_profile`, not `~/.bashrc`.
  If the user works in bash there and `respec` is not found, `~/.bash_profile`
  needs the line `[ -f ~/.bashrc ] && . ~/.bashrc`. Ask before adding it.
- An alias exists only in interactive shells. Scripts and agents that run
  commands non-interactively will not find `respec`. If the user needs that,
  offer `uv tool install --editable "$REPO"`, which puts a real `respec`
  command on `PATH`; then remove the alias so the two do not disagree.
- The alias points at this checkout. If the folder moves, rerun this skill.

## Uninstall

Remove the comment line and the `alias respec=` line from the files changed
above. This does not undo anything respec did to skill folders; run
`respec restore` first for that.
