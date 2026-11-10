"""respec's own record of what it manages: ``<respec home>/state.json``.

Schema (version 1)::

    {
      "version": 1,
      "active_profile": "work",            # or null before the first switch
      "owned": {                           # target folders respec has taken over
        "claude-code": {
          "skills_dir": "/home/me/.claude/skills",
          "backup": "/home/me/.respec/backups/20261109T120000Z/claude-code",
          "taken_over_at": "2026-11-09T12:00:00+00:00",
          "created": ["/home/me/.omp/agent/skills", "/home/me/.omp/agent"]
        }
      },
      "installed": [                       # every path respec created
        {"target": "claude-code", "name": "tdd",
         "path": "/home/me/.claude/skills/tdd", "mode": "symlink"},
        {"target": "agents", "name": "lint",
         "path": "/home/me/.agents/skills/lint", "mode": "copy",
         "digest": "sha256:..."}         # content fingerprint, copies only
      ]
    }

``journal`` (left out when nothing is in progress) records a change that
spans several steps while it runs: which operation, its plan and the one
step in flight. A crash leaves it behind, and the next respec command finishes
or rolls back that change (see :mod:`respec.journal`).

``backup`` is null when the folder did not exist at takeover. After
``respec recover`` rebuilt an unreadable file, a folder whose takeover it
could not find again is marked ``takeover_unknown`` (``backup`` and
``created`` are then unknown, and a restore must name its backup run). ``created`` (left
out when empty) lists the folders missing at takeover, deepest first, which
respec then created; ``respec restore`` removes those that are empty again. ``mode`` is
``symlink`` or ``copy``. ``digest`` fingerprints a copy's content as installed,
so a copy that was later edited or replaced is not mistaken for respec's own; a
copy recorded without one is never treated as respec's. Removal only ever touches paths listed in
``installed``.

Files written by earlier versions may hold an ``unmanaged`` list (entries the
user once chose to keep). That choice no longer exists: the list is ignored on
load, so those entries count as unknown again, and the next save drops it.
"""

from __future__ import annotations

import json
import os

try:
    import fcntl
except ImportError:  # not on Windows
    fcntl = None  # type: ignore[assignment]
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from respec.errors import RespecError

STATE_FILE = "state.json"
VERSION = 1
MODES = ("symlink", "copy")


@dataclass(frozen=True)
class Owned:
    skills_dir: str
    backup: str | None
    taken_over_at: str
    # Folders missing at takeover (the skills folder and missing parents,
    # deepest first): respec created them, so a restore may remove them again.
    created: tuple[str, ...] = ()
    # Set when state.json was rebuilt and no record of this folder's takeover
    # was found: ``backup`` and ``created`` are then unknown, not "none".
    takeover_unknown: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "skills_dir": self.skills_dir,
            "backup": self.backup,
            "taken_over_at": self.taken_over_at,
        }
        if self.created:
            data["created"] = list(self.created)
        if self.takeover_unknown:
            data["takeover_unknown"] = True
        return data


@dataclass(frozen=True)
class Installed:
    target: str
    name: str
    path: str
    mode: str
    digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "target": self.target,
            "name": self.name,
            "path": self.path,
            "mode": self.mode,
        }
        if self.digest is not None:
            data["digest"] = self.digest
        return data


@dataclass
class State:
    active_profile: str | None = None
    owned: dict[str, Owned] = field(default_factory=dict)
    installed: list[Installed] = field(default_factory=list)
    # The change in progress (see :mod:`respec.journal`); None when there is none.
    journal: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "version": VERSION,
            "active_profile": self.active_profile,
            "owned": {name: entry.to_dict() for name, entry in self.owned.items()},
            "installed": [item.to_dict() for item in self.installed],
        }
        if self.journal is not None:
            data["journal"] = self.journal
        return data


def state_path(respec_home: Path) -> Path:
    return respec_home / STATE_FILE


class StateNewer(RespecError):
    """``state.json`` comes from a newer respec; it is never rebuilt."""


