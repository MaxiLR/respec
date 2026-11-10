# respec reference

The full behavior of every command. For an overview, see the [README](../README.md).

## Commands

```sh
respec               # open the TUI (also: respec tui)
respec profile new work --target claude-code --target agents
respec use work      # switch: remove the previous profile's skills, link this one's
respec status        # active profile, targets and managed skills per folder
respec profile show work          # targets, the profile's source and where each skill came from
respec add ./my-skill [-p work]   # copy a skill folder (with SKILL.md) into a profile; the folder is its source
respec disable my-skill [-p work] # stop linking it; files and metadata stay
respec enable my-skill [-p work]
respec remove my-skill [-p work]  # drop it from profile.yaml and delete its folder
respec adopt [--add|--remove <entry>] [--all add|remove]
respec restore [<backup>] [--list] [--unknown add|remove] [--overwrite] [--release-only]
respec recover [--rollback]       # finish (or roll back) an interrupted change
respec add owner/repo[#path] [--ref main] [-p work]  # fetch skill(s) from git
respec update --check [-p work]   # which sourced skills have an update; skills new in or gone from the profile's source
respec update [my-skill] [-p work] [--yes]  # apply; --yes overwrites (or removes) locally edited copies
respec profile install ./profile-folder [--name mine]    # copy a whole profile and remember its source
respec profile install owner/repo[#path] [--name mine] [--ref main]  # the same from git
respec profile diff mine          # how respec's copy differs from the profile's source; reads only
respec profile remove old         # move a profile that is not active to a backup
```

`add`, `remove`, `enable` and `disable` change the active profile unless `-p`
names another. When the changed profile is active, its target folders are
refreshed right away. Every command except `tui` accepts `--json`.

## Skills from a local folder

`add <folder>` copies the folder into the profile and records it as the
skill's source in `profile.yaml`: `folder` (the absolute, resolved path, also
when a relative one was given) and `digest` (a digest of the copied files).
`--json` gives the same record under `source`. respec only ever reads the
folder: it is never written, moved or deleted.

Two kinds of folder are not taken as a source:

- A folder inside the `skills/` folder of the profile's own source is refused
  and nothing changes. Recorded with a source there, the skill would count as
  one that came from the profile's source, and the next `update` would remove
  it as gone, since the source does not list it. List the skill in the
  source's `profile.yaml` and run `respec update`, which adds it. The same
  holds for `add owner/repo#<path>` naming a skill inside the profile's own
  git source.
- A folder inside respec's own data (`~/.respec`) or inside a target folder
  (such as a link respec installed in `~/.claude/skills`, which resolves into
  respec's copy) is one of respec's copies or an installed skill. The skill
  is added, but no source is recorded: it is `added locally, original`, and
  `--json` has no `source`.

`.git` and `.DS_Store` entries, at any depth, are never copied from a source
(a folder or a repository) and never count as its content: they are left out
of every digest. So a checkout given as a source does not bring its `.git`
along (a real folder named `.git` inside a source skill does not arrive in
the copy either), a commit there that changes no file is no update, and a
`.DS_Store` that the Finder writes into the source or into the copy is
neither an update nor an edit. A digest recorded by an earlier respec, when
those entries still counted, stays valid as long as the copy still matches
it.

A `.git` entry inside respec's copy of a skill (a file or a folder, at any
depth) is another matter: no source put it there, so it is yours, for example
from `git init` in the copy. It counts as a local edit wherever respec asks
whether a copy was edited: the skill is `edited` in `profile show` and
`status` and `modified` in `update --check`, `profile diff` lists the entry
under the skill's `edited` files as `added` (a folder as `.git/`), the copy
is never adopted, and `update` replaces the skill, or removes it when it is
gone from the profile's source, only after confirmation or with `--yes`
(`--json` skips it as `skipped-local-edits`). Only then is the `.git` entry
deleted with the rest of the copy.

`update --check` reports an update when the folder's files differ from what
was copied, and `update` copies the folder again and records the new digest.
The rules are those for git sources: a copy that was edited in the profile is
only overwritten after confirmation or with `--yes` (with `--json` it is
skipped), the swap is journaled, and symlinks in the folder must point to
files inside it (they are copied as plain files; links to folders and links
that leave the folder are refused, by `add` as well).

A source folder that is gone, or that no longer holds `SKILL.md`, is reported
and changes nothing: the skill keeps its files, the other skills are still
updated and the command does not fail. The text output says `source missing`;
`--json` gives a `source-missing` warning, and the skill's row has
`source_missing: true` (`update --check`) or `result: source-missing`
(`update`), each with the `message`. A source names a path on this machine, so
a profile moved to another machine reports its folder sources as missing.

