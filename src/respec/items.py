"""Items of a profile: add a local skill folder, remove, enable and disable.

Every change writes ``profile.yaml`` through :func:`respec.profiles.save_profile`.
When the changed profile is the active one, its targets are refreshed at once by
re-running the switching engine (:func:`respec.switch.use`) for that profile, so
links are added or removed and ``state.json`` stays truthful. When that switch is
refused by its preflight (nothing on disk changed), the profile change is undone
so the profile and its target folders never disagree.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from respec import global_skills, profiles, switch
from respec.errors import RespecError
from respec.state import load_state

SKILL_FILE = "SKILL.md"


@dataclass
class SkillChange:
    profile: str
    skill: str
    action: str
    enabled: bool | None
    path: str
    active: bool = False
    linked: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def resolve_profile_name(respec_home: Path, name: str | None) -> str:
    """``name``, or the active profile when ``name`` is not given."""
    if name is not None:
        return name
    active = load_state(respec_home).active_profile
    if active is None:
        raise RespecError(
            "no active profile; name the profile with '-p <profile>' "
            "or activate one with 'respec use <profile>'"
        )
    return active


def user_path(text: str | Path) -> Path:
    """A path as the user typed it, with ``~`` expanded; refuses what cannot be."""
    if "\0" in str(text):
        raise RespecError(f"{str(text)!r} is not a valid path: it holds a NUL byte")
    try:
        return Path(text).expanduser()
    except RuntimeError:
        raise RespecError(
            f"cannot expand {str(text)!r}: no home folder is known for that user"
        ) from None


def _skill_folder(profile: profiles.Profile, item: str) -> Path:
    return profile.path / profiles.SKILLS_DIR / item


def add_local(
    respec_home: Path,
    profile_name: str,
    source: Path,
    enabled: bool = True,
    name: str | None = None,
    origin: profiles.Source | None = None,
) -> profiles.Profile:
    """Copy the skill folder ``source`` into a profile and record it.

    The item is called ``name``, or after the source folder (after resolving
    symlinks) when no name is given. ``origin`` is recorded as the item's
    ``source`` (where it was fetched from). Target folders are not touched.
    Returns the updated profile. On failure nothing is left behind in the
    profile.
    """
    profile = profiles.load_profile(respec_home, profile_name)
    source = user_path(source).resolve()
    if not source.is_dir():
        raise RespecError(f"{source} is not a folder; give the path of a skill folder")
    if not (source / SKILL_FILE).is_file():
        raise RespecError(f"{source} has no {SKILL_FILE}; a skill folder needs one")
    item = name if name is not None else source.name
    if not profiles.NAME_PATTERN.match(item):
        raise RespecError(
            f"skill folder name {item!r} is not a valid skill name: "
            f"{profiles.NAME_RULE}"
        )
    global_skills.refuse_reserved(respec_home, [item], profile.name)
    if item in profile.skills:
        raise RespecError(
            f"profile {profile.name!r} already has a skill {item!r}; "
            f"remove it first with 'respec remove {item} -p {profile.name}'"
        )
    destination = _skill_folder(profile, item)
    if os.path.lexists(destination):
        raise RespecError(
            f"{destination} already exists but is not listed in "
            f"{profiles.PROFILE_FILE}; move it out of the way first"
        )
    if source == destination.resolve() or source in destination.resolve().parents:
        raise RespecError(f"cannot add {source}: it contains profile {profile.name!r}")

    try:
        shutil.copytree(source, destination)
        skills = dict(profile.skills)
        skills[item] = profiles.SkillEntry(enabled=enabled, source=origin)
        updated = dataclasses.replace(profile, skills=skills)
        profiles.save_profile(updated)
    except (OSError, shutil.Error) as error:
        shutil.rmtree(destination, ignore_errors=True)
        raise RespecError(
            f"could not add {source} to profile {profile.name!r}: {error}"
        ) from None
    return updated


def _refresh(
    respec_home: Path,
    user_home: Path,
    change: SkillChange,
    undo: Callable[[], None],
) -> None:
    """Re-apply the profile when it is active; fill in the link changes.

    ``change`` is any object with ``profile``, ``active``, ``linked`` and
    ``unlinked`` attributes (an :class:`SkillChange` or a layer change).
    """
    if load_state(respec_home).active_profile != change.profile:
        return
    change.active = True
    try:
        result = switch.use(respec_home, user_home, change.profile, action="refresh")
    except switch.UnknownEntries as error:
        undo()
        raise switch.UnknownEntries(
            change.profile,
            error.entries,
            lead=f"cannot refresh profile {change.profile!r}",
            note=f"Profile {change.profile!r} was left unchanged.",
            clashes=error.clashes,
        ) from None
    except switch.SwitchBlocked as error:
        undo()
        raise switch.SwitchBlocked(
            f"{error}\nProfile {change.profile!r} was left unchanged."
        ) from None
    removed = {item.path for item in result.removed}
    installed = {item.path for item in result.installed}
    change.linked = sorted(installed - removed)
    change.unlinked = sorted(removed - installed)


def refresh_active(
    respec_home: Path,
    user_home: Path,
    change: object,
    undo: Callable[[], None],
) -> None:
    """Re-apply ``change.profile`` if it is the active profile.

    Fills in ``change.active``, ``linked`` and ``unlinked``. When the switch
    preflight refuses, ``undo()`` runs and :class:`switch.SwitchBlocked` is
    raised. For callers whose undo needs more than restoring ``profile.yaml``.
    """
    _refresh(respec_home, user_home, change, undo)


def commit(
    respec_home: Path,
    user_home: Path,
    before: profiles.Profile,
    after: profiles.Profile,
    change: SkillChange,
) -> None:
    """Save ``after`` and refresh an active profile; if refused, put back the
    exact file ``before`` was loaded from."""
    profiles.save_profile(after)
    _refresh(respec_home, user_home, change, lambda: profiles.restore_profile(before))


def add(
    respec_home: Path,
    user_home: Path,
    source: Path,
    profile_name: str | None = None,
) -> SkillChange:
    """Add a local skill folder to a profile (default: the active one)."""
    name = resolve_profile_name(respec_home, profile_name)
    before = profiles.load_profile(respec_home, name)
    profile = add_local(respec_home, name, source)
    item = next(skill for skill in profile.skills if skill not in before.skills)
    folder = _skill_folder(profile, item)
    change = SkillChange(
        profile=name, skill=item, action="add", enabled=True, path=str(folder)
    )

    def undo() -> None:
        profiles.restore_profile(before)
        shutil.rmtree(folder, ignore_errors=True)

    _refresh(respec_home, user_home, change, undo)
    return change


def _load_with_item(
    respec_home: Path, profile_name: str | None, item: str
) -> profiles.Profile:
    profile = profiles.load_profile(
        respec_home, resolve_profile_name(respec_home, profile_name)
    )
    if item not in profile.skills:
        known = ", ".join(profile.skills) or "none"
        raise RespecError(
            f"profile {profile.name!r} has no skill {item!r} (skills: {known})"
        )
    return profile


def set_enabled(
    respec_home: Path,
    user_home: Path,
    item: str,
    enabled: bool,
    profile_name: str | None = None,
) -> SkillChange:
    """Enable or disable an item; its files and source record are kept."""
    profile = _load_with_item(respec_home, profile_name, item)
    change = SkillChange(
        profile=profile.name,
        skill=item,
        action="enable" if enabled else "disable",
        enabled=enabled,
        path=str(_skill_folder(profile, item)),
        active=load_state(respec_home).active_profile == profile.name,
    )
    if profile.skills[item].enabled == enabled:
        return change
    # Enabling a member of an active exclusive layer disables the previous one.
    after = profiles.with_enabled(profile, [item], enabled)
    commit(respec_home, user_home, profile, after, change)
    return change


def remove(
    respec_home: Path,
    user_home: Path,
    item: str,
    profile_name: str | None = None,
) -> SkillChange:
    """Remove an item: drop it from ``profile.yaml`` and delete its folder."""
    profile = _load_with_item(respec_home, profile_name, item)
    folder = _skill_folder(profile, item)
    change = SkillChange(
        profile=profile.name,
        skill=item,
        action="remove",
        enabled=None,
        path=str(folder),
    )
    skills = {name: entry for name, entry in profile.skills.items() if name != item}
    layers = {
        name: dataclasses.replace(
            layer, items=tuple(member for member in layer.items if member != item)
        )
        for name, layer in profile.layers.items()
    }
    profiles.save_profile(dataclasses.replace(profile, skills=skills, layers=layers))
    try:
        _refresh(
            respec_home, user_home, change, lambda: profiles.restore_profile(profile)
        )
    except switch.SwitchBlocked:
        raise
    except RespecError:
        # The item is gone from profile.yaml; any links still recorded in
        # state.json are removed by the next switch, so delete the folder too.
        shutil.rmtree(folder, ignore_errors=True)
        raise
    shutil.rmtree(folder, ignore_errors=True)
    return change
