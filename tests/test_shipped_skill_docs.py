"""The shipped skills document the real CLI.

Every ``respec ...`` command the skills name must exist, accept the options
shown and answer ``--help``; the ``respec`` skill must name every command.
"""

from __future__ import annotations

import re
from importlib import resources
from typing import Any

import pytest
import typer.main

SKILLS = ("respec", "profile-maker")
OPTION = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")


def skill_text(name: str) -> str:
    return (
        resources.files("respec")
        .joinpath("shipped", name, "SKILL.md")
        .read_text("utf-8")
    )


def invocations(text: str) -> list[str]:
    """Every ``respec`` invocation in inline code and in code blocks."""
    found: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            command = line.split(" # ")[0].strip()
            if command == "respec" or command.startswith("respec "):
                found.append(command)
            continue
    # Inline code may wrap across lines; join the text without blocks first.
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for span in re.findall(r"`([^`]+)`", prose):
        span = " ".join(span.split())
        if span == "respec" or span.startswith("respec "):
            found.append(span)
    return found


def resolve(invocation: str) -> tuple[tuple[str, ...], Any, list[str]]:
    """(command path, command, options written after it)."""
    from respec.cli import app

    command = typer.main.get_command(app)
    path: list[str] = []
    words = invocation.split()[1:]
    rest = words
    for index, word in enumerate(words):
        if not hasattr(command, "commands"):
            break
        if word in command.commands:
            command = command.commands[word]
            path.append(word)
            rest = words[index + 1 :]
            continue
        assert word.startswith("-"), f"{invocation!r}: no command {word!r}"
        break
    else:
        rest = []
    options = [m for word in rest for m in OPTION.findall(word)]
    return tuple(path), command, options


def leaf_paths() -> set[tuple[str, ...]]:
    from respec.cli import app

    found: set[tuple[str, ...]] = set()

    def walk(command, path):
        if hasattr(command, "commands"):
            for name, child in command.commands.items():
                walk(child, path + (name,))
        else:
            found.add(path)

    walk(typer.main.get_command(app), ())
    return found


@pytest.mark.parametrize("skill", SKILLS)
def test_every_documented_command_exists_and_answers_help(run, skill):
    documented = invocations(skill_text(skill))
    assert len(documented) >= 5, documented

    for invocation in documented:
        path, command, options = resolve(invocation)
        result = run(*path, "--help")
        assert result.exit_code == 0, (invocation, result.output)
        accepted = {opt for param in command.params for opt in param.opts}
        accepted |= {opt for param in command.params for opt in param.secondary_opts}
        accepted.add("--help")
        for option in options:
            assert option in accepted, (invocation, option)
            assert option in result.output, (invocation, option)


def test_respec_skill_names_every_command():
    documented = {resolve(i)[0] for i in invocations(skill_text("respec"))}

    missing = sorted(" ".join(path) for path in leaf_paths() - documented)

    assert missing == []


def test_every_command_but_the_tui_takes_json(run):
    # The respec skill tells agents that every command except tui has --json.
    for path in leaf_paths():
        output = run(*path, "--help").output
        assert ("--json" in output) == (path != ("tui",)), path


def test_a_misspelled_command_is_caught():
    with pytest.raises(AssertionError):
        resolve("respec layer fix design-principles")


WARNING_TYPES = (
    "layer-conflict",
    "unreadable-manifest",
    "unreadable-takeover-log",
    "interrupted-operation",
)
OUTCOMES = ("finished", "rolled-back", "pending", "rebuilt")


def test_respec_skill_names_every_warning_type_and_outcome():
    text = " ".join(skill_text("respec").split())

    missing = [w for w in WARNING_TYPES + OUTCOMES if f"`{w}`" not in text]

    assert missing == []