In `--json`, a row of `update --check` has `skill`, `update_available` and
`modified`, plus `current` and `latest` (commits) for a git source or `folder`
for a folder source, and `error` when the check failed. A `source-missing`
warning for a skill that is new in the profile's source and could not be
copied (its folder went away while the update ran) has no `folder`. A row of `update` has
`skill`, the same source fields and `result`: `updated`, `up-to-date`,
`skipped-local-edits`, `source-missing` or `error`. A profile that has a source
of its own adds rows and results to both: see
[A profile's source](#a-profiles-source) and
[Comparing a profile with its source](#comparing-a-profile-with-its-source).

## Skills from git

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
command (`GIT_SSH_COMMAND`, `GIT_SSH` or `core.sshCommand`). Each git command
stops after `RESPEC_GIT_TIMEOUT` seconds (default 120); http transfers slower
than 1 KB/s for 30 seconds, and ssh connections not made within 15 seconds,
fail sooner. A source `repo`
must be `owner/repo`, `user@host:path` or an https, http, ssh or git URL; local
paths and other git transports are refused.

## A profile's source

`profile install <source>` copies a whole profile: a folder holding
`profile.yaml` and `skills/<skill>/SKILL.md` for every skill that file lists.
The source is a local folder, `owner/repo[#path]` or a git URL with an
optional `#path`; an existing local folder wins, and `--ref` only applies to
git. The profile is named after the folder (or the repository) unless `--name`
is given. respec only ever reads the source: it is never written, moved or
deleted, and changes only flow from the source to respec's copy. A folder
inside respec's own data (`~/.respec`, for example another profile's folder)
is refused: what is there is respec's copy, never a source. A
`skills/<skill>` entry of the source that is a symlink must point inside the
source, for a folder as for a repository; one that leaves it is refused
(`profile install` fails, `update` gives that skill `result: error`).

The profile remembers where it came from: `profile.yaml` gets a top-level
`source`, either `folder` (the absolute, resolved path) or `repo`, `path`,
`ref` and `commit` (`path` and `ref` only when given). `--json` gives `name`,
`path` and that `source`. Each installed skill gets a source that points into
the profile's source, with a digest of the copied files: `folder`
(`<profile folder>/skills/<skill>`) and `digest`, or `repo`, `path`
(`[<profile path>/]skills/<skill>`), `ref`, `commit` and `digest`. So
`update --check` and `update` cover these skills too. For them an update is
decided by files, not by commits, for git as for a folder: the profile's
source is read once, and a skill has an update only when its files there
differ from what was copied, which is what `profile diff` reports. A skill
whose files did not change in the source is `up-to-date` and is never asked
about or overwritten, also when its copy was edited; for git only its
recorded `commit` follows the source's (so `current` and `latest` of
`update --check` can differ while `update_available` is false). A skill whose
files changed is copied from the source as it was read, and is asked about
only when the copy was edited. A skill whose entry in the
source's `profile.yaml` carries its own git source keeps that one, and updates
from there (without a recorded digest its first `update` asks before
overwriting). A `folder` source written in the source's own `profile.yaml`
(for a skill or for the profile) is never trusted, as it would make a later
update copy from whatever local path it names: it is ignored and the skill
gets a source inside the profile's source.

With no skill named, `update --check` and `update` also compare the profile's
skills with the ones its source lists now:

- A skill the source lists and the profile does not have is **new**.
  `update --check` reports it (`new in the source`; a row with `skill`,
  `new: true` and `enabled`). `update` copies it into the profile, enabled or
  disabled as the source's `profile.yaml` says (`result: added`, with
  `enabled` and its `folder` or, for git, its commit as `current`). That is
  only its starting state: afterwards only respec's copy tracks whether it is
  enabled. A name that a shipped or global skill has is refused as `add` does
  (`result: error`; the other skills are still handled, and the command
  fails).
- A skill whose recorded source points into the profile's source and that the
  source no longer lists is **gone**. `update --check` reports it as
  `gone from the source` (its row has `gone: true` and `modified`), also
  when the skill is named. `update` with no skill named
  removes it as `remove` does: it leaves `profile.yaml` and its layers, its
  links go and its folder is deleted (`result: removed`, with `gone: true`).
  A copy that was edited in the profile is not deleted silently: `update`
  asks first, `--json` skips it (`result: skipped-local-edits`, with
  `gone: true`) and `--yes` removes it. Skills you added yourself, skills
  with a source of their own and skills without a source are never removed
  this way.
