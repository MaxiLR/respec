"""Help output speaks of skills, never of items."""

from __future__ import annotations

import re

import typer.main


def command_paths() -> list[tuple[str, ...]]:
    """Every command path of the CLI, the top-level command included."""
    from respec.cli import app

    paths: list[tuple[str, ...]] = []

    def walk(command, path: tuple[str, ...]) -> None:
        paths.append(path)
        for name, child in getattr(command, "commands", {}).items():
            walk(child, path + (name,))

    walk(typer.main.get_command(app), ())
    return paths


def test_no_help_page_says_item(run):
    paths = command_paths()
    # Guard against a walk that silently finds nothing to check.
    assert ("layer", "add-skill") in paths and ("remove",) in paths

    offenders = {}
    for path in paths:
        result = run(*path, "--help")
        assert result.exit_code == 0, (path, result.output)
        found = re.findall(r"\w*item\w*", result.output, flags=re.IGNORECASE)
        if found:
            offenders[" ".join(path) or "respec"] = found

    assert offenders == {}


def test_skill_arguments_are_named_skill_in_usage(run):
    commands = [("remove",), ("enable",), ("disable",), ("update",)]
    commands += [("layer", name) for name in ("use", "add-skill", "remove-skill")]
    for path in commands:
        usage = run(*path, "--help").output.strip().splitlines()[0]
        assert re.search(r"\bskill\b", usage, flags=re.IGNORECASE), (path, usage)
