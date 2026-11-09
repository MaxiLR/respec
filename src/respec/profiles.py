"""Profiles: self-contained folders under ``<respec home>/profiles/<name>/``.

Each profile folder holds ``profile.yaml`` and a ``skills/`` directory. The
schema of ``profile.yaml``::

    targets: [claude-code, agents]   # at least one known target, no repeats
    skills:                          # optional; mapping of skill name to entry
      my-skill:
        enabled: true                # required boolean
        source:                      # optional origin record
          repo: owner/repo           # required within source
          path: skills/my-skill      # optional
          ref: main                  # optional
          commit: 0123abcd           # optional resolved commit
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from respec.errors import RespecError
from respec.targets import known_names, registry

PROFILE_FILE = "profile.yaml"
SKILLS_DIR = "skills"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
NAME_RULE = "use letters, digits, '.', '_' or '-', starting with a letter or digit"

TOP_LEVEL_KEYS = ("targets", "skills")
SKILL_KEYS = ("enabled", "source")
SOURCE_KEYS = ("repo", "path", "ref", "commit")


class ProfileError(RespecError):
    """``profile.yaml`` is missing, unreadable or does not match the schema."""

    def __init__(self, path: Path, problems: list[str]):
        self.path = path
        self.problems = problems
        lines = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(f"invalid profile file {path}:\n{lines}")


@dataclass(frozen=True)
class Source:
    repo: str
    path: str | None = None
    ref: str | None = None
    commit: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in vars(self).items() if value is not None}


@dataclass(frozen=True)
class SkillEntry:
    enabled: bool
    source: Source | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"enabled": self.enabled}
        if self.source is not None:
            data["source"] = self.source.to_dict()
        return data


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    targets: list[str]
    skills: dict[str, SkillEntry] = field(default_factory=dict)

    def to_yaml_data(self) -> dict[str, Any]:
        return {
            "targets": list(self.targets),
            "skills": {name: entry.to_dict() for name, entry in self.skills.items()},
        }


def profiles_dir(respec_home: Path) -> Path:
    return respec_home / "profiles"


def validate_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise RespecError(f"invalid profile name {name!r}: {NAME_RULE}")


def validate_targets(targets: list[Any]) -> list[str]:
    """Return problems with a list of target names (empty when valid)."""
    problems: list[str] = []
    if not targets:
        problems.append(f"at least one target is required (known: {known_names()})")
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, str):
            problems.append(f"target {target!r} must be a string")
        elif target not in registry():
            problems.append(
                f"unknown target {target!r} (known targets: {known_names()})"
            )
        elif target in seen:
            problems.append(f"target {target!r} is listed more than once")
        else:
            seen.add(target)
    return problems


def _unknown_keys(where: str, data: dict[Any, Any], allowed: tuple[str, ...]):
    return [
        f"{where}: unknown key {key!r} (allowed: {', '.join(allowed)})"
        for key in data
        if key not in allowed
    ]


def _parse_source(where: str, raw: Any, problems: list[str]) -> Source | None:
    if not isinstance(raw, dict):
        problems.append(f"{where} must be a mapping with keys {', '.join(SOURCE_KEYS)}")
        return None
    problems.extend(_unknown_keys(where, raw, SOURCE_KEYS))
    values: dict[str, str] = {}
    for key in SOURCE_KEYS:
        if key not in raw or raw[key] is None:
            continue
        if not isinstance(raw[key], str) or not raw[key]:
            problems.append(f"{where}.{key} must be a non-empty string")
        else:
            values[key] = raw[key]
    if "repo" not in raw:
        problems.append(f"{where}.repo is required (for example 'owner/repo')")
    if "repo" not in values:
        return None
    return Source(**values)


def _parse_skill(name: Any, raw: Any, problems: list[str]) -> SkillEntry | None:
    where = f"skills.{name}"
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        problems.append(f"skill name {name!r} is invalid: {NAME_RULE}")
        return None
    if not isinstance(raw, dict):
        problems.append(f"{where} must be a mapping such as '{{enabled: true}}'")
        return None
    problems.extend(_unknown_keys(where, raw, SKILL_KEYS))
    enabled = raw.get("enabled")
    if "enabled" not in raw:
        problems.append(f"{where}.enabled is required (true or false)")
    elif not isinstance(enabled, bool):
        problems.append(f"{where}.enabled must be true or false, got {enabled!r}")
    source = None
    if raw.get("source") is not None:
        source = _parse_source(f"{where}.source", raw["source"], problems)
    if not isinstance(enabled, bool):
        return None
    return SkillEntry(enabled=enabled, source=source)


def parse_profile(name: str, folder: Path, data: Any) -> Profile:
    """Validate loaded YAML data, collecting every problem before failing."""
    file = folder / PROFILE_FILE
    if not isinstance(data, dict):
        raise ProfileError(file, ["top level must be a mapping with a 'targets' list"])
    problems = _unknown_keys("top level", data, TOP_LEVEL_KEYS)

    targets: list[str] = []
    raw_targets = data.get("targets")
    if "targets" not in data:
        problems.append(f"'targets' is required (known targets: {known_names()})")
    elif not isinstance(raw_targets, list):
        problems.append("'targets' must be a list of target names")
    else:
        problems.extend(f"targets: {p}" for p in validate_targets(raw_targets))
        targets = raw_targets

    skills: dict[str, SkillEntry] = {}
    raw_skills = data.get("skills")
    if raw_skills is None:
        raw_skills = {}
    if not isinstance(raw_skills, dict):
        problems.append("'skills' must be a mapping of skill name to entry")
    else:
        for skill_name, raw_entry in raw_skills.items():
            entry = _parse_skill(skill_name, raw_entry, problems)
            if entry is not None:
                skills[skill_name] = entry

    if problems:
        raise ProfileError(file, problems)
    return Profile(name=name, path=folder, targets=targets, skills=skills)


def load_profile(respec_home: Path, name: str) -> Profile:
    validate_name(name)
    folder = profiles_dir(respec_home) / name
    file = folder / PROFILE_FILE
    if not folder.is_dir():
        raise RespecError(
            f"profile {name!r} does not exist; create it with "
            f"'respec profile new {name} --target <target>'"
        )
    if not file.is_file():
        raise ProfileError(file, [f"{PROFILE_FILE} is missing"])
    try:
        data = yaml.safe_load(file.read_text("utf-8"))
    except yaml.YAMLError as error:
        raise ProfileError(file, [f"not valid YAML: {error}"]) from None
    return parse_profile(name, folder, data)


def list_profile_names(respec_home: Path) -> list[str]:
    folder = profiles_dir(respec_home)
    if not folder.is_dir():
        return []
    return sorted(
        child.name
        for child in folder.iterdir()
        if child.is_dir() and NAME_PATTERN.match(child.name)
    )


def create_profile(respec_home: Path, name: str, targets: list[str]) -> Profile:
    validate_name(name)
    problems = validate_targets(targets)
    if problems:
        raise RespecError("; ".join(problems))
    folder = profiles_dir(respec_home) / name
    if folder.exists():
        raise RespecError(
            f"profile {name!r} already exists at {folder}; choose another name"
        )
    profile = Profile(name=name, path=folder, targets=list(targets))
    (folder / SKILLS_DIR).mkdir(parents=True)
    text = yaml.safe_dump(profile.to_yaml_data(), sort_keys=False)
    (folder / PROFILE_FILE).write_text(text, "utf-8")
    return profile