- An update never changes whether an existing skill is enabled, and never
  changes the profile's layers or targets, whatever the source's
  `profile.yaml` says. A removed skill only leaves the layer that listed it.
- If the source lists fewer skills for a while (for example another branch is
  checked out in a source folder), `update` removes the missing ones. A later
  update adds them again in the state the source gives them, so whether they
  were enabled locally, and their layer, is lost.

`--json` of both commands then has a top-level `source`: the profile's
`source` record, as saved after an `update` (for git, `commit` is the commit
the skill list was last read at), plus `latest` in `update --check` for git.
Naming a skill (`update <skill>`) only checks or updates that skill: nothing is
added or removed and `source` is left out. A named skill that is gone from the
profile's source is only reported, for a folder source as for git: its row
has `gone: true`, `result: source-missing` and a `message` that says so, with
a `source-missing` warning, the command succeeds, and `update` with no skill
named is what removes it. A profile without a `source` in its `profile.yaml`
behaves as before.

A profile source that cannot be read is reported and changes nothing: no skill
is added or removed, and the skills that come from it are left as they are
(skills from other sources still update). A folder that is gone or no longer
holds `profile.yaml` is reported like a missing skill folder and is not a
failure: the text output says `source missing`, `--json` gives a
`source-missing` warning without `skill`, and `source` has
`source_missing: true` (`update --check`) or `result: source-missing`
(`update`) with the `message`; the rows of its skills say the same, each
with its own warning. Anything
else (a repository that cannot be fetched, a `profile.yaml` that is not valid,
a listed skill without its folder) is an error: `source` and the rows of its
skills have `error` (`update`: `result: error`), and the command fails. An
invalid `profile.yaml` of a git source is named by the source and the file's
path in it (`profile.yaml in owner/repo#path@ref`), not by a temporary path.

Adding and removing is journaled with the rest of the update: an interrupted
`update` either finishes or is rolled back as a whole, and a rollback removes
only the skill folders that run made.

## Comparing a profile with its source

`profile diff <name>` shows how respec's copy of a profile differs from the
profile's source. It only reads: nothing changes in respec's data, in the
target folders or in the source, and it never waits for another respec. It is
made for carrying local work into the source by hand (or by an agent): respec
itself never writes to the source, so saving a profile to its source means
copying the listed folders and files there yourself, then running `update`.

A skill has one of three origins, read from the sources `profile.yaml`
records: it came from the profile's source (its source points into it), it was
added here with a source of its own (git, or another folder), or it was made
here and has no source.

