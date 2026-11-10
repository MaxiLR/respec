# respec

> Switchable profiles of global agent skills for Claude Code, the `.agents`
> standard and oh-my-pi.

![The respec terminal UI: switching to another profile, turning a skill off in the editor, and running Sync](docs/assets/tui-demo.svg)

Coding agents load global skills from folders in your home directory, and some
read each other's folders. A set of skills meant for one kind of work leaks
into every other session, and there is no clean way to swap sets or to go back.

respec takes over those folders and keeps your skills in named **profiles**.
One profile is active at a time. Switching removes everything the previous
profile installed and installs the new one, from the command line or a terminal
UI.

```sh
respec profile new work --target claude-code --target agents
respec add ./my-skill
respec add owner/repo#skills/tdd
respec use work
```

## Features

- **Profiles:** self-contained sets of skills; one command switches between
  them across every harness.
- **Safe takeover:** the first switch backs up each skill folder in full, and
  `respec restore` puts it back.
- **Nothing is lost silently:** skills respec did not install are reported, and
  you choose to add them to a profile or remove them (with a backup).
- **Skills from a folder or git:** add skills from a local folder or a
  repository, check them against that source and update on request.
- **Layers:** group a profile's skills; an exclusive layer keeps at most one of
  its skills enabled.
- **Terminal UI:** switch, edit and check profiles with the keyboard or mouse.
- **Built for agents:** every command takes `--json`, and respec installs a
  skill that teaches agents how to use it.
- **Interruption-safe:** a change cut short by a kill or power loss is finished
  or rolled back by the next command.

> [!NOTE]
> respec is at version 0.1.0. It manages three folders: `~/.claude/skills`,
> `~/.agents/skills` and `~/.omp/agent/skills`.

## Install

