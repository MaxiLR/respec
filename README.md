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
respec adopt [--add|--backup|--keep <entry>] [--all <choice>] [-p work]
respec restore [<backup>] [--list] [--unknown add|backup|keep] [--overwrite]
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
something else, or a copy whose content was edited or replaced. `status` lists
them, and before a switch each one needs a choice: `add` (copy it into
the profile being activated, then manage it), `backup` (move it to
`~/.respec/backups/<timestamp>/<target>/`) or `keep` (leave it, unmanaged, and
stop asking). A terminal asks per entry; other runs stop unless
`respec use <profile> --unknown add|backup|keep` gives the choice. `respec adopt`
resolves unknown entries outside a switch (`--add` copies into the active
profile unless `-p` names another). Nothing is removed before it is copied into
a profile or a backup.

`respec restore` undoes respec: it removes every skill respec manages, puts each
owned folder back to the backup taken when respec first took it over (a folder
that did not exist then is removed again once empty), clears `state.json` and
leaves no profile active. `respec restore <backup>` restores the target folders
of that run instead; `--list` shows the runs. respec's own skills in a backup are
skipped and reported: symlinks into profiles, and copies that the run's
`manifest.json` records as installed by respec when the backup was taken.
Entries the backup would overwrite (unknown ones, edited copies, or kept entries
whose content or permissions differ from the backup) stop the restore until
they are resolved with `--unknown` or `respec adopt`, or until `--overwrite` (or
a yes in a terminal) backs them up and replaces them. Kept and hidden entries
the backup does not hold stay in place and are reported. A restore that fails
part way can be run again to finish.

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

Every `--json` output that is an object has a `warnings` list, empty when there
are no conflicts; each entry gives `profile`, `layer`, `skills`, `message` and
`fix`. `respec restore --list --json` prints a bare list of backups instead: it
reads no profile, so it has nothing to warn about.

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