`--json` gives `profile`, `path` (the copy's folder) and `source`: the
profile's `source` record, plus `latest` (the commit that was read) for git.
When the source was read it also gives `matches` (whether the lists below are
all empty) and:

- `only_in_copy`: skills the source does not list and that did not come from
  it. Each has `skill`, `path` (the absolute path of its folder in the copy)
  and its own `source` when it has one. Copy the folder to
  `skills/<skill>/` in the source and list the skill in the source's
  `profile.yaml`, with that `source` (git only) if it should keep following
  it.
- `edited`: skills both have whose files differ in the copy. Each has
  `skill`, `path` and `files`: the paths `added`, `changed` and `removed` in
  the copy, relative to what was copied (an empty folder is listed as
  `path/`). A `.git` entry in the copy is listed as `added` (a folder as
  `.git/`) and makes the skill `edited` by itself; it is not part of the
  skill, so do not copy it into the source. `changed_in_source: true` means the source changed too since the
  skill was copied; `not_from_source: true` means the copy never came from
  the source (a skill of the same name was added here). In both cases the
  files are listed against what the source holds now.
- `carried`: skills whose copy holds exactly what the source holds, which
  `profile.yaml` does not record yet; `update` records it.
- `changed_in_source`: skills whose files changed in the source since they
  were copied, with no local edits; `update` brings them in.
- `only_in_source`: skills the source lists and the copy lacks, with
  `enabled`; `update` adds them. A skill that came from the source and was
  removed here with `remove` is listed here and comes back on the next
  `update`: to keep it out, disable it instead, or remove it in the source.
- `gone_from_source`: skills that came from the source, which no longer lists
  them, with `path` and `modified` (the copy was edited); `update` removes
  them, an edited one only after confirmation or with `--yes` (`--json` skips
  it), as that deletes the edits.
- `local_state`: what the copy's `profile.yaml` says differently from the
  source's. `enabled` lists the skills both have that are enabled on one side
  only (`skill`, `copy`, `source`), `targets` (only when they differ) gives
  both lists as `copy` and `source`, and `layers` lists each layer that
  differs (`layer`, with its `copy` and `source` definitions, one of them left
  out when only the other has it). This is local state: an update never
  changes it, it does not count for `matches`, and it only belongs in the
  source when you decide so.

Skills are compared by their files, not by commits: a git source with new
commits that did not touch a skill is not a difference. A skill that follows
the same git source of its own in the copy and in the source's `profile.yaml`
is not compared.

The text output says the same, one section per list, and
`Profile '<name>' matches its source <source>` when nothing differs. A profile
without a source says so and succeeds (`--json`: `profile` and `path` only). A
source folder that is gone or has no `profile.yaml` is reported and is not a
failure: `source` has `source_missing: true` and `message`, with a
`source-missing` warning (`profile`, `folder`). Anything else that keeps the
source from being read gives `error` in `source` and the command fails.

After a skill was carried into the source with identical files, `update`
(with no skill named) **adopts** it without asking: nothing is copied, the
skill's source now points into the profile's source with the digest of its
files (replacing a source of its own, if it had one), whether it is enabled
stays as it is, and its row has `result: adopted`. This covers a skill that
was only in the copy, and a skill edited in the copy whose edits are now in
the source. Files that differ are never adopted, nor is a copy that holds a
`.git` entry: an edited skill from the
source is still only overwritten after confirmation or with `--yes`, and a
skill that did not come from the source is left alone. The change is
journaled with the rest of the update. `profile diff` then no longer lists
the skill.

So after merging a skill in the source (its files there are then neither the
copy's nor what was copied), `update --json` reports `skipped-local-edits`
and `update` without a terminal cannot ask and is rolled back: only
`update --yes` finishes, by overwriting the copy. The same holds for a skill
that is gone from the source and was edited in the copy, which `--yes`
deletes. A merged skill that did not come from the source
(`not_from_source`) is not updated from it at all: removing it with `remove`
and running `update` adds the source's version. The shipped `respec` skill
gives agents this procedure step by step, each of these steps only after the
user agrees.

## Finding a skill's true source

The files under `~/.respec/profiles/` are respec's own copy. A skill that has
a source must be edited there, not in the copy: respec never writes to a
source, so an edit made in the copy never reaches it. After editing the
source, `respec update <skill> -p <profile>` brings the change into the copy
(without `-p` only the active profile is looked at). For a git source the edit
must be committed and pushed first, as respec reads the remote. When the copy
was edited too, that update would overwrite its edits: `update` asks first
(without a terminal the question aborts the update), `update --json` skips
the skill as `skipped-local-edits`, and `update --yes` overwrites the copy.

Each skill of a profile has a provenance, derived from the sources
`profile.yaml` records (nothing more is stored):

| `provenance`     | In text                     | Meaning                                                        | Where to edit                         |
| ---------------- | --------------------------- | -------------------------------------------------------------- | ------------------------------------- |
| `profile-source` | `from the profile's source` | Its source points into the profile's source.                   | At its `source`, then `update`.       |
| `own-source`     | `added locally`             | Added here with a source of its own (git, or another folder).  | At its `source`, then `update`.       |
| `original`       | `added locally, original`   | Added or made here without a source; the copy is the only one. | In the copy, under `skills/<skill>/`. |

A skill with a source is also flagged `edited` when its files no longer match
the digest of what was copied, or when the copy holds a `.git` entry. A source
record without a digest cannot be
judged, so the flag is then left out.

`profile show <name>` prints the profile's source (`Source: ...`) and, per
skill, the label, `, edited` when flagged, and the source:

```text
Profile pack  (/Users/me/.respec/profiles/pack)
Source: /Users/me/dev-setup/pack
Targets:
  claude-code  /Users/me/.claude/skills
Skills:
  tdd    enabled   from the profile's source, edited: /Users/me/dev-setup/pack/skills/tdd
  extra  enabled   added locally: owner/repo#skills/extra@main
  notes  disabled  added locally, original
```

`status` prints the same label after each skill of the active profile. With
`--json`, `profile show` gives the profile's `source` (left out when it has
none) and each skill's `provenance`, `source` (left out for `original`) and
`edited` (left out when it cannot be judged); `status` gives the same three
fields on every skill whose `origin` is `profile`. `origin` keeps its meaning
(`profile`, `shipped` or `global`: who placed the skill); `provenance` says
where a profile's skill came from.

respec also keeps a generated `SOURCE.md` in the profile's folder, beside
`profile.yaml`, as a backstop for an agent that opens the folder directly. It
names the profile's source, lists each skill with its label and where to edit
it, and gives the rule above. respec writes it again every time it saves
`profile.yaml` (through a temporary file and a rename), from `profile.yaml`
alone: it does not carry the `edited` flag, which `profile show`, `status` and
`profile diff` compute when asked. Commands that only read (`profile show`,
`status`, `profile diff`, `update --check`) never write it, so a profile made
before this file existed gets one at its next change. A command that changes
things (it holds respec's lock) and `respec recover` also write it again
when they load a profile whose `SOURCE.md` does not say what `profile.yaml`
gives, for example after a change was killed between the two writes. It is not a skill: it is
never installed into a target, is not part of any skill's digest, and a
`SOURCE.md` inside a profile's source is neither copied nor read. Do not edit
it. If it cannot be written, the profile change still stands and the next save
writes it again.

## Removing a profile

`profile remove <name>` deletes nothing: it moves the profile's folder
(`profile.yaml` and its skills) in one rename to
`~/.respec/removed-profiles/<timestamp>/<name>/` and prints that path (`backup`
with `--json`). To get the profile back, move that folder to
`~/.respec/profiles/<name>/`; `restore` never does this, and nothing prunes
`removed-profiles/`. It refuses the active profile (switch first with
`respec use <other>`, or undo respec with `respec restore`), a profile whose
skills are still linked into a target folder (possible after `respec recover`
rebuilt `state.json`), an unknown or invalid name, and an interrupted change
that still waits (run `respec recover` first); each refusal changes nothing.
Profile names are case-sensitive in every command, also on a case-insensitive
file system: `WORK` does not name the profile `work`. A kill leaves the profile
either in place or complete in its backup; the empty timestamp folder a kill
can leave is removed by the next `profile remove`.

## Switching profiles

`respec use` links every enabled skill of the profile into each of its targets'
folders (symlinks, or copies where symlinking fails) and records every created
path in `~/.respec/state.json`. A switch removes only recorded paths, from every
folder, then installs the new profile into its own targets. The first time
respec takes over a target folder it copies the folder's full contents to
`~/.respec/backups/<timestamp>/<target>/`. Installing respec changes nothing.

## Shipped and global skills

Some skills survive every switch. respec ships two of its own: `respec` (a
reference of this CLI for agents) and `profile-maker` (a guided interview that
builds a profile through the CLI). Whenever a profile is active they are linked
into every registered target, whatever the profile's targets, so any agent can
edit profiles; a switch therefore takes over all target folders. There is no
opt-out, and `respec restore` removes them with everything else, along with
any folders respec created for them that are empty again. Your own
global skills are listed in `~/.respec/config.yaml`, each in
`~/.respec/global/skills/<skill>/`, and are linked only into the active
profile's targets:

```yaml
global:
  skills: [my-notes]
```

No profile skill may take the name of a global or shipped skill: `add`,
`profile install` and adopt's add refuse such a name before changing
anything. An unknown entry with such a name (for example a replaced
shipped link) can only be removed; it is backed up and respec links its
own skill there again.

## Unknown entries

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
stderr (and in the `unresolved` list with `--json`) with a hint to run
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
already made are kept, not undone, and skills added to the profile that is
still active are linked. That includes any folder the switch already took over
and backed up: `respec use --json` always gives `backups`, `resolved`,
`linked`, `unresolved` and `warnings`, plus `error` when it failed. An add that replaces the profile's
own copy of a skill says so and names the backup of the previous copy. If an
earlier run was killed while replacing a copy, its hidden
`.<skill>.respec-old`/`.respec-new` folder in the profile is removed only when
its content is held elsewhere (the live folder or a backup run); a missing live
folder is restored from it, and any other leftover is kept and reported.
`respec adopt`
resolves unknown entries at any time (`--add` or `--remove` per entry, or
`--all`).

Hidden entries (names starting with a dot, such as `.DS_Store`) are ignored:
they are never reported as unknown, never asked about and never removed by a
switch. A `.DS_Store` file inside an installed copy does not count as an edit.

## Undo

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

## Interrupted changes

Every change of several steps is recorded in a journal in `state.json` before
it changes anything, together with the one step in flight: a switch or
refresh (also an edit of the active profile), a restore, adopt, a layer
repair, linking outside a switch, `update`, `add` from git and `profile
install`. If respec is killed or crashes part way, the journal stays behind:

- `respec status` (and every other command that only reads) reports it.
- The next command that changes skills first finishes the change or rolls it
  back, and says which (`finished` or `rolled-back`):
  - A switch that had not yet removed any skill is rolled back (the previous
    profile stays active). One that had is finished, or, if the new profile
    can no longer be activated, rolled back to the previous one.
  - A restore is finished.
  - An adopt keeps every choice it completed; the entry in flight is finished
    once its copy was whole and otherwise left as it was (then it reports
    `rolled-back`).
  - An edit of the active profile, a layer repair, a local `add` and a
    `remove` are finished when `profile.yaml` was already saved, and rolled
    back when it was not; the links then match `profile.yaml` either way. A
    local `add` that is rolled back drops its copy (the source folder is never
    touched); a finished `remove` deletes the skill folder it was removing.
  - An `update` or git `add` is rolled back until `profile.yaml` records the
    new skills and finished after (a finished `update` also deletes the
    folders of the skills it removed because they are gone from the profile's
    source). A rollback only touches what that run
    made: the skills it swapped (when the folders are still the ones it
    recorded) and the skill folders it created. A folder that was there before
    is never removed.
  - A half-copied `profile install` is removed.
- `respec recover` does the same on its own; `respec recover --rollback`
  undoes the change instead where that is still possible (a switch activates
  the previous profile again; a restore that already removed skills, and the
  choices adopt completed, cannot be undone).
- While a restore waits, `respec restore` finishes that same restore (and
  `respec restore --release-only` an interrupted release) and reports what
  this run removed, restored and released; another backup is refused.
- While a change waits, `respec status` names the entry its step in flight was
  changing (for example a link a switch had just made) as part of that change,
  under the warning's `in_flight`, rather than as an unknown entry.
- In the TUI, Sync shows the interrupted change with Finish and Roll back;
  until it is resolved, Sync offers nothing else and the TUI refuses every
  change to skill folders.

Nothing is lost on the way: an entry a step left half made (a copy cut short,
or a staging folder of an adopt overwrite) is moved to a fresh backup run and
reported under `set_aside`, unless it is verifiably what that step was making,
in which case it is recorded. An `update` that already saved `profile.yaml`
removes its own `.<skill>.old` (the previous files), also when the
interruption had deleted it part way. A `.<skill>.old` that no journaled
`update` made is never used to replace a skill: like adopt's staging folders,
`update` puts it back when the skill folder is gone, removes it when its
content is verifiably in the skill folder or a backup run (renamed to
`.<skill>.dropping` first, so a delete cut short is finished by the next
update), and otherwise keeps it and refuses that skill until it is moved out
of the way. The same goes for a `.<skill>.dropping` folder (a redundant
`.old` being removed) that no journaled update recorded. A journal that
respec does not recognise, or that is malformed, is only dropped by
`respec recover --rollback`. `state.json` and `profile.yaml` are written to a
temporary file, flushed and renamed, so a kill never leaves either half
written. Each `profile.yaml` write and the journal's boundaries (a change
beginning, changing phase and ending) are also flushed to the drive itself
(`F_FULLFSYNC` on macOS); the per-skill records in between are not, which
keeps a switch fast.

After a power loss:

- `state.json` may have lost the per-skill records written since the last
  boundary. The journal is still there and the next command recovers it as
  above; links respec made but no longer records show up as unknown entries
  (`respec status`), to resolve with `respec adopt` or `respec use <profile>
--unknown remove`, which back them up first.
- If `state.json` cannot be read at all, every command stops and names
  `respec recover`. That moves the damaged file to a new backup run and
  rebuilds the record from disk: respec owns again the target folders that
  hold its links and records those links as its own; no profile is active,
  and everything else in those folders is an unknown entry. Nothing is
  deleted. Each folder's takeover (its backup run, or that the folder did not
  exist, and which folders respec created) is found again in
  `~/.respec/takeovers.json`, a log every takeover appends to and every
  restore marks as released; it is written apart from `state.json` and
  flushed to disk. A folder with no unreleased record there (taken over by an
  older respec, or the log is lost too) is marked `takeover_unknown`: a bare
  `respec restore` then refuses and changes nothing. Either name the run to
  put back, `respec restore <backup>` (`respec restore --list` marks takeover
  runs), or run `respec restore --release-only`, which lets go of every folder
  without putting anything back: it removes only the records it can verify as
  respec's (a link into its folders, or a copy with the recorded digest),
  lists the rest under `kept` (a record whose path is gone is only dropped),
  removes only folders respec recorded creating,
  and keeps every backup run. It reports this as an `interrupted-operation`
  warning with `operation` `state` and `outcome` `rebuilt`.
