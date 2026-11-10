---
name: respec
description: Reference for respec, the CLI that switches named profiles of global agent skills across Claude Code, the .agents folder and oh-my-pi. Use it when asked to add, remove, enable or disable a global skill, switch or inspect profiles, group skills into layers, update skills from git, resolve unknown entries in skill folders, or undo respec. Also says which scope a hook belongs in.
---

# respec

respec keeps self-contained **profiles** of global agent skills and activates
exactly one at a time. Switching removes every skill the previous profile
placed, in every folder, then installs the new profile into its own targets.

Change profiles only through the `respec` commands below. Never edit
`profile.yaml`, `state.json` or the target folders by hand: respec records
every path it creates, and hand edits make its record disagree with disk.

## Ground rules for agents

- Pass `--json` to read results. Every command except `tui` accepts it. JSON
  objects carry a `warnings` list; each warning has a `type`
  (`layer-conflict` or `interrupted-operation`) and a `message`. Unknown entries still waiting for a
  decision are listed under `unresolved`; entries a command resolved are
  under `resolved`. Fields that do not apply are left out; only
  `active_profile`, `previous_profile`, `same_as` and values under `restored`
  can be `null` (meaning none).
- Exit code 0 means done; 1 means refused or failed. `use`, `adopt` and
  `restore` then print their usual JSON keys plus `error`; other commands
  print the reason on stderr. A refused command changes nothing unless its
  output reports what it already did.
- Commands that change a profile take `-p <profile>`; without it they change
  the active profile.
- Only global skills belong in respec. Project-scoped content (a project's
  component library, design tokens, repository conventions) belongs in that
  project, never in a profile.
- Check a command's options with its `--help` (for example
  `respec layer repair --help`) before relying on one.

## Targets

| Target        | Folder                |
| ------------- | --------------------- |
| `claude-code` | `~/.claude/skills`    |
| `agents`      | `~/.agents/skills`    |
| `oh-my-pi`    | `~/.omp/agent/skills` |

Every enabled skill of a profile goes to all of that profile's targets.

## Commands

### Profiles

- `respec profile new <name> -t <target> [-t <target>...]`: create an empty
  profile.
- `respec profile list`: profiles with their targets and skill counts.
- `respec profile show <name>`: targets (with folders) and skills.
- `respec profile install <owner/repo[#path]> [--name <name>] [--ref <ref>]`:
  copy a whole profile folder (with `profile.yaml`) from a git repository
  once. It is then owned locally; respec does not track it upstream.
- `respec use <profile> [--unknown add|remove]`: activate a profile.
- `respec status`: active profile, its targets, and the managed skills in
  each folder respec owns (each marked by `origin`: `profile`, `shipped` or
  `global`), plus the unknown entries (`unresolved`).
- `respec tui` (or `respec` alone on a terminal): the terminal UI.

### Skills

- `respec add <source> [-p <profile>] [--ref <ref>]`: add a skill and enable
  it. `<source>` is a local folder holding `SKILL.md` (an existing local
  folder wins), `owner/repo[#path]`, or a git URL `[#path]`. A repository
  path without `SKILL.md` adds every skill folder directly in it (or in its
  `skills/` folder). Git sources record their origin (repo, path, ref,
  resolved commit, digest).
- `respec remove <skill> [-p <profile>]`: remove a skill and delete its files.
- `respec enable <skill> [-p <profile>]`: enable it; an active profile links
  it right away.
- `respec disable <skill> [-p <profile>]`: disable it, keeping files and
  source record.
- `respec update --check [<skill>] [-p <profile>]`: report which sourced
  skills have newer upstream commits. Reads only.
- `respec update [<skill>] [-p <profile>] [--yes]`: apply them. A skill with
  local edits is only overwritten after confirmation or with `--yes`. Skills
  without a source never change.

### Layers

Layers are named groups of skills inside one profile. They decide which skills
are enabled, never where skills are installed. An exclusive layer keeps at
most one skill enabled. Built-in layers (exclusive, cannot be removed, only
turned off): `design-principles` (design principles only, never component
libraries or project tokens) and `output-style` (reserved, accepts no skills
yet). Skills outside layers, and skills of a layer turned off, are additive.

- `respec layer list [-p <profile>]`
- `respec layer show <layer> [-p <profile>]`
- `respec layer add <layer> --exclusive|--additive -d <description> [-p <profile>]`
- `respec layer rm <layer> [-p <profile>]`: its skills stay in the profile.
- `respec layer use <layer> <skill> [-p <profile>]`: enable the skill in the
  layer (adding it); an exclusive layer disables the others.
- `respec layer add-skill <layer> <skill> [-p <profile>]`: add without
  changing an exclusive layer's current choice.
