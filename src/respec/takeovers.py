"""The takeover log: ``<respec home>/takeovers.json``.

Every time respec takes a target folder over it appends a record here, kept
apart from ``state.json`` and written durably (temporary file, ``fsync``,
rename, folder flush). It says what ``state.json``'s ``owned`` entry said at
takeover (the folder, its takeover backup, the folders respec created), so a
rebuilt ``state.json`` (:func:`respec.journal.rebuild_state`) knows each
folder's takeover again, also when the folder did not exist and no backup run
was made. A restore marks the records of the folders it releases as
``released``, so a later rebuild never reuses a takeover that was undone.

A log written by a newer respec (a higher ``version``) is never read or
rewritten: every command that needs it refuses (:class:`TakeoversNewer`). A
log that cannot be read is reported (:func:`take_problems`) and, before
respec writes a new one, moved to a fresh backup run, never overwritten.

Schema::

    {"version": 1,
     "records": [{"target": "claude-code", "skills_dir": "...",
                  "backup": "..." | null, "taken_over_at": "...",
                  "created": ["..."], "released": false}]}
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from respec.errors import RespecError
from respec.state import Owned, sync_folder, write_durably

LOG_FILE = "takeovers.json"
VERSION = 1
WARNING = "unreadable-takeover-log"


class TakeoversNewer(RespecError):
    """``takeovers.json`` comes from a newer respec; it is never rewritten."""


@dataclass(frozen=True)
class Problem:
    """A takeover log that could not be read; ``path`` is where it is now
    (moved to a backup run before a new log was written, or left in place)."""

    path: str
    message: str

    def to_warning(self) -> dict[str, Any]:
        return {"type": WARNING, "path": self.path, "message": self.message}


# Unreadable logs found by this process, reported as warnings by the CLI.
_problems: list[Problem] = []


def peek_problems() -> list[Problem]:
    return list(_problems)


def take_problems() -> list[Problem]:
    found = list(_problems)
    _problems.clear()
    return found


def _report(problem: Problem) -> None:
    if problem not in _problems:
        _problems.append(problem)


def log_path(respec_home: Path) -> Path:
    return respec_home / LOG_FILE


def check(respec_home: Path) -> None:
    """Refuse (:class:`TakeoversNewer`) when a newer respec wrote the log."""
    _read(respec_home)


def _read(respec_home: Path) -> tuple[list[dict[str, Any]], str | None]:
    """(the records, why the log cannot be read or None). No log: no records."""
    path = log_path(respec_home)
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return [], None
    except OSError as error:
        return [], str(error)
    try:
        data = json.loads(text)
    except ValueError as error:
        return [], str(error)
    version = data.get("version") if isinstance(data, dict) else None
    if isinstance(version, int) and version > VERSION:
        raise TakeoversNewer(
            f"{path} was written by a newer respec (takeover log version "
            f"{version}; this respec reads version {VERSION}). Use that newer "
            "respec; nothing was changed."
        )
    if version != VERSION or not isinstance(data.get("records"), list):
        return [], f"expected a mapping with version {VERSION} and its records"
    records = data["records"]
    return [r for r in records if isinstance(r, dict) and "target" in r], None


def _load(respec_home: Path) -> list[dict[str, Any]]:
    """The records to read; a log that cannot be read is reported and left as
    it is (it holds none that respec can use)."""
    records, problem = _read(respec_home)
    if problem is not None:
        path = log_path(respec_home)
        _report(
            Problem(
                str(path),
                f"{path} could not be read ({problem}), so the takeovers it "
                "recorded are unknown; it is left as it is, and moved to a "
                "backup run before respec writes a new one.",
            )
        )
    return records


def _load_for_rewrite(respec_home: Path) -> list[dict[str, Any]]:
    """The records to rewrite; a log that cannot be read is first moved to a
    fresh backup run (never overwritten) and reported."""
    records, problem = _read(respec_home)
    if problem is None:
        return records
    from respec import switch

    path = log_path(respec_home)
    kept = switch.new_backup_run(respec_home, switch.utc_now()) / LOG_FILE
    os.replace(path, kept)
    _report(
        Problem(
            str(kept),
            f"{path} could not be read ({problem}), so the takeovers it "
            f"recorded are unknown. It is kept at {kept}, and a new log was "
            "started.",
        )
    )
    return []


def _save(respec_home: Path, records: list[dict[str, Any]]) -> None:
    path = log_path(respec_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{LOG_FILE}.tmp")
    write_durably(
        temporary, json.dumps({"version": VERSION, "records": records}, indent=2)
    )
    os.replace(temporary, path)
    sync_folder(path.parent)


def record(respec_home: Path, owned: dict[str, Owned]) -> None:
    """Append the takeover of each target in ``owned``."""
    if not owned:
        return
    records = _load_for_rewrite(respec_home)
    for target, entry in owned.items():
        records.append({"target": target, **entry.to_dict(), "released": False})
    _save(respec_home, records)


def release(respec_home: Path, targets: Iterable[str]) -> None:
    """Mark the current takeovers of ``targets`` as undone."""
    wanted = set(targets)
    _release(respec_home, lambda target: target in wanted)


def release_unowned(respec_home: Path, owned: Iterable[str]) -> None:
    """Mark as undone the takeovers of targets not in ``owned`` (those of an
    interrupted switch that was rolled back before ``state.json`` recorded
    them)."""
    keep = set(owned)
    _release(respec_home, lambda target: target not in keep)


def _release(respec_home: Path, chosen: Callable[[str], bool]) -> None:
    records = _load_for_rewrite(respec_home)
    changed = False
    for entry in records:
        if chosen(entry["target"]) and not entry.get("released"):
            entry["released"] = True
            changed = True
    if changed:
        _save(respec_home, records)


def current(respec_home: Path) -> dict[str, Owned]:
    """The latest takeover of each target that was not released."""
    found: dict[str, Owned] = {}
    for entry in _load(respec_home):
        target = entry["target"]
        if entry.get("released"):
            found.pop(target, None)
            continue
        try:
            found[target] = Owned(
                skills_dir=entry["skills_dir"],
                backup=entry.get("backup"),
                taken_over_at=entry["taken_over_at"],
                created=tuple(entry.get("created", ())),
            )
        except (KeyError, TypeError):
            found.pop(target, None)
    return found


def backup_targets(respec_home: Path) -> set[Path]:
    """Every takeover backup folder (``<run>/<target>``) ever recorded."""
    return {Path(e["backup"]) for e in _load(respec_home) if e.get("backup")}
