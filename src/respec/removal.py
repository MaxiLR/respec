"""Removing a profile: ``respec profile remove <name>`` (and Delete in the TUI).

Nothing is deleted. The profile's folder (``profile.yaml`` and its skill
copies) moves, in one rename, to a fresh run folder
``<respec home>/removed-profiles/<run>/<name>/`` (runs are named like backup
runs, by UTC time). Moving that folder back to ``<respec home>/profiles/``
brings the profile back.

A kill can only land before the rename (the profile is intact; an empty run
folder may be left) or after it (the backup is complete), so no journal is
needed and there is nothing to recover; the empty run folder a kill before
the rename leaves is removed by the next removal. Refused, with nothing
changed: an invalid name or one not listed exactly (case matters, also on a
case-insensitive file system), the active profile, a profile whose skills are
still linked into a target folder (for example after ``respec recover``
rebuilt ``state.json``), an interrupted change waiting in the journal (it may
concern this profile; ``respec recover`` first) and a second respec holding
the lock.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from respec import journal, lock, paths, profiles, switch, targets
from respec.errors import RespecError
from respec.state import State, load_state, sync_folder

REMOVED_DIR = "removed-profiles"


@dataclass(frozen=True)
class Removed:
    name: str
    path: Path  # where the profile was
    backup: Path  # where its folder is now

    def describe(self) -> str:
        return (
            f"Removed profile {self.name!r}. Its folder (profile.yaml and its "
            f"skills) was moved to {self.backup}; to get it back, move that "
            f"folder to {self.path}."
        )


def removed_dir(respec_home: Path) -> Path:
    return respec_home / REMOVED_DIR


def remove_profile(
    respec_home: Path,
    name: str,
    user_home: Path | None = None,
    now: datetime | None = None,
) -> Removed:
    """Move profile ``name`` to a new run in :func:`removed_dir`."""
    profiles.validate_name(name)
    home = user_home if user_home is not None else paths.user_home()
    with lock.exclusive(respec_home):
        state = load_state(respec_home)
        if state.journal is not None:
            raise journal.Pending(_pending_refusal(name, state.journal))
        folder = profiles.existing_folder(respec_home, name)
        active = state.active_profile
        if active is not None and (
            active == name or _same(folder, profiles.profiles_dir(respec_home) / active)
        ):
            raise RespecError(
                f"profile {name!r} is active, so it cannot be removed; nothing "
                "was changed. Switch to another profile first with 'respec use "
                "<other>', or undo respec with 'respec restore'."
            )
        linked = _links_into(folder, _target_folders(state, home))
        if linked:
            raise RespecError(
                f"profile {name!r} still has skills linked into target folders: "
                f"{', '.join(linked)}; nothing was changed. Removing it would "
                "break them. Run 'respec use <other>' (or 'respec restore') "
                "first to remove respec's links."
            )
        root = removed_dir(respec_home)
        _drop_empty_runs(root)
        run = switch.new_backup_run(
            respec_home, now or datetime.now(timezone.utc), parent=root
        )
        backup = run / name
        journal.checkpoint("profile-remove:move")
        try:
            os.rename(folder, backup)
        except OSError as error:
            _drop_empty(run)
            raise RespecError(
                f"could not move profile {name!r} to {backup}: {error}; "
                "nothing was changed"
            ) from None
        sync_folder(folder.parent)
        sync_folder(run)
        journal.checkpoint("profile-remove:moved")
        return Removed(name=name, path=folder, backup=backup)


def _pending_refusal(name: str, waiting: dict[str, Any]) -> str:
    what = journal.describe(waiting)
    started = waiting.get("started_at")
    when = f" (started {started})" if started else ""
    return (
        f"cannot remove profile {name!r} while an interrupted change waits; "
        f"nothing was changed. {what[0].upper()}{what[1:]}{when} did not "
        "complete. Run 'respec recover' to finish it, or 'respec recover "
        "--rollback' to roll it back (Sync in the TUI offers both), then remove "
        "the profile."
    )


def _same(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _target_folders(state: State, user_home: Path) -> list[Path]:
    """Every folder respec may have linked skills into: each target's folder
    and each folder state.json records as owned."""
    found = [t.skills_dir(user_home) for t in targets.registry().values()]
    found += [Path(owned.skills_dir) for owned in state.owned.values()]
    unique: dict[str, Path] = {}
    for folder in found:
        unique.setdefault(os.path.realpath(folder), folder)
    return list(unique.values())


def _links_into(profile_folder: Path, folders: list[Path]) -> list[str]:
    """Symlinks in ``folders`` that point into ``profile_folder``, whatever
    state.json says (it may have been rebuilt)."""
    inside = Path(os.path.realpath(profile_folder))
    found: list[str] = []
    for folder in folders:
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_symlink():
                continue
            target = Path(os.path.realpath(entry))
            if (
                target == inside
                or inside in target.parents
                or any(_same(parent, inside) for parent in target.parents)
            ):
                found.append(str(entry))
    return found


def _drop_empty_runs(root: Path) -> None:
    """Remove empty run folders a kill before the rename left behind (under
    the lock, so no other removal is between its mkdir and its rename)."""
    try:
        runs = list(root.iterdir())
    except OSError:
        return
    for run in runs:
        if run.is_dir() and not run.is_symlink():
            _drop_empty(run)


def _drop_empty(run: Path) -> None:
    try:
        run.rmdir()  # only when empty
    except OSError:
        pass