- A `state.json` or `takeovers.json` written by a newer respec is never
  rebuilt or rewritten: every command that needs it says so and changes
  nothing. A `takeovers.json` that cannot be read is reported
  (`unreadable-takeover-log`) and moved to a new backup run before respec
  writes a new log. `respec status` reports one too, and leaves it as it is.

## Running two at once

Only one respec changes things at a time. Every command that changes skills,
profiles, layers, takeovers or backups (`use`, `add`, `remove`, `enable`,
`disable`, `update`, the `layer` changes, `adopt`, `restore`, `recover`,
`profile new`, `profile install` and `profile remove`), and every change made
in the TUI, holds
a lock on `~/.respec/.lock` while it runs, including while it waits for an
answer at a prompt (the answer decides part of a change that has already
started, so the lock cannot be let go in between). Another one, in another
process or another thread, waits up to a second for it, then fails with
`another respec is running`, exit code 1, and changes nothing. With `--json`
it then prints on stdout:

- `use`, `adopt`, `restore` (also `--release-only`) and `recover`: their usual
  keys, empty or as on disk (nothing was done), plus `error`;
- `profile remove`: `name`, `error` and `warnings`;
- every other command: only `error` and `warnings`.

Commands that only read (`status`, `profile list` and `show`, `layer list` and
`show`, `update --check`, `restore --list`) never wait for it, and while
another respec holds it they do not report its change as interrupted: it is
still running. The lock belongs to the running process, so the system
releases it when that process ends, also when it is killed; a kill never
leaves a stale lock behind (the journal then reports the change as
interrupted, as above). The next command that takes the lock also removes the
temporary `state.json` files such a kill can leave in `~/.respec`.

