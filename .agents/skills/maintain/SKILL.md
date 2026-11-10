---
name: maintain
description: Checklist for changing the respec codebase. Use it whenever you add, change or remove anything in this repository (a command, an option, JSON output, a warning, a message, TUI behavior, a file format, the install steps), before you call the change done. Its main job is to make you check whether the shipped skills and the other documents still describe the program.
---

# Maintaining respec

respec ships documents that agents and users rely on to drive it. A change to
the program that leaves them stale is an unfinished change. After every change,
go through the list below and update what the change touched.

## 1. The shipped skills (always check these)

respec installs two skills of its own into every target folder whenever a
profile is active. Agents on users' machines read them instead of the code:

- `src/respec/shipped/respec/SKILL.md`: the reference for every command, its
  options, the `--json` output, the warning types and outcomes, the
  `profile.yaml` format, global skills and the environment variables.
- `src/respec/shipped/profile-maker/SKILL.md`: the interview that builds a
  profile through the CLI.

For each change, ask:

- Did a command, subcommand, argument or option appear, change or go away?
- Did any `--json` key, value, warning type, outcome or error change?
- Did the meaning of a command change (what it refuses, asks, backs up, or
  leaves behind)?
- Did `profile.yaml`, `config.yaml`, the targets or an environment variable
  change?
- Does `profile-maker` still use commands and options that exist, in an order
  that still works?

If any answer is yes, edit the shipped skill in the same change. Read the
section you touch in full; do not only patch one line. Keep the frontmatter
`name` equal to the folder name.

`tests/test_shipped_skill_docs.py` catches some drift (unknown commands and
options, a command or warning type the `respec` skill does not name). It does
not check prose, JSON examples or behavior, so passing tests do not prove the
skills are current.

## 2. The other documents

- `README.md`: the overview: features, quick start, the command table and the
  TUI keys. Keep it short.
- `docs/reference.md`: the full behavior of every command, the `--json`
  vocabulary and the environment variables. Detail goes here, not in the
  README.
- `.agents/skills/install/SKILL.md`: when installing, running or the project
  layout changes (`pyproject.toml` name or entry point, `uv` usage).
- `docs/assets/tui-demo.svg`: the animated picture at the top of the README. When
  the TUI's look or keys change, regenerate it with
  `uv run python scripts/make_tui_demo.py` and look at the result.
- This file: when the list of documents to check changes.
- Help text and messages in `src/respec/cli.py` and `src/respec/messages.py`:
  user-facing text says "skill", never "item".

## 3. The repository's own skills

`.agents/skills/` holds the skills for people working in this repository
(`install`, `maintain`). `.claude/skills` is a symlink to that folder, so both
Claude Code and harnesses that read the `.agents` standard find the same
skills. To add a repository skill, add its folder under `.agents/skills/`;
nothing else is needed. Do not replace the symlink with a real folder.

These are separate from the shipped skills: repository skills are found only
by an agent started inside a checkout; shipped skills are installed by respec
on the user's machine.

## 4. Checks before you call it done

```sh
uv run pytest
uv run black --check src tests
npx prettier --check README.md "docs/**/*.md" "src/respec/shipped/**/*.md" ".agents/skills/**/*.md"
```

Behavior changes need a test that fails first. In your report, say which
documents you updated and which you checked and left alone.
