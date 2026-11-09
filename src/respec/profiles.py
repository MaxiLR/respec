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
          digest: sha256:...         # optional hash of the files as fetched
    layers:                          # optional; named groups of skills
      design-principles:             # built-in: only items and active allowed
        items: [my-skill]
      my-layer:                      # custom layer
        exclusive: false             # required boolean
        description: What belongs    # required string
        items: [other-skill]         # optional; each skill in at most one layer
        active: false                # optional; false turns the layer's rules off

Layers only decide which items are enabled, never where they are installed.
An active exclusive layer has at most one enabled item. Items outside layers,
and items of a layer that is turned off, are plain additive items.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from respec.errors import RespecError
from respec.targets import known_names, registry

PROFILE_FILE = "profile.yaml"
SKILLS_DIR = "skills"
# ``\Z``, not ``$``: ``$`` also matches before a trailing newline.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
NAME_RULE = "use letters, digits, '.', '_' or '-', starting with a letter or digit"

TOP_LEVEL_KEYS = ("targets", "skills", "layers")
SKILL_KEYS = ("enabled", "source")
SOURCE_KEYS = ("repo", "path", "ref", "commit", "digest")
LAYER_KEYS = ("exclusive", "description", "items", "active")
BUILTIN_LAYER_KEYS = ("items", "active")

OUTPUT_STYLE = "output-style"
OUTPUT_STYLE_UNSUPPORTED = (
    "output styles are not supported yet; "
    f"the {OUTPUT_STYLE!r} layer accepts no skills until they are"
)
BUILTIN_LAYERS: dict[str, str] = {
    "design-principles": (
        "Design principles only: how interfaces should look, read and behave. "
        "Never component libraries or project tokens."
    ),
    OUTPUT_STYLE: (
        "How the agent writes its replies. Reserved: accepts no skills until "
        "output styles are supported."
    ),
}


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
    digest: str | None = None

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
class Layer:
    exclusive: bool
    description: str
    items: tuple[str, ...] = ()
    active: bool = True
    builtin: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if not self.builtin:
            data["exclusive"] = self.exclusive
            data["description"] = self.description
        if self.items or self.builtin:
            data["items"] = list(self.items)
        if not self.active:
            data["active"] = False
        return data


def builtin_layers() -> dict[str, Layer]:
    return {
        name: Layer(exclusive=True, description=description, builtin=True)
        for name, description in BUILTIN_LAYERS.items()
    }


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    targets: list[str]
    skills: dict[str, SkillEntry] = field(default_factory=dict)
    layers: dict[str, Layer] = field(default_factory=builtin_layers)

    def to_yaml_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "targets": list(self.targets),
            "skills": {name: entry.to_dict() for name, entry in self.skills.items()},
        }
        layers = {
            name: layer.to_dict()
            for name, layer in self.layers.items()
            if not (layer.builtin and not layer.items and layer.active)
        }
        if layers:
            data["layers"] = layers
        return data

    def layer_of(self, item: str) -> str | None:
        """Name of the layer listing ``item``, or ``None``."""
        for name, layer in self.layers.items():
            if item in layer.items:
                return name
        return None


def exclusivity_problems(profile: Profile) -> list[str]:
    """Active exclusive layers with more than one enabled item."""
    problems: list[str] = []
    for name, layer in profile.layers.items():
        if not (layer.exclusive and layer.active):
            continue
        enabled = [
            item
            for item in layer.items
            if item in profile.skills and profile.skills[item].enabled
        ]
        if len(enabled) > 1:
            problems.append(
                f"layer {name!r} is exclusive but has {len(enabled)} enabled skills "
                f"({', '.join(enabled)}); keep at most one enabled"
            )
    return problems


def with_enabled(profile: Profile, items: list[str], enabled: bool) -> Profile:
    """``profile`` with ``items`` set to ``enabled``, applying layer rules.

    Enabling an item of an active exclusive layer disables that layer's other
    items, so the newly enabled item becomes the layer's single choice.
    """
    skills = dict(profile.skills)
    for item in items:
        if enabled:
            layer_name = profile.layer_of(item)
            layer = profile.layers[layer_name] if layer_name else None
            if layer is not None and layer.exclusive and layer.active:
                for other in layer.items:
                    if other != item and other in skills and skills[other].enabled:
                        skills[other] = replace(skills[other], enabled=False)
        skills[item] = replace(skills[item], enabled=enabled)
    return replace(profile, skills=skills)


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


GIT_BASE_URL_ENV = "RESPEC_GIT_BASE_URL"
DEFAULT_GIT_BASE_URL = "https://github.com"
# ``owner/repo`` where neither part is ``.`` or ``..``.
REPO_SHORTHAND = re.compile(r"^(?!\.\.?/)[A-Za-z0-9_.-]+/(?!\.\.?\Z)[A-Za-z0-9_.-]+\Z")
REPO_SCP_LIKE = re.compile(r"^[\w.-]+@[\w.-]+:")
REPO_URL = re.compile(r"^(https?|ssh|git|file)://\S+\Z")


def git_base_url() -> str:
    """Base URL for ``owner/repo``; read at call time so tests can inject it."""
    return os.environ.get(GIT_BASE_URL_ENV) or DEFAULT_GIT_BASE_URL