## TUI

`respec` without a command (or `respec tui`) opens a terminal UI: profiles on
the left with the active one marked, each owned target folder on the right.
Select a profile with the arrow keys or a click, then press Enter or click
**Activate**. Unknown entries in the way open a dialog with the same two
choices (add to the active profile, or back up and remove); so do entries found
in a folder the switch took over for the first time. `a` resolves unknown
entries outside a switch, `r` refreshes and `q` quits.

The arrow keys move between controls on every screen, like Tab and Shift+Tab:
Down and Right go to the next control, Up and Left to the previous one. A
control that uses an arrow itself keeps it: a text field keeps Left and Right, a
scrolled panel keeps Up and Down, and a list or a group of choices keeps them
until its first or last entry, where the next press moves on.

**Edit** (`e`) opens the selected profile: its skills grouped by layer, with a
toggle per skill and, in an active exclusive layer, a choice of one skill (or
none). Each skill shows where it came from (`from the profile's source`,
`added locally` or `added locally, original`, with `, edited` when the copy
no longer matches what was copied) and its source, as `profile show` does. **Add folder** (`a`) and **Add from git** (`g`) add skills, and
**Check updates** (`u`) marks sourced skills that have a newer commit or a
changed source folder, or that are gone from the profile's source. Git runs
in the background with a **Cancel** button (or `Esc`). Every
change goes through the same code as `respec enable`, `respec layer use` and
`respec add`, so an active profile is re-applied at once and a refused change
leaves the profile as it was. **New profile** (`n`) asks for a name and targets.
**Remove** (`d`) asks for confirmation, then moves the selected profile to a
backup as `respec profile remove` does, with the same refusals.

