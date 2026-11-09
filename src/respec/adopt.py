"""Resolve unknown entries in owned folders (see :mod:`respec.unknown`).

Each entry gets one of three choices:

- ``add``: copy it into a profile as an enabled item (through
  :func:`respec.items.add_local`, keeping the entry's own name), then remove
  the original; the profile's next install links it back.
- ``backup``: copy it to ``<respec home>/backups/<timestamp>/<target>/<name>``,
  then remove the original.
- ``keep``: leave it in place and record it in ``state.unmanaged`` so it is no
  longer asked about.

An original is only removed after its copy (in a profile or in a backup) is
complete, so nothing is lost. A symlink entry is removed by unlinking it; what
it points to is never touched.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from respec import items, switch, unknown
from respec.errors import RespecError
from respec.state import load_state, save_state

CHOICES = ("add", "backup", "keep")

Decide = Callable[[unknown.Unknown], str | None]


@dataclass
class Resolution:
    entry: unknown.Unknown
    choice: str
    profile: str | None = None
    backup: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            **self.entry.to_dict(),
            "choice": self.choice,
            "profile": self.profile,
            "backup": self.backup,
        }


@dataclass
class AdoptResult:
    resolved: list[Resolution] = field(default_factory=list)
    unknown: list[unknown.Unknown] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)


def _delete(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _settle(respec_home: Path, entry: unknown.Unknown, keep: bool) -> None:
    """Record the outcome: the path is no longer respec's; kept ones are listed."""
    state = load_state(respec_home)
    key = unknown.real(entry.path)
    state.installed = [i for i in state.installed if unknown.real(i.path) != key]
    if keep and entry.path not in state.unmanaged:
        state.unmanaged.append(entry.path)
    save_state(respec_home, state)


def _add(respec_home: Path, entry: unknown.Unknown, profile_name: str | None) -> str:
    profile = items.resolve_profile_name(respec_home, profile_name)
    items.add_local(respec_home, profile, Path(entry.path), name=entry.name)
    _delete(Path(entry.path))
    _settle(respec_home, entry, keep=False)
    return profile


def _backup(respec_home: Path, entry: unknown.Unknown, run_dir: Path) -> str:
    source = Path(entry.path)
    destination = run_dir / entry.targets[0] / entry.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.is_symlink():
            os.symlink(os.readlink(source), destination)
        elif source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination)
    except (OSError, shutil.Error) as error:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination, ignore_errors=True)
        raise RespecError(
            f"could not back up {source}; it was left in place: {error}"
        ) from None
    _delete(source)
    _settle(respec_home, entry, keep=False)
    return str(destination)


def resolve(
    respec_home: Path,
    entries: list[unknown.Unknown],
    decide: Decide,
    profile_name: str | None = None,
    now: switch.Clock = switch.utc_now,
) -> list[Resolution]:
    """Ask ``decide`` about each entry and apply its choice at once.

    ``decide`` returns one of :data:`CHOICES`, or ``None`` to leave the entry
    as it is. ``add`` goes to ``profile_name`` (default: the active profile).
    """
    resolutions: list[Resolution] = []
    run_dir: Path | None = None
    for entry in entries:
        choice = decide(entry)
        if choice is None:
            continue
        if choice not in CHOICES:
            raise RespecError(
                f"unknown choice {choice!r} for {entry.path}; "
                f"use one of: {', '.join(CHOICES)}"
            )
        resolution = Resolution(entry=entry, choice=choice)
        if choice == "add":
            resolution.profile = _add(respec_home, entry, profile_name)
        elif choice == "backup":
            if run_dir is None:
                run_dir = switch.new_backup_run(respec_home, now())
            resolution.backup = _backup(respec_home, entry, run_dir)
        else:
            _settle(respec_home, entry, keep=True)
        resolutions.append(resolution)
    return resolutions


def find(respec_home: Path) -> list[unknown.Unknown]:
    """Current unknown entries of every owned folder."""
    return unknown.find_unknown(respec_home, load_state(respec_home))


def adopt(
    respec_home: Path,
    user_home: Path,
    decide: Decide,
    profile_name: str | None = None,
    now: switch.Clock = switch.utc_now,
) -> AdoptResult:
    """Resolve unknown entries outside a switch.

    Entries added to the active profile are linked right away by re-applying
    that profile; other unknown entries stay as they are.
    """
    result = AdoptResult()
    result.resolved = resolve(respec_home, find(respec_home), decide, profile_name, now)
    active = load_state(respec_home).active_profile
    if any(r.choice == "add" and r.profile == active for r in result.resolved):
        applied = switch.use(
            respec_home, user_home, active, now=now, on_unknown=lambda entries: None
        )
        removed = {item.path for item in applied.removed}
        result.linked = sorted(
            item.path for item in applied.installed if item.path not in removed
        )
    result.unknown = find(respec_home)
    return result