def _repo_problem(repo: str) -> str | None:
    """Only remote repositories: 'owner/repo', ``user@host:path`` or a URL.

    ``file://`` is accepted only below a ``file://`` base URL (the injectable
    test seam), so a profile cannot point respec at local repositories.
    """
    if REPO_SHORTHAND.match(repo) or REPO_SCP_LIKE.match(repo):
        return None
    match = REPO_URL.match(repo)
    if match and match.group(1) != "file":
        return None
    base = git_base_url().rstrip("/")
    if (
        match
        and base.startswith("file://")
        and repo.startswith(base + "/")
        and "%" not in repo
        and not any(part in (".", "..") for part in repo.split("/"))
    ):
        return None
    return (
        f"source repo {repo!r} must be 'owner/repo', 'user@host:path' or an "
        "https, http, ssh or git URL (local paths, file URLs and other "
        "transports are refused)"
    )


def source_value_problem(key: str, value: str) -> str | None:
    """Why a source ``repo``, ``ref`` or ``path`` value is unsafe, or None.

    Values starting with '-' could be read by git as options, and a ``path``
    must stay inside the repository it names.
    """
    if value.startswith("-"):
        return f"source {key} {value!r} must not start with '-'"
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return f"source {key} {value!r} must not contain control characters"
    if key == "repo":
        return _repo_problem(value)
    if key == "path" and (
        value.startswith("/")
        or "\\" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        return (
            f"source path {value!r} must be a relative path inside the repository "
            "(no leading '/', no '.' or '..' parts)"
        )
    return None


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
            continue
        problem = source_value_problem(key, raw[key])
        if problem:
            problems.append(f"{where}.{key}: {problem}")
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


def _parse_layer(
    name: Any, raw: Any, skills: dict[str, Any], problems: list[str]
) -> Layer | None:
    where = f"layers.{name}"
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        problems.append(f"layer name {name!r} is invalid: {NAME_RULE}")
        return None
    builtin = name in BUILTIN_LAYERS
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        problems.append(f"{where} must be a mapping")
        return None
    allowed = BUILTIN_LAYER_KEYS if builtin else LAYER_KEYS
    unknown = _unknown_keys(where, raw, allowed)
    if builtin and unknown:
        unknown = [
            f"{problem}; exclusive and description of built-in layers are fixed"
            for problem in unknown
        ]
    problems.extend(unknown)

    exclusive: Any = True
    description: Any = BUILTIN_LAYERS.get(name, "")
    if not builtin:
        exclusive = raw.get("exclusive")
        if "exclusive" not in raw:
            problems.append(f"{where}.exclusive is required (true or false)")
        elif not isinstance(exclusive, bool):
            problems.append(f"{where}.exclusive must be true or false")
        description = raw.get("description")
        if "description" not in raw:
            problems.append(
                f"{where}.description is required (what belongs in this layer)"
            )
        elif not isinstance(description, str):
            problems.append(f"{where}.description must be a string")

    active = raw.get("active", True)
    if not isinstance(active, bool):
        problems.append(f"{where}.active must be true or false")

    items: list[str] = []
    raw_items = raw.get("items")
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list):
        problems.append(f"{where}.items must be a list of skill names")
        raw_items = []
    for item in raw_items:
        if not isinstance(item, str) or item not in skills:
            problems.append(f"{where}.items: {item!r} is not a skill of this profile")
        elif item in items:
            problems.append(f"{where}.items: {item!r} is listed more than once")
        else:
            items.append(item)
    if name == OUTPUT_STYLE and raw_items:
        problems.append(f"{where}: {OUTPUT_STYLE_UNSUPPORTED}")

    if not isinstance(exclusive, bool) or not isinstance(description, str):
        return None
    if not isinstance(active, bool):
        return None
    return Layer(
        exclusive=exclusive,
        description=description,
        items=tuple(items),
        active=active,
        builtin=builtin,
    )


def _parse_layers(raw: Any, skills: dict[str, Any], problems: list[str]):
    layers = builtin_layers()
    if raw is None:
        return layers
    if not isinstance(raw, dict):
        problems.append("'layers' must be a mapping of layer name to entry")
        return layers
    owner: dict[str, str] = {}
    for layer_name, raw_layer in raw.items():
        layer = _parse_layer(layer_name, raw_layer, skills, problems)
        if layer is None:
            continue
        layers[layer_name] = layer
        for item in layer.items:
            if item in owner:
                problems.append(
                    f"layers: {item!r} is listed in more than one layer "
                    f"({owner[item]}, {layer_name})"
                )
            owner.setdefault(item, layer_name)
    return layers


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

    layers = _parse_layers(
        data.get("layers"),
        raw_skills if isinstance(raw_skills, dict) else {},
        problems,
    )
    profile = Profile(
        name=name, path=folder, targets=targets, skills=skills, layers=layers
    )
    if not problems:
        problems.extend(exclusivity_problems(profile))
    if problems:
        raise ProfileError(file, problems)
    return profile


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
    save_profile(profile)
    return profile


def save_profile(profile: Profile) -> None:
    """Write ``profile.yaml``; the only writer, atomic so a crash never truncates."""
    file = profile.path / PROFILE_FILE
    temporary = file.with_name(f".{PROFILE_FILE}.tmp")
    text = yaml.safe_dump(profile.to_yaml_data(), sort_keys=False)
    temporary.write_text(text, "utf-8")
    os.replace(temporary, file)