**⟳ Sync** (`s`) is a manual check of the setup and every profile; nothing is
watched in the background. It lists unknown entries and edited or replaced
copies (add to the active profile, or back up and remove, as `respec adopt`),
exclusive layers with several enabled skills (keep one, as `respec layer
repair`), and links respec placed that are missing, broken or out of line with
the active profile (re-apply it). Each fix is listed with its backups; with
nothing found it says everything is in sync. Shipped and global skills are marked
in the status panel and the editor; Sync expects them where `respec use` puts
them, and an entry in their place can only be removed.

## Layers

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
was. `respec layer repair` is the one exception for unknown entries: a repair
only disables skills, so when unknown entries refuse the refresh it still
saves the repair, unlinks the disabled skills and links the kept one. It only
removes links that still hold what respec placed and only links into free
paths, so an unknown entry (also an edited copy of a skill of that layer) is
never touched and waits for `respec adopt`: add keeps the edit in the profile,
remove backs it up. So a conflict and an edited copy never block each other's
fix. Other refusals (such as a missing skill folder) still leave the profile
unchanged.

## JSON output

Every `--json` output that is an object uses one vocabulary:

- `resolved`: the unknown entries a command resolved, each with its `choice`
  (`add` or `remove`), and the `profile` it went to or the `backup` it went to.
- `unresolved`: unknown entries still waiting for a decision, each with
  `name`, `path`, `kind` (`folder`, `file` or `symlink`), `targets` and
  `replaced` (an edited or replaced copy of a skill respec installed). `use`,
  `adopt`, `restore`, `status` and every command that changes skills or
  layers (`add`, `remove`, `enable`, `disable`, `update` and the `layer`
  changes) give it. A refused `use` or `restore` also lists the entries in its
  way there, including ones outside the folders respec owns.