class StateInvalid(RespecError):
    """``state.json`` cannot be read (for example empty after a power loss)."""


def _invalid(path: Path, problem: str) -> RespecError:
    return StateInvalid(
        f"invalid state file {path}: {problem}\nRun 'respec recover' to rebuild "
        "it from what is on disk (the damaged file is kept in a backup run and "
        "nothing is deleted)."
    )


def load_state(respec_home: Path) -> State:
    path = state_path(respec_home)
    if not path.exists():
        return State()
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise _invalid(path, str(error)) from None
    if (
        isinstance(data, dict)
        and isinstance(data.get("version"), int)
        and data["version"] > VERSION
    ):
        raise StateNewer(
            f"{path} was written by a newer respec (state version "
            f"{data['version']}; this respec reads version {VERSION}). Use that "
            "newer respec; nothing was changed."
        )
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise _invalid(path, f"expected a mapping with version {VERSION}")
    try:
        owned = {
            name: Owned(**{**entry, "created": tuple(entry.get("created", ()))})
            for name, entry in data["owned"].items()
        }
        installed = [Installed(**item) for item in data["installed"]]
    except (KeyError, TypeError, AttributeError) as error:
        raise _invalid(path, f"malformed entry ({error})") from None
    for item in installed:
        if item.mode not in MODES:
            raise _invalid(path, f"unknown install mode {item.mode!r}")
    active = data.get("active_profile")
    if active is not None and not isinstance(active, str):
        raise _invalid(path, "active_profile must be a string or null")
    journal = data.get("journal")
    if journal is not None and not (
        isinstance(journal, dict) and isinstance(journal.get("operation"), str)
    ):
        raise _invalid(path, "journal must be a mapping with an operation")
    return State(
        active_profile=active, owned=owned, installed=installed, journal=journal
    )


def active_or_none(respec_home: Path) -> str | None:
    """The active profile on disk; None also when ``state.json`` cannot be
    read (for reports that must not fail on that)."""
    try:
        return load_state(respec_home).active_profile
    except RespecError:
        return None


def save_state(respec_home: Path, state: State, durable: bool = False) -> None:
    """Write state atomically (a temporary file, then a rename), so a crash or
    kill never leaves a truncated file.

    The temporary file is always flushed (``fsync``) before the rename, so
    a power loss cannot expose an empty file. ``durable`` also flushes to the
    drive itself (``F_FULLFSYNC`` on macOS) and flushes the folder, so the
    write itself survives a power loss. That is slow, so only the journal's
    boundaries ask for it (a change beginning, changing phase or ending, see
    :mod:`respec.journal`). After a power loss the per-item saves in between
    may be lost, back to the last boundary; a file that still cannot be read
    is rebuilt by ``respec recover`` (:func:`respec.journal.rebuild_state`).
    """
    path = state_path(respec_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{STATE_FILE}.tmp")
    text = json.dumps(state.to_dict(), indent=2) + "\n"
    if durable:
        write_durably(temporary, text)
    else:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    os.replace(temporary, path)
    if durable:
        sync_folder(path.parent)


def write_durably(path: Path, text: str) -> None:
    """Write ``text`` and flush it to disk before returning (``fsync``), so
    a rename of the file that follows never exposes an empty file after a
    power loss."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        _flush_to_disk(handle.fileno())


def _flush_to_disk(descriptor: int) -> None:
    """``fsync``; on macOS ``F_FULLFSYNC``, which also flushes the drive's
    cache (plain ``fsync`` does not there)."""
    full = getattr(fcntl, "F_FULLFSYNC", None) if fcntl is not None else None
    if full is not None:
        try:
            fcntl.fcntl(descriptor, full)
            return
        except OSError:
            pass  # not supported by this file system
    os.fsync(descriptor)


def sync_folder(folder: Path) -> None:
    """Flush a folder's entries (a rename into it) to disk where supported."""
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        _flush_to_disk(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