You need [git](https://git-scm.com), [uv](https://docs.astral.sh/uv/) and
Python 3.11 or newer.

```sh
git clone https://github.com/MaxiLR/respec.git
cd respec
```

**With a coding agent:** start Claude Code, or a harness that reads
`.agents/skills/`, inside the checkout and run `/install` (or ask it to
"install respec"). It follows
[the install skill](.agents/skills/install/SKILL.md), which adds a `respec`
alias to your shell startup file so the command works from any directory.

**By hand:**

```sh
uv sync --frozen
echo "alias respec='uv run --project \"$PWD\" respec'" >> ~/.bashrc   # or ~/.zshrc
```

Open a new shell, then run `respec --help`.

> [!TIP]
> An alias exists only in interactive shells. If scripts or agents need to run
> `respec` too, use `uv tool install --editable .` instead, which puts a real
> command on your `PATH`.

Installing changes nothing in your skill folders. That happens at the first
`respec use`.

## Quick start

```sh
# 1. Create a profile for the harnesses it should apply to
respec profile new work -t claude-code -t agents -t oh-my-pi

# 2. Add skills: a local folder holding SKILL.md, or a git repository
respec add ./my-skill -p work
respec add owner/repo#skills/tdd -p work

# 3. Activate it
respec use work

# 4. See what is installed where
respec status
```

Running `respec` with no command opens the terminal UI.

### What the first `respec use` does

1. It copies each skill folder it takes over, in full, to
   `~/.respec/backups/<timestamp>/`.
2. It links the profile's skills into the profile's targets, and respec's own
   two skills into all three folders.
3. It leaves the skills you already had in place and asks about each one: add
   it to the profile, or remove it. Without a terminal it leaves them and
   warns.

> [!IMPORTANT]
> `respec restore` undoes all of it: it removes what respec manages and puts
> each folder back as it was before the first switch.

To try respec without touching your real folders, point it at a throwaway home:

```sh
export RESPEC_USER_HOME="$(mktemp -d)"
```

## How it works

| Term              | Meaning                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Profile**       | A folder in `~/.respec/profiles/<name>/` with a `profile.yaml` and the skills themselves.                                                        |
| **Target**        | A harness folder a profile installs into: `claude-code` (`~/.claude/skills`), `agents` (`~/.agents/skills`), `oh-my-pi` (`~/.omp/agent/skills`). |
| **Switch**        | `respec use <profile>` removes only what respec installed, from every folder, then links the new profile into its targets.                       |
| **Unknown entry** | Anything in an owned folder that respec did not put there, or a copy that was edited. Resolve it with `add` or `remove`.                         |
| **Layer**         | A named group of skills inside a profile. An exclusive layer keeps at most one enabled.                                                          |
| **Shipped skill** | `respec` and `profile-maker`, installed into every target whenever a profile is active so any agent can manage profiles.                         |
| **Global skill**  | A skill of yours listed in `~/.respec/config.yaml`; it survives every switch.                                                                    |
| **Source**        | Where a profile or a skill was copied from: a folder or a git repository. respec reads it and never writes to it.                                |

Skills are installed as symlinks into the profile, or as copies where
symlinking fails. respec records every path it creates and never removes
anything it did not record.

## Commands

| Command                                    | What it does                                                    |
| ------------------------------------------ | --------------------------------------------------------------- |
| `respec` / `respec tui`                    | Open the terminal UI.                                           |
| `respec profile new <name> -t <target>`    | Create an empty profile.                                        |
| `respec profile list` / `show <name>`      | Inspect profiles.                                               |
| `respec profile install <folder or repo>`  | Copy a whole profile and remember where it came from.           |
| `respec profile diff <name>`               | Show how a profile differs from its source; changes nothing.    |
| `respec profile remove <name>`             | Move a profile that is not active to a backup.                  |
| `respec use <profile>`                     | Switch to a profile.                                            |
| `respec status`                            | Show the active profile, its targets and the skills per folder. |
| `respec add <folder or owner/repo[#path]>` | Add a skill and enable it.                                      |
| `respec enable` / `disable <skill>`        | Turn a skill on or off, keeping its files.                      |
| `respec remove <skill>`                    | Remove a skill from a profile and delete its files.             |
| `respec update [--check] [<skill>]`        | Check for, or apply, updates from a skill's folder or git repo. |
| `respec layer ...`                         | Group skills into layers (`respec layer --help`).               |
| `respec adopt`                             | Resolve unknown entries: add or remove each.                    |
| `respec restore [<backup>]`                | Put a backup back and release every folder.                     |
| `respec recover [--rollback]`              | Finish, or roll back, an interrupted change.                    |

`add`, `remove`, `enable` and `disable` change the active profile unless
`-p <profile>` names another. When the changed profile is active, its folders
are refreshed right away. Every command except `tui` accepts `--json`.

## Terminal UI

`respec` shows your profiles on the left and each owned folder on the right.

| Key             | Action                                                          |
| --------------- | --------------------------------------------------------------- |
| Arrow keys, Tab | Move between controls                                           |
| Enter           | Activate the selected profile                                   |
| `e`             | Edit the profile: toggle skills, choose within layers, add more |
| `n` / `d`       | New profile / remove profile                                    |
| `s`             | Sync: check the setup and offer fixes                           |
| `a`             | Resolve unknown entries                                         |
| `r` / `q`       | Refresh / quit                                                  |

Sync is a manual check; nothing is watched in the background.

## For agents

Whenever a profile is active, respec links two skills of its own into every
target:

- `respec`: a reference of the CLI, so an agent can add, remove and switch
  skills when you ask.
- `profile-maker`: a guided interview that builds a profile.

respec keeps its own copy of every skill and never writes to a skill's source.
An agent asked to edit a global skill first looks up where it came from:
`respec profile show <name> --json` (and `respec status --json`) give each
skill's `provenance` and `source`. A skill with a source is edited there and
brought in with `respec update <skill> -p <profile>`; only a skill that is original to the
copy is edited under `~/.respec/profiles/`. The shipped `respec` skill states
this rule, and a generated `SOURCE.md` in each profile's folder repeats it per
skill. See
[Finding a skill's true source](docs/reference.md#finding-a-skills-true-source).

Every command's `--json` output uses one vocabulary (`resolved`, `unresolved`,
`backups`, `warnings`, `error`), described in the
[reference](docs/reference.md#json-output).

## Documentation

The [reference](docs/reference.md) covers every command in detail:

- [Skills from git](docs/reference.md#skills-from-git)
- [Finding a skill's true source](docs/reference.md#finding-a-skills-true-source)
- [Shipped and global skills](docs/reference.md#shipped-and-global-skills)
- [Unknown entries](docs/reference.md#unknown-entries)
- [Undo](docs/reference.md#undo)
- [Interrupted changes](docs/reference.md#interrupted-changes)
- [Running two at once](docs/reference.md#running-two-at-once)
- [Layers](docs/reference.md#layers)
- [JSON output](docs/reference.md#json-output)
- [Environment variables](docs/reference.md#environment-variables)

## Development

```sh
uv sync
uv run respec --help
uv run pytest
uv run black --check src tests
```

The test suite points every respec path at temporary folders and fails any
test that touches the real home.

Agents changing this repository follow
[the maintain skill](.agents/skills/maintain/SKILL.md): after every change,
check whether the shipped skills in `src/respec/shipped/`, this README and the
reference still describe the program.
