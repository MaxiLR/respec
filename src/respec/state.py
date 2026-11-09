"""respec's own record of what it manages: ``<respec home>/state.json``.

Schema (version 1)::

    {
      "version": 1,
      "active_profile": "work",            # or null before the first switch
      "owned": {                           # target folders respec has taken over
        "claude-code": {
          "skills_dir": "/home/me/.claude/skills",
          "backup": "/home/me/.respec/backups/20261109T120000Z/claude-code",
          "taken_over_at": "2026-11-09T12:00:00+00:00"
        }
      },
      "installed": [                       # every path respec created
        {"target": "claude-code", "name": "tdd",
         "path": "/home/me/.claude/skills/tdd", "mode": "symlink"}
      ]
    }

``backup`` is null when the folder did not exist at takeover. ``mode`` is
``symlink`` or ``copy``. Removal only ever touches paths listed in
``installed``.
"""

from __future__ import annotations

import json
import os
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


@dataclass(frozen=True)
class Installed:
    target: str
    name: str
    path: str
    mode: str


@dataclass
class State:
    active_profile: str | None = None
    owned: dict[str, Owned] = field(default_factory=dict)
    installed: list[Installed] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "active_profile": self.active_profile,
            "owned": {name: vars(entry) for name, entry in self.owned.items()},
            "installed": [vars(item) for item in self.installed],
        }


def state_path(respec_home: Path) -> Path:
    return respec_home / STATE_FILE


def _invalid(path: Path, problem: str) -> RespecError:
    return RespecError(f"invalid state file {path}: {problem}")


def load_state(respec_home: Path) -> State:
    path = state_path(respec_home)
    if not path.exists():
        return State()
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise _invalid(path, str(error)) from None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise _invalid(path, f"expected a mapping with version {VERSION}")
    try:
        owned = {name: Owned(**entry) for name, entry in data["owned"].items()}
        installed = [Installed(**item) for item in data["installed"]]
    except (KeyError, TypeError, AttributeError) as error:
        raise _invalid(path, f"malformed entry ({error})") from None
    for item in installed:
        if item.mode not in MODES:
            raise _invalid(path, f"unknown install mode {item.mode!r}")
    active = data.get("active_profile")
    if active is not None and not isinstance(active, str):
        raise _invalid(path, "active_profile must be a string or null")
    return State(active_profile=active, owned=owned, installed=installed)


def save_state(respec_home: Path, state: State) -> None:
    """Write state atomically so a crash never leaves a truncated file."""
    path = state_path(respec_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{STATE_FILE}.tmp")
    temporary.write_text(json.dumps(state.to_dict(), indent=2) + "\n", "utf-8")
    os.replace(temporary, path)