- `respec layer remove-skill <layer> <skill> [-p <profile>]`
- `respec layer enable <layer>` and `respec layer disable <layer>`: every
  skill of the layer.
- `respec layer on <layer>` and `respec layer off <layer>`: turn the layer's
  rules on or off.
- `respec layer repair <layer> [--keep <skill>] [-p <profile>]`: fix an
  exclusive layer with several enabled skills (for example after a hand edit):
  keep one, disable the rest. Without `--keep`, a terminal asks; other runs
  keep the first listed skill. `respec use` refuses a profile with such a
  conflict until it is repaired. A repair goes ahead while unknown entries
  (even an edited copy of a skill in that layer) wait for `respec adopt`; it
  never touches them.

### Unknown entries (adopt)

An unknown entry is anything in a folder respec owns that respec did not put
there, or a copy of a respec skill that was edited or replaced. Each one is
resolved in one of two ways:

- **add**: copy it into the active profile as an enabled skill, then link it.
- **remove**: back it up under `~/.respec/backups/<timestamp>/`, then remove it.

Unknown entries sitting exactly where a switch installs or removes a skill
block that switch until resolved. Unknown entries elsewhere only produce
warnings.

- `respec adopt`: on a terminal, asks per entry; otherwise lists them.
- `respec adopt --add <name|path>` and `respec adopt --remove <name|path>`
  (both repeatable), `respec adopt --all add|remove` for the rest.
- `respec use <profile> --unknown add|remove`: resolve the blocking entries
  during a switch (`add` goes to the profile active now).

### Undo

- `respec restore --list`: backup runs.
- `respec restore [<backup>]`: put back each folder's takeover backup (or the
  named run), remove every skill respec placed and release ownership. Entries
  the restore would overwrite are refused unless resolved with
  `--unknown add|remove` or replaced with `--overwrite` (they are backed up
  first).

### Interrupted changes

respec journals every change of several steps in `state.json`. If one was cut
short (killed, crashed), `respec status` reports it with an
`interrupted-operation` warning whose `outcome` is `pending`, and the next
command that changes skills finishes or rolls it back first (`outcome`
`finished` or `rolled-back`, with anything half made moved to a backup and
listed in `set_aside`).

- `respec recover`: finish the interrupted change now.
- `respec recover --rollback`: undo it instead where possible (a switch
  activates the previous profile again).

The first `respec use` that touches a folder backs up its full contents to
`~/.respec/backups/<timestamp>/<target>/` before taking it over. Folders respec
had to create are removed again by `respec restore` once they are empty.

## `profile.yaml`

Each profile is a folder `~/.respec/profiles/<name>/` with `profile.yaml` and
`skills/<skill>/SKILL.md...`. The commands above write it; this schema is for
reading.

```yaml
targets: [claude-code, agents] # at least one known target
skills:
  my-skill:
    enabled: true
    source: # only for skills added from git
      repo: owner/repo
      path: skills/my-skill
      ref: main
      commit: 0123abcd...
      digest: sha256:...
layers:
  design-principles: # built-in: skills and active only
    skills: [my-skill]
  my-layer:
    exclusive: false
    description: What belongs in this layer
    skills: [other-skill]
    active: true # false turns the layer's rules off
```

## Global skills

These skills are installed whatever profile is active and survive every
switch:

- **Shipped skills** (`respec` and this profile builder, `profile-maker`) are
  installed into every target, whatever the active profile's targets, so any
  agent can edit profiles. They cannot be turned off; `respec restore` removes
  them with everything else.
- **The global section** of `~/.respec/config.yaml` lists your own global
  skills. Each lives in `~/.respec/global/skills/<skill>/` and is installed
  only into the active profile's targets. No command edits this file yet; it
  is the one file edited by hand, and the next `respec use` applies it:

  ```yaml
  global:
    skills: [my-notes]
  ```

No profile skill may take the name of a global or shipped skill: `add`,
`profile install` and adopt's add refuse such a name before changing
anything. An unknown entry with such a name (for example a replaced
shipped link) can only be removed; it is backed up and respec links its
own skill there again.

## Hook scope (next phase, not built yet)

respec v1 manages skills only. When hooks arrive:

- Safety and security hooks are **global**: never switched with a profile.
- Every other hook belongs to a **profile**.
- Adding a hook will require choosing its scope (global or a named profile);
  respec will ask when neither is given. No hook command exists yet.
- respec only ever removes hooks it installed.

Until then, do not put hooks in a profile folder.

## Environment (advanced and testing)

- `RESPEC_HOME`: relocates `~/.respec`.
- `RESPEC_USER_HOME`: relocates the home the target folders resolve against.
- `RESPEC_GIT_BASE_URL`: base for `owner/repo` sources (default
  `https://github.com`).
