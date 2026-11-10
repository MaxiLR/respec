---
name: profile-maker
description: Guided interview that builds a respec profile of global agent skills through the respec CLI. Use when the user wants a new respec profile, wants to turn a way of working into a profile, or asks which skills a profile should hold. Rejects project-scoped content such as component libraries.
---

# profile-maker

Build a respec profile by interviewing the user, then create it with `respec`
commands. Read the `respec` skill first for the command reference. Never write
`profile.yaml` or the profile folder by hand.

## Rules

- Ask one question at a time and wait for the answer. Offer a recommended
  answer with each question so the user can simply agree.
- Profiles hold **global** skills only: ways of working that apply in any
  project. Reject project-scoped content and say why: a project's component
  library, design tokens or theme, framework or repository conventions,
  project instructions such as `CLAUDE.md` or `AGENTS.md`, and anything that
  names one codebase. Suggest keeping it in that project instead.
- Hooks, output styles, MCP servers and settings are not part of respec v1.
  Note them for later and leave them out of the profile.
- Do not activate the new profile unless the user asks; switching replaces
  every skill of the active profile.
- Check a command's options with its `--help` (for example
  `respec add --help`) when unsure,
  and read results with `--json`.

## Interview

1. **Purpose.** What is this profile for (for example "client work",
   "writing", "experiments")? Derive a short name: letters, digits, `.`, `_`
   or `-`, starting with a letter or digit. Check it is free with
   `respec profile list --json`.
2. **Targets.** Which agents should see it: `claude-code`, `agents` (Codex,
   Pi and other `.agents` readers), `oh-my-pi`? Every enabled skill goes to
   all chosen targets. respec's own skills are always installed everywhere,
   so do not add them.
3. **Skills.** For each skill the user wants, ask where it comes from: a
   local folder holding `SKILL.md`, `owner/repo#path` or a git URL (and a
   branch, tag or commit to pin, if any). Ask whether it is global; reject it
   if it is project-scoped (see Rules). Look at what an existing profile has
   with `respec profile show <name> --json` when the user wants to start from
   one.
4. **Layers.** Should some skills be alternatives? Design principles go in
   the built-in exclusive `design-principles` layer: principles only, never
   component libraries or project tokens. For other groups ask for a name,
   whether only one may be enabled (exclusive) or any number (additive), and
   a one-sentence description of what belongs there.
5. **Enabled or not.** Which skills should start disabled (kept but not
   installed)?
6. **Confirm.** Show the plan: name, targets, skills with sources, layers,
   disabled skills. Apply only after the user agrees.

## Apply

Run these in order; stop and report on the first failure.

```sh
respec profile new <name> -t <target> [-t <target>...]
respec add <source> -p <name> [--ref <ref>]          # once per skill
respec layer add <layer> --exclusive|--additive -d "<description>" -p <name>
respec layer add-skill <layer> <skill> -p <name>     # once per member
respec layer use <layer> <skill> -p <name>           # the exclusive choice
respec disable <skill> -p <name>                     # skills to start off
respec profile show <name> --json                    # verify the result
```

`respec add` names each skill after its folder and enables it; a repository
path without `SKILL.md` adds every skill folder in it, so disable or remove
the ones the user did not ask for. Report the final `respec profile show` to
the user, and tell them `respec use <name>` activates the profile when they
are ready.
