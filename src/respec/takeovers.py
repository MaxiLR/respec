"""The takeover log: ``<respec home>/takeovers.json``.

Every time respec takes a target folder over it appends a record here, kept
apart from ``state.json`` and written durably (temporary file, ``fsync``,
rename, folder flush). It says what ``state.json``'s ``owned`` entry said at
takeover (the folder, its takeover backup, the folders respec created), so a
rebuilt ``state.json`` (:func:`respec.journal.rebuild_state`) knows each
folder's takeover again, also when the folder did not exist and no backup run
was made. A restore marks the records of the folders it releases as
``released``, so a later rebuild never reuses a takeover that was undone.

Schema::

    {"version": 1,
     "records": [{"target": "claude-code", "skills_dir": "...",
                  "backup": "..." | null, "taken_over_at": "...",
                  "created": ["..."], "released": false}]}
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from respec.state import Owned, sync_folder, write_durably

LOG_FILE = "takeovers.json"
VERSION = 1


def log_path(respec_home: Path) -> Path:
    return respec_home / LOG_FILE


def _load(respec_home: Path) -> list[dict[str, Any]]:
    """The records; none when the log is missing or cannot be read."""
    try:
        data = json.loads(log_path(respec_home).read_text("utf-8"))
        records = data["records"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [r for r in records if isinstance(r, dict) and "target" in r]


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
    records = _load(respec_home)
    for target, entry in owned.items():
        records.append({"target": target, **entry.to_dict(), "released": False})
    _save(respec_home, records)


def release(respec_home: Path, targets: Iterable[str]) -> None:
    """Mark the current takeovers of ``targets`` as undone."""
    wanted = set(targets)
    records = _load(respec_home)
    changed = False
    for entry in records:
        if entry["target"] in wanted and not entry.get("released"):
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
