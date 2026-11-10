"""Removing a profile: ``respec profile remove <name>`` (and Delete in the TUI).

Nothing is deleted. The profile's folder (``profile.yaml`` and its skill
copies) moves, in one rename, to a fresh run folder
``<respec home>/removed-profiles/<run>/<name>/`` (runs are named like backup
runs, by UTC time). Moving that folder back to ``<respec home>/profiles/``
brings the profile back.

A kill can only land before the rename (the profile is intact; an empty run
folder may be left) or after it (the backup is complete), so no journal is
needed and there is nothing to recover. Refused, with nothing changed: an
invalid or unknown name, the active profile, an interrupted change waiting in
the journal (it may concern this profile; ``respec recover`` first) and a
second respec holding the lock.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from respec import journal, lock, profiles, switch
from respec.errors import RespecError
from respec.state import load_state, sync_folder

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
    respec_home: Path, name: str, now: datetime | None = None
) -> Removed:
    """Move profile ``name`` to a new run in :func:`removed_dir`."""
    profiles.validate_name(name)
    with lock.exclusive(respec_home):
        state = load_state(respec_home)
        waiting = state.journal
        if waiting is not None:
            raise journal.Pending(
                f"cannot remove profile {name!r} now; nothing was changed. "
                + journal.pending_message(waiting)
            )
        folder = profiles.profiles_dir(respec_home) / name
        if not folder.is_dir():
            raise RespecError(f"profile {name!r} does not exist in {folder.parent}")
        if state.active_profile == name:
            raise RespecError(
                f"profile {name!r} is active, so it cannot be removed; nothing "
                "was changed. Switch to another profile first with 'respec use "
                "<other>', or undo respec with 'respec restore'."
            )
        run = switch.new_backup_run(
            respec_home,
            now or datetime.now(timezone.utc),
            parent=removed_dir(respec_home),
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


def _drop_empty(run: Path) -> None:
    try:
        run.rmdir()  # only when empty
    except OSError:
        pass
