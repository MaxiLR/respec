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

- **Before editing any global skill, look up where it came from.** The files
  under `~/.respec/profiles/` are respec's copy, not the source. Run
  `respec profile show <profile> --json` (or `respec status --json` for the
  active profile) and read the skill's `provenance` and `source`:
  - `profile-source` or `own-source`: the skill has a `source`. Edit it
    there (the `folder`, or a checkout of the `repo` at its `path`), then run
    `respec update <skill> -p <profile>` to bring the change into the copy
    (without `-p` it looks in the active profile only). For a git source,
    commit and push the edit first: respec reads the remote, so `update`
    cannot see an edit that is only in a checkout. An edit made in the copy
    never reaches the source, and `edited: true` marks a copy that already
    differs from what was copied.
  - `original`: the skill has no `source`; the copy is the only one. Edit it
    under `~/.respec/profiles/<profile>/skills/<skill>/`.

  Never write to a source on respec's behalf. The one exception is when the
  user asks you to save a profile to its source: then follow
  [Saving a profile to its source](#saving-a-profile-to-its-source).
  `SOURCE.md` in each profile's folder repeats this per skill; respec
  generates it, so never edit it.

- Pass `--json` to read results. Every command except `tui` accepts it. JSON
  objects carry a `warnings` list; each warning has a `type`
  (`layer-conflict`, `unreadable-manifest`, `unreadable-takeover-log`,
  `interrupted-operation` or `source-missing`) and a `message`. An `interrupted-operation`
  warning's `outcome` is `finished`, `rolled-back`, `pending` or `rebuilt`
  (with `operation` `state`: `respec recover` rebuilt `state.json`). Unknown entries still waiting for a
  decision are listed under `unresolved`; entries a command resolved are
  under `resolved`. Fields that do not apply are left out; only
  `active_profile`, `previous_profile`, `same_as` and values under `restored`
  can be `null` (meaning none).
- Exit code 0 means done; 1 means refused or failed. `use`, `adopt`,
  `restore` (also `--release-only`) and `recover` then print their usual
  JSON keys plus `error` (`profile remove` prints `name` and `error`); other
  commands, and a refused combination of
  options, print the reason on stderr. A refused command changes nothing unless its
  output reports what it already did.
- Only one respec changes things at a time. A change started while another
  respec (a command, a prompt waiting for an answer, or the TUI) is changing
  things waits up to a second, then exits 1 with `another respec is running`
  and changes nothing; with `--json`, `use`, `adopt`, `restore` and `recover`
  print their usual keys plus `error`, `profile remove` prints `name`,
  `error` and `warnings`, every other command prints only
  `error` and `warnings`. Retry once the other run has finished. Commands that
  only read never wait.
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
- `respec profile show <name>`: targets (with folders), the profile's
  `source` when it has one, and the skills. Each skill has `name`, `enabled`
  and `provenance`: `profile-source` (it came from the profile's source),
  `own-source` (added locally with a source of its own, git or a folder) or
  `original` (added locally, no source). A skill with a source also has
  `source` and, when its record has a digest, `edited`: whether the copy no
  longer matches what was copied.
- `respec profile install <source> [--name <name>] [--ref <ref>]`: copy a
  whole profile folder (with `profile.yaml` and `skills/`). `<source>` is a
  local folder (an existing local folder wins), `owner/repo[#path]` or a git
  URL `[#path]`; `--ref` is for git only. The profile remembers that source
  (`source` in `profile.yaml` and in the `--json` output, next to `name` and
  `path`), and every installed skill gets a source pointing into it, with a
  digest, unless it carries a git source of its own. respec only ever reads
  the source and never writes to it; `respec update` brings its changes in.
  A folder inside `~/.respec` is refused: it holds respec's own copies, never
  a source. A skill folder of the source that is a symlink must point inside
  the source, for a folder as for a repository.
- `respec profile diff <name>`: how respec's copy of the profile differs
  from the profile's source. Reads only: it changes nothing and never waits.
  `--json` gives `profile`, `path`, `source` (plus `latest` for git),
  `matches` and the lists `only_in_copy` (`skill`, `path`, its own `source`),
  `edited` (`skill`, `path`, `files` with `added`, `changed` and `removed`;
  `changed_in_source` or `not_from_source` when true), `carried` (same files
  as the source, not recorded yet), `changed_in_source`, `only_in_source`
  (`skill`, `enabled`), `gone_from_source` (`skill`, `path`, `modified`) and
  `local_state` (`enabled`, `targets`, `layers`: what `profile.yaml` says
  differently; it stays local and does not count for `matches`). A profile
  without a source gives only `profile` and `path`; a source folder that is
  gone gives a `source-missing` warning and `source_missing: true` in
  `source`; any other problem gives `error` there and exit code 1. See
  [Saving a profile to its source](#saving-a-profile-to-its-source).
- `respec profile remove <name>`: remove a profile that is not active. Nothing
  is deleted: its folder (`profile.yaml` and its skills) moves to
  `~/.respec/removed-profiles/<timestamp>/<name>/`, reported as `backup`; move
  it back to `~/.respec/profiles/<name>/` to restore it. Refused for the active
  profile or one whose skills are still linked (`respec use <other>` first,
  or `respec restore`) and while an interrupted change waits (`respec recover`
  first). Profile names are case-sensitive.
- `respec use <profile> [--unknown add|remove]`: activate a profile.
- `respec status`: active profile, its targets, and the managed skills in
  each folder respec owns (each marked by `origin`: `profile`, `shipped` or
  `global`), plus the unknown entries (`unresolved`). A skill with `origin`
  `profile` also has `provenance`, `source` and `edited`, as in
  `respec profile show`.
- `respec tui` (or `respec` alone on a terminal): the terminal UI.

### Skills

- `respec add <source> [-p <profile>] [--ref <ref>]`: add a skill and enable
  it. `<source>` is a local folder holding `SKILL.md` (an existing local
  folder wins), `owner/repo[#path]`, or a git URL `[#path]`. A repository
  path without `SKILL.md` adds every skill folder directly in it (or in its
  `skills/` folder). Git sources record their origin (repo, path, ref,
  resolved commit, digest). A local folder is recorded as the skill's source
  too (its absolute path and a digest of the copy; `source` in the `--json`
  output). respec copies from that folder and never writes to it. Symlinks in
  it must point to files inside it, as for git. `.git` and `.DS_Store`
  entries are never copied from any source and never count as content: not
  as an update, not as an edit and not in `respec profile diff`.
  - A skill inside the profile's own source (a folder under its `skills/`,
    or the same repository path) is refused and nothing changes: list the
    skill in the source's `profile.yaml` and run `respec update`, which
    adds it.
  - A folder inside `~/.respec` or inside a target folder (a link respec
    installed, or a skill sitting in a target folder) is one of respec's
    copies or an installed skill, not a source: the skill is added without
    a `source`, so its `provenance` is `original`.
- `respec remove <skill> [-p <profile>]`: remove a skill and delete its files.
- `respec enable <skill> [-p <profile>]`: enable it; an active profile links
  it right away.
- `respec disable <skill> [-p <profile>]`: disable it, keeping files and
  source record.
- `respec update --check [<skill>] [-p <profile>]`: report which sourced
  skills have an update: a newer upstream commit, or a source folder whose
  files differ from what was copied. A skill that came from the profile's
  source (`profile-source`) has an update only when its files in that source
  differ from what was copied, also for git: a new commit that did not touch
  it is no update, so `update --check` and `respec profile diff` agree, and
  `current` and `latest` may then differ while `update_available` is false.
  Reads only. Each row gives `skill`,
  `update_available` and `modified` (the profile's copy was edited), with
  `current` and `latest` commits for git or `folder` for a source folder.
  With no skill named and a profile that has a source, it also compares the
  skill lists: a skill that came from the profile's source and is no longer
  listed there has `gone: true`, and a skill listed there that the profile
  lacks gets a row with `new: true` and `enabled` (its starting state). The
  output then has a top-level `source` (the profile's source; `latest` for
  git).
- `respec update [<skill>] [-p <profile>] [--yes]`: apply them (a source
  folder is copied again). A skill with local edits is only overwritten after
  confirmation or with `--yes`; with `--json` it is skipped. Each row's
  `result` is `updated`, `up-to-date`, `skipped-local-edits`, `source-missing`
  or `error`. A skill from the profile's source whose files did not change
  there is `up-to-date` and is never asked about or overwritten, also when
  its copy was edited (only its recorded commit follows the source's).
  `update` never changes the files of a skill without a source;
  it only gives such a skill a source when it adopts it (`adopted`, below).
- `respec update` with no skill named also follows the profile's own source:
  it adds the skills that are new there (`result` `added`, with `enabled`:
  the state the source's `profile.yaml` gives, as a starting state only) and
  removes the skills that came from it and are gone (`result` `removed`, with
  `gone: true`; the folder is deleted as `respec remove` does). A gone skill
  with local edits is removed only after confirmation or with `--yes`; with
  `--json` it is skipped (`skipped-local-edits` with `gone: true`). Skills
  added by hand, with their own source or without one are never removed, a
  new skill named like a shipped or global skill is refused (`error`), and an
  update never changes whether an existing skill is enabled, nor layers or
  targets.
- If the source lists fewer skills for a while (for example another branch
  is checked out in a source folder), `update` removes the missing ones;
  a later update adds them again in the state the source gives them, so
  whether they were enabled locally, and their layer, is lost.
- `respec update` with no skill named also adopts a skill whose copy holds
  exactly the files the profile's source now holds for it (someone carried
  it there): nothing is copied or asked, the skill's source then points into
  the profile's source with a digest, and its `result` is `adopted`. Files
  that differ are never adopted.
- A profile source that cannot be read changes nothing: no skill is added or
  removed and its skills stay as they are. A folder that is gone or has no
  `profile.yaml` gives a `source-missing` warning without `skill`, and the
  top-level `source` has `source_missing: true` (`--check`) or `result`
  `source-missing`; any other problem gives `error` there and the command
  fails.
- A source folder that is gone or no longer holds `SKILL.md` changes nothing
  and is not a failure: the skill keeps its files, the other skills still
  update, and the output gives a `source-missing` warning (`profile`, `skill`,
  and `folder` unless the skill is a new one that was not copied yet). Its
  row has `source_missing: true` (`--check`) or `result`
  `source-missing` (`update`), with the same `message`.

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
listed in `set_aside`). While it waits, the entry its step in flight was
changing is listed under the warning's `in_flight`, not as an unknown entry;
recovering settles it.

- `respec recover`: finish the interrupted change now.
- `respec recover --rollback`: undo it instead where possible (a switch
  activates the previous profile again).
- If every command fails with "invalid state file" (for example after a power
  loss), run `respec recover`: it keeps the damaged `state.json` in a backup
  and rebuilds it from disk (`operation` `state`, `outcome` `rebuilt`). No
  profile is active afterwards; entries it cannot recognise as respec's are
  unknown entries. Nothing is deleted. If it could not find a folder's
  takeover record, a bare `respec restore` refuses: name the run with
  `respec restore <backup>` (`respec restore --list` marks takeover runs), or
  run `respec restore --release-only` to let go of the folders without putting
  anything back (only what it can verify as respec's is removed).
  A `state.json` or `takeovers.json` from a newer respec is never rebuilt or
  rewritten. An unreadable `takeovers.json` is reported
  (`unreadable-takeover-log`) and moved to a backup run before respec writes a
  new one.

The first `respec use` that touches a folder backs up its full contents to
`~/.respec/backups/<timestamp>/<target>/` before taking it over. Folders respec
had to create are removed again by `respec restore` once they are empty.

## Saving a profile to its source

respec never writes to a profile's source: changes only flow from the source
to respec's copy. To save local work (skills added or edited in the copy) to
the source, you carry it there and respec then records it:

1. Run `respec profile diff <name> --json`. If there is no `source`, or
   `matches` is true, there is nothing to save.
2. Apply each difference in the source (the `folder` under `source`, or a
   checkout of its `repo`, under its `path` if it has one):
   - `only_in_copy`: copy the folder at `path` to `skills/<skill>/` in the
     source and add the skill to the source's `profile.yaml`
     (`<skill>: {enabled: true}`). If it has a git `source` it should keep
     following, also record that `source` (`repo`, `path`, `ref`) in the
     entry; a `folder` source is never read from the source's `profile.yaml`.
   - `edited`: copy the `added` and `changed` files from `path` to
     `skills/<skill>/` in the source and delete the `removed` ones there
     (a path ending in `/` is an empty folder). With `changed_in_source` or
     `not_from_source`, the source has content of its own: merge instead of
     overwriting, and ask the user when unsure.
   - `local_state` stays local. Change `enabled`, `targets` or `layers` in
     the source's `profile.yaml` only when the user asks for it.
   - `changed_in_source` and `only_in_source` need nothing in the source:
     `respec update` brings them into the copy.
   - `gone_from_source`: the source no longer lists the skill, so
     `respec update` removes it from the copy. With `modified: false` that
     needs nothing. With `modified: true` the copy holds edits that the
     removal deletes: ask the user whether to keep them. To keep them, put
     the skill back in the source (copy the folder at `path` to
     `skills/<skill>/` there and list it in the source's `profile.yaml`);
     otherwise it is removed in step 5.
3. Let the user review the changes in the source and commit them there (for
   a git source: commit and push, as respec reads the remote).
4. Run `respec update -p <name> --json`. Always pass `--json` here: without
   it `update` asks before it overwrites or removes an edited copy, and
   without a terminal that question aborts the update and rolls it back.
   Read each row's `result`:
   skills you carried over with identical files are `adopted`, and nothing
   else is needed for them.
5. A row with `skipped-local-edits` is a copy that still differs from the
   source and was left alone: a skill you merged in the source (the merged
   files are not the copy's), or with `gone: true` a skill that is gone from
   the source and was edited in the copy. Finishing overwrites that copy
   with the source's files, or deletes it when it is gone. Name these skills
   to the user, and only after the user agrees run
   `respec update -p <name> --yes --json`.
6. A skill listed with `not_from_source` that you merged in the source is
   not updated from it: its copy follows its own source or none. Only after
   the user agrees, run `respec remove <skill> -p <name>` and then
   `respec update -p <name> --json`, which adds the source's version, in the
   state the source gives it.
7. Run `respec profile diff <name> --json` again and confirm that `matches`
   is true.

A skill that came from the source and is removed locally with
`respec remove` comes back on the next `respec update`. To keep it out,
disable it (`respec disable <skill>`) or remove it in the source.

## `profile.yaml`

Each profile is a folder `~/.respec/profiles/<name>/` with `profile.yaml` and
`skills/<skill>/SKILL.md...`. The commands above write it; this schema is for
reading. Beside it respec keeps a generated `SOURCE.md` (the profile's source
and each skill's provenance and source), written again on every save. It is
not a skill and is never installed into a target.

```yaml
targets: [claude-code, agents] # at least one known target
source: # optional: where `profile install` got the profile
  folder: /absolute/path/to/profile # or repo, path, ref, commit as below
skills:
  my-skill:
    enabled: true
    source: # a skill added from git
      repo: owner/repo
      path: skills/my-skill
      ref: main
      commit: 0123abcd...
      digest: sha256:...
  other-skill:
    enabled: true
    source: # a skill added from a local folder
      folder: /absolute/path/to/other-skill
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
