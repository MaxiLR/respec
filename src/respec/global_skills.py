"""Skills that survive every switch: the global section and respec's own skills.

The global section lives in ``<respec home>/config.yaml``::

    global:
      skills: [my-notes]     # optional; folders under <respec home>/global/skills/

Each listed skill's folder is ``<respec home>/global/skills/<name>/``. Global
skills are installed only into the active profile's targets and are never
dropped by a switch.

respec also ships its own skills (``respec`` and ``profile-maker``, bundled in
the package under ``shipped/``). They go into every registered target whenever
a profile is active, whatever that profile's targets, so any agent on the
machine can edit profiles. Before each switch their files are refreshed into
``<respec home>/shipped/<name>/`` and target entries link there. There is no
opt-out; ``respec restore`` removes them with everything else.

A profile skill cannot share a name with a global or shipped skill: they would
need the same entry in a target folder, so the switch refuses.
"""

from __future__ import annotations

import filecmp
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from respec import profiles
from respec.errors import RespecError

CONFIG_FILE = "config.yaml"
GLOBAL_DIR = "global"
SHIPPED_DIR = "shipped"
TOP_LEVEL_KEYS = ("global",)
GLOBAL_KEYS = ("skills",)


def config_path(respec_home: Path) -> Path:
    return respec_home / CONFIG_FILE


def global_skills_dir(respec_home: Path) -> Path:
    return respec_home / GLOBAL_DIR / profiles.SKILLS_DIR


def shipped_dir(respec_home: Path) -> Path:
    return respec_home / SHIPPED_DIR


def source_roots(respec_home: Path) -> list[Path]:
    """Folders that respec's links point into (resolved)."""
    return [
        profiles.profiles_dir(respec_home).resolve(),
        (respec_home / GLOBAL_DIR).resolve(),
        shipped_dir(respec_home).resolve(),
    ]


def _bundled():
    return resources.files("respec").joinpath(SHIPPED_DIR)


def shipped_names() -> tuple[str, ...]:
    """Names of the skills respec ships, sorted."""
    return tuple(
        sorted(
            entry.name
            for entry in _bundled().iterdir()
            if entry.is_dir() and entry.joinpath("SKILL.md").is_file()
        )
    )


def _invalid(path: Path, problem: str) -> RespecError:
    return RespecError(f"invalid config file {path}: {problem}")


def _unknown_keys(where: str, data: dict[str, Any], allowed: tuple[str, ...]):
    extra = sorted(str(key) for key in data if key not in allowed)
    if extra:
        return f"unknown key(s) at {where}: {', '.join(extra)}"
    return None


def load_global(respec_home: Path) -> tuple[str, ...]:
    """Skill names listed in the global section (none without a config file)."""
    path = config_path(respec_home)
    if not path.exists():
        return ()
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise _invalid(path, str(error)) from None
    if data is None:
        return ()
    if not isinstance(data, dict):
        raise _invalid(path, "expected a mapping")
    problem = _unknown_keys("top level", data, TOP_LEVEL_KEYS)
    if problem:
        raise _invalid(path, problem)
    section = data.get("global")
    if section is None:
        return ()
    if not isinstance(section, dict):
        raise _invalid(path, "'global' must be a mapping")
    problem = _unknown_keys("global", section, GLOBAL_KEYS)
    if problem:
        raise _invalid(path, problem)
    skills = section.get("skills")
    if skills is None:
        return ()
    if not isinstance(skills, list):
        raise _invalid(path, "'global.skills' must be a list of skill names")
    shipped = set(shipped_names())
    seen: list[str] = []
    for name in skills:
        if not isinstance(name, str) or not profiles.NAME_PATTERN.match(name):
            raise _invalid(path, f"invalid skill name {name!r} ({profiles.NAME_RULE})")
        if name in seen:
            raise _invalid(path, f"skill {name!r} is listed twice")
        if name in shipped:
            raise _invalid(
                path, f"skill {name!r} is one respec ships; it is always installed"
            )
        seen.append(name)
    return tuple(seen)


def global_source(respec_home: Path, name: str) -> Path:
    return global_skills_dir(respec_home) / name


def shipped_source(respec_home: Path, name: str) -> Path:
    return shipped_dir(respec_home) / name


def check_sources(respec_home: Path, names: tuple[str, ...]) -> list[str]:
    """Problems with global skills whose folder is missing."""
    return [
        f"global skill {name!r} (listed in {config_path(respec_home)}) has no "
        f"folder at {global_source(respec_home, name)}"
        for name in names
        if not global_source(respec_home, name).is_dir()
    ]


def _same_tree(left: Path, right: Path) -> bool:
    compared = filecmp.dircmp(left, right, ignore=[])
    if compared.left_only or compared.right_only or compared.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(
        left, right, compared.common_files, shallow=False
    )
    if mismatch or errors:
        return False
    return all(_same_tree(left / sub, right / sub) for sub in compared.common_dirs)


def refresh_shipped(respec_home: Path) -> None:
    """Bring ``<respec home>/shipped/<name>/`` in line with the bundled files.

    A folder whose content already matches is left alone, so links into it
    and recorded copies stay valid.
    """
    root = shipped_dir(respec_home)
    root.mkdir(parents=True, exist_ok=True)
    for name in shipped_names():
        destination = root / name
        with resources.as_file(_bundled().joinpath(name)) as bundled:
            if destination.is_dir() and not destination.is_symlink():
                if _same_tree(Path(bundled), destination):
                    continue
            staged = root / f".{name}.new"
            shutil.rmtree(staged, ignore_errors=True)
            try:
                shutil.copytree(bundled, staged)
                if destination.is_symlink() or destination.is_file():
                    destination.unlink()
                elif destination.exists():
                    shutil.rmtree(destination)
                staged.rename(destination)
            except OSError as error:
                shutil.rmtree(staged, ignore_errors=True)
                raise RespecError(
                    f"could not refresh respec's own skill {name!r} in {root}: "
                    f"{error}"
                ) from None
