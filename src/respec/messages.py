"""What a change did, in the words both the CLI and the TUI print."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from respec import items, layers, profiles, sources
from respec.state import Installed


def source_label(source: profiles.Source) -> str:
    """``repo[#path][@ref]`` or the source folder, as written in
    ``profile.yaml``."""
    if source.folder is not None:
        return source.folder
    label = source.repo or ""
    if source.path:
        label += f"#{source.path}"
    if source.ref:
        label += f"@{source.ref}"
    return label


def short(commit: str | None) -> str:
    """A commit for messages; skills installed without one show as unknown."""
    return commit[:12] if commit else "unknown"


def plural(count: int, one: str, many: str | None = None) -> str:
    """``1 skill``, ``2 skills``."""
    return f"{count} {one if count == 1 else many or one + 's'}"


def skills_placed(entries: Sequence[Installed]) -> str:
    """How many skills ``entries`` (records of what respec placed, one per
    target folder) hold, and how many links and copies that took:
    ``2 skills (4 links)``."""
    links = sum(entry.mode == "symlink" for entry in entries)
    copies = len(entries) - links
    parts = [plural(links, "link")] if links else []
    if copies:
        parts.append(plural(copies, "copy", "copies"))
    skills = plural(len({entry.name for entry in entries}), "skill")
    return f"{skills} ({', '.join(parts)})" if parts else skills


def link_lines(change: Any) -> list[str]:
    """The links a change added or removed."""
    return [
        *(f"  linked {path}" for path in change.linked),
        *(f"  unlinked {path}" for path in change.unlinked),
    ]


def skill_change(change: items.SkillChange) -> list[str]:
    origin = f" from {change.source['folder']}" if change.source else ""
    lead = {
        "add": f"Added {change.skill!r} to profile {change.profile!r}{origin}",
        "remove": f"Removed {change.skill!r} from profile {change.profile!r}",
        "enable": f"Enabled {change.skill!r} in profile {change.profile!r}",
        "disable": f"Disabled {change.skill!r} in profile {change.profile!r}",
    }[change.action]
    return [lead, *link_lines(change)]


def layer_change(change: layers.LayerChange) -> list[str]:
    where = f"layer {change.layer!r} of profile {change.profile!r}"
    lead = {
        "add": f"Added {where}",
        "rm": f"Removed {where}; its skills stay in the profile",
        "add-skill": f"Added {change.skill!r} to {where}",
        "remove-skill": f"Removed {change.skill!r} from {where}",
        "use": f"Using {change.skill!r} in {where}",
        "enable": f"Enabled the skills of {where}",
        "disable": f"Disabled the skills of {where}",
        "on": f"Turned on {where}",
        "off": f"Turned off {where}; its rules no longer apply",
        "repair": f"Repaired {where}: kept {change.skill!r}",
        "nothing": f"Nothing to repair in {where}: at most one skill is enabled",
        "additive": f"Nothing to repair in {where}: it is additive",
    }[change.action]
    disabled = [f"  disabled {skill!r}" for skill in change.disabled]
    return [lead, *disabled, *link_lines(change)]


def sourced_change(change: sources.SourceChange) -> list[str]:
    lines = []
    for skill in change.skills:
        origin = change.sources[skill]
        lines.append(
            f"Added {skill!r} to profile {change.profile!r} from "
            f"{source_label(profiles.Source(**origin))} "
            f"at {short(origin['commit'])}"
        )
    lines += [f"  linked {path}" for path in change.linked]
    return lines