- `backups`: the folders `use` took over, with their takeover backups.
- `warnings`: always present, empty when there is nothing to warn about. Each
  warning is an object with a `type` and a `message`. The types:
  - `layer-conflict`: an exclusive layer has several enabled skills; also
    gives `profile`, `layer`, `skills` and `fix`.
  - `unreadable-manifest`: a backup run's `manifest.json` could not be read
    during a restore, so every entry of that run was put back as the user's;
    gives its `path`.
  - `unreadable-takeover-log`: `takeovers.json` could not be read, so the
    takeovers it recorded are unknown; gives its `path`, which is in a backup
    run once respec wrote a new log (it never overwrites the damaged one).
  - `interrupted-operation`: a change that was cut short (see
    [Interrupted changes](#interrupted-changes)); also gives `operation`
    (`use`, `restore`, `adopt`, `links`, `update`, `add`, `install`, or `state`
    for a rebuilt `state.json`),
    `outcome` (`finished` or `rolled-back` when this command recovered it,
    `rebuilt` when `respec recover` rebuilt an unreadable `state.json`,
    `pending` when it still waits), `set_aside` (paths moved to a backup
    run), `profile` when it concerns one and, while it is `pending`,
    `in_flight`: the entry its step in flight was changing (part of that
    change, so not listed under `unresolved`). `respec recover --json` gives
    `active_profile`, `recovered` (whether there was anything to recover)
    and this warning.
  - `source-missing`: `update` or `update --check` found a skill's source
    folder gone or without `SKILL.md` and left the skill as it was; also
    gives `profile`, `skill` and `folder` (no `folder` for a skill that is
    new in the profile's source and was not copied yet). `update <skill>`
    gives the same warning for a named skill that is gone from the profile's
    source and was left as it was (no `folder` for a git source). For the profile's own source
    folder (gone, or without `profile.yaml`) it gives `profile` and `folder`
    and no `skill`: nothing was added or removed. `profile diff` gives that
    second form when it could not compare.
- `error`: present only when the command failed. `use`, `adopt`, `restore`
  (also `--release-only`, which adds `kept`) and `recover` then print every
  other key of their success output too, filled with what was done before the
  failure (`recover` gives `active_profile` and `recovered: false`).
  `profile remove` gives `name`, `path` and `backup` on success and `name`
  with `error` on failure, on stdout either way. Other
  commands print their error on stderr only, with one exception: refused
  because another respec is running, they print `error` and `warnings` on
  stdout (see [Running two at once](#running-two-at-once)). A refused
  combination of options (such as `restore --list --release-only`) prints its
  error on stderr only.

A field that does not apply is left out rather than given as `null`: for
example a resolved entry has `profile` only when it was added and `backup`
only when it was removed, a linked skill has no `digest`, a layer change has
`skill` only when it names one, a skill without a source has no `source`, a
source has either the git fields or `folder`,
and `restore` gives `backup` only when a backup run was named. A change of a
profile (`add`, `remove`, `enable`, `disable`, `update`) gives `active`:
whether that profile is the active one. Only these
fields can be `null`, each meaning "none": `active_profile` and
`previous_profile` (no profile), `same_as` (the folder is not shared with
another target) and a value under `restored` (that folder did not exist at
takeover). In `status`, each skill of a folder gives its `origin`: `profile`,
`shipped` (respec's own skills) or `global` (from `config.yaml`); a link is
judged by the folder it points into. A skill of a profile (in `profile show`,
and in `status` when its `origin` is `profile`) also gives its `provenance`
(`profile-source`, `own-source` or `original`), its `source` when it has one
and `edited` when that can be judged; see
[Finding a skill's true source](#finding-a-skills-true-source).

The same warnings are printed on stderr. `respec restore --list --json` prints a
bare list of backups instead: it reads no profile, so it has nothing to warn
about.

## Environment variables

Two environment variables are advanced/testing overrides, not everyday options:
`RESPEC_USER_HOME` relocates the home that target folders such as
`~/.claude/skills` resolve against, and `RESPEC_HOME` relocates respec's data
folder (default `.respec` inside that home). The test suite points
`HOME`, `RESPEC_HOME` and `RESPEC_USER_HOME` at temporary folders for every test
and fails any test that resolves a respec path under the real home.

`RESPEC_GIT_BASE_URL` (default `https://github.com`) is the base that
`owner/repo` sources resolve against, and `RESPEC_GIT_TIMEOUT` (default 120) is
the number of seconds after which a git command is stopped.
