---
schema: 1
kind: spec
title: "respec v1: profile switching for agent skills"
revision: 2
updated: "2026-11-09T21:09:55.799226+00:00"
---

# respec: profile switcher for coding-agent setups

## Problem

Global agent skills live in several per-harness folders (`~/.claude/skills`,
`~/.agents/skills`, `~/.omp/agent/skills`). Harnesses read each other's folders
(oh-my-pi also loads `~/.agents/skills` and `~/.claude/skills`), so a setup meant for
one tool leaks into others, and copies drift: 10 of the 20 skills present in more than
one folder on the author's machine currently differ between folders.

Existing tools (rulesync, skills-supply, ai-rules-sync, agent-sync, the `skills` CLI)
sync or generate skills per tool, but none offers switchable named profiles where one
activation cleanly replaces everything the previous profile installed. oh-my-pi's own
`--profile` only covers oh-my-pi's folders and does not stop foreign providers loading.

## Proposed behavior

`respec` is a Python CLI plus a mouse-capable Textual TUI. Users keep self-contained
profiles (similar to CurseForge instances) and activate exactly one at a time. Activation
removes everything the previous profile placed in any target folder, then installs the
new profile into its own targets only. Folders that the new profile does not target
end up empty of managed content.

## User stories

- As a user, I create a profile for oh-my-pi only, activate it, and neither Claude Code
  nor the `~/.agents/skills` readers see any skill from my previous profile.
- As a user, I add a global skill from a GitHub repo to a profile in one command and
  later see whether a newer upstream commit exists, updating only when I choose.
- As a user, I disable a skill in a profile without deleting it or losing its source
  record and local edits.
- As a user, I group skills into layers; in an exclusive layer, choosing one item turns
  the others off.
- As a user, I can try respec and undo it: `respec restore` returns my folders to their
  pre-respec contents.
- As a user, when another tool drops a skill into a folder respec owns, I am offered to
  adopt it, back it up and remove it, or keep it unmanaged, and nothing is silently lost.
- As an agent, I read the shipped `respec` skill, use the CLI with `--json`, and know how
  to add skills, build profiles (via `profile-maker`), and which scope a hook belongs in.

## Implementation decisions (agreed)

1. **Profile**: self-contained folder `~/.respec/profiles/<name>/` holding
   `profile.yaml` plus content (`skills/<name>/SKILL.md…`). The folder is the source of
   truth. Profiles are independent; no inheritance or shared skill library.
2. **Targets**: each profile lists the targets it applies to.
3. **One active profile globally.** Switching removes all managed content of the previous
   profile from every folder it touched, then installs the new profile into its targets.
4. **Uniform targets**: every enabled skill in a profile goes to all of that profile's
   targets. Per-skill target restriction is excluded until a real use case appears.
5. **Ownership**: respec owns the folders of the targets it manages. Unknown entries
   found in an owned folder (before a switch, and in `status`) are listed with the
   choices add to profile / back up and remove / keep unmanaged (`respec adopt`).
6. **No import on install.** Installing creates only `~/.respec/`. The first time respec
   takes over a folder (first `respec use`), it backs up that folder's full contents to
   `~/.respec/backups/<timestamp>/<target>/`. `respec restore [<backup>]` puts a backup
   back and releases ownership. No profiles are generated from existing content.
7. **Global scope only.** Project-scoped skills are out of scope.
8. **Sources**: an item may record its origin (repo, path, ref, resolved commit). Updates
   are explicit (`update --check` shows availability; `update` applies). Items without a
   source never change. A whole profile may be installed once from a repo
   (modpack-style), after which it is owned locally. respec does not version profiles.
9. **Enable/disable** per item without deleting it.
10. **Layers**: optional named groups inside one profile, `exclusive: true|false`, with a
    `description` explaining what belongs there (read by humans and agents). Built-in
    layers: `design-principles` (exclusive; design principles only, never component
    libraries or project tokens) and `output-style` (exclusive). Built-ins can be turned
    off per profile; with layers off, a profile is a flat additive list. Layers never
    change install locations, only which items are enabled. Items outside layers are
    additive. When layers are turned off, exclusivity rules lapse.
11. **Global section** `~/.respec/config.yaml` for items that survive every switch. In
    v1 it holds respec's own skills. Global items are installed only into the active
    profile's targets, so isolation stays complete.
12. **Shipped agent skills**: `respec` (reference: CLI, `profile.yaml` schema, layers,
    sources, hook scope rule) and `profile-maker` (guided interview that builds a
    profile). Agents mutate through the CLI, not by hand-editing YAML.
13. **Stack**: Python, Textual (TUI with mouse support), Typer (CLI). Distribution
    (PyPI name such as `respec-cli`, `uv tool install`, Homebrew tap) is deferred.
14. **v1 targets**: `claude-code` → `~/.claude/skills`; `agents` → `~/.agents/skills`
    (shared by Codex, Pi, and other universal readers); `oh-my-pi` →
    `~/.omp/agent/skills`. Targets are defined in a data file modelled on the
    skills.sh agent registry (`vercel-labs/skills` `src/agents.ts`, MIT) so more can be
    added by pull request.
15. **Scope**: v1 = skills and layers. Next = output styles plus hooks.
16. **coding-setup** will be retired; respec takes over skill installation. Guards,
    `git push`, board, and instruction files are not part of respec v1 and stay with
    coding-setup until migrated separately.

### Agreed for the next phase (design recorded, not built in v1)

- Hooks have two scopes. Safety and security hooks are global (never switched). All
  other hooks belong to a profile. The `respec` skill states the rule; `respec hook add`
  requires `--global` or `-p <profile>` and asks when neither is given.
- respec only ever removes hooks it installed.

## Proposed defaults (stated in planning, not explicitly confirmed)

- Install mode: target entries are symlinks to the profile folder, with copy fallback
  when a symlink cannot be created (same approach as the `skills` CLI).
- `RESPEC_HOME` relocates `~/.respec`; target folders resolve against an overridable home
  so tests run in temporary directories.
- respec keeps its own state in `~/.respec/state.json` (active profile, every path it
  created) and never edits the `skills` CLI's `~/.agents/.skill-lock.json`.
- Command surface, to finalise in tickets: `respec use <profile>`, `respec status`,
  `respec profile new|list|show|rm`, `respec add <source|path> [-p]`,
  `respec remove <item>`, `respec enable|disable <item>`, `respec layer …`,
  `respec update [--check]`, `respec adopt`, `respec restore`, `respec` (no args) or
  `respec tui` opens the TUI. Every read command supports `--json`.

## Observable testing seams

- Temporary `RESPEC_HOME` plus temporary home directory containing fake target folders;
  assert on the resulting filesystem (links present/absent, backups written, unknown
  entries reported).
- `state.json` and `--json` command output as the machine-readable contract.
- Git sources tested against local bare repositories (`file://`), no network.
- TUI tested with Textual's `Pilot`, including mouse clicks.
- Switch scenarios: A(claude-code, agents) → B(oh-my-pi) leaves both former folders free
  of A's items; disabled items never linked; exclusive layer enforces a single enabled
  item; unknown entry triggers the adopt prompt; restore returns exact backup contents.

## Exclusions (v1)

- Output styles, hooks, instruction files (`CLAUDE.md`, `AGENTS.md`, `RULES.md`), MCP,
  settings.
- Project-scoped skills.
- Per-skill target restriction.
- Targets beyond the three listed.
- Automatic import of existing folders into profiles; automatic updates.
- Profile inheritance or a shared skill library.
- Packaging and publishing.

## Risks and open questions

- **Interrupted switch**: a crash between removal and install could leave folders half
  populated. The switch needs a journal in `state.json` so it can be resumed or rolled
  back.
- **Symlink support**: confirm oh-my-pi and Claude Code load skills through symlinked
  directories; otherwise the copy fallback becomes the default for that target.
- **oh-my-pi foreign providers**: oh-my-pi reads `~/.claude/skills` and
  `~/.agents/skills`; isolation relies on respec emptying those folders. Confirm in the
  oh-my-pi source which providers are enabled by default.
- **Running sessions**: harness sessions open during a switch may hold stale skill lists.
- **Other installers**: `coding-setup update` and `npx skills add` keep writing into owned
  folders until coding-setup is retired; detection and adopt (decision 5) mitigate this.
- **Name**: W3C ReSpec (`speced/respec`, npm `respec`) shares the name; PyPI `respec` is
  taken.
