"""Unknown entries: anything in a folder respec owns that respec did not put there.

An entry is *managed* when ``state.json`` records it and it is still what respec
created: a recorded symlink must still be a symlink into the profiles folder,
a recorded copy must still exist. A recorded path that now holds something
else (for example a link replaced by a hand-made folder, or a
copy another tool replaced or someone edited) is unknown again and
flagged ``replaced``. Hidden entries (``.DS_Store`` and the like) are never
reported, and ``.DS_Store`` files inside a copy do not count as an edit.

Every unknown entry is resolved the same way (see :mod:`respec.adopt`): add it
to the active profile, or remove it after backing it up.

Targets whose folders resolve to one real directory are scanned once, under the
first of them in registry order; the others are its aliases.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from respec import profiles, targets
from respec.state import Installed, State

IGNORED_FILES = frozenset({".DS_Store"})


@dataclass(frozen=True)
class Unknown:
    name: str
    path: str
    kind: str  # folder | file | symlink
    targets: tuple[str, ...]  # every owned target whose folder holds the entry
    replaced: bool  # it took the place of an item respec installed

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "kind": self.kind,
            "targets": list(self.targets),
            "replaced": self.replaced,
        }


def real(path: Path | str) -> Path:
    """``path`` with its parent folders' symlinks resolved (not the entry itself)."""
    path = Path(path)
    return path.parent.resolve() / path.name


def digest(path: Path | str) -> str:
    """Fingerprint of an entry's content: names, file bytes and link targets.

    Symlinks are recorded by target and never followed. ``.DS_Store`` files
    (written by the macOS Finder when a folder is opened) are left out.
    """
    root = Path(path)
    hasher = hashlib.sha256()

    def add(relative: str, entry: Path) -> None:
        if entry.is_symlink():
            hasher.update(b"L\0" + relative.encode() + b"\0")
            hasher.update(os.readlink(entry).encode() + b"\0")
        elif entry.is_dir():
            hasher.update(b"D\0" + relative.encode() + b"\0")
            for child in sorted(entry.iterdir(), key=lambda c: c.name):
                if child.name in IGNORED_FILES:
                    continue
                add(f"{relative}/{child.name}", child)
        else:
            content = entry.read_bytes()
            hasher.update(b"F\0" + relative.encode() + b"\0")
            hasher.update(str(len(content)).encode() + b"\0" + content)

    add(".", root)
    return "sha256:" + hasher.hexdigest()


def is_managed(respec_home: Path, item: Installed) -> bool:
    """Whether the recorded path still holds what respec created there."""
    path = Path(item.path)
    if item.mode == "symlink":
        if not path.is_symlink():
            return False
        root = profiles.profiles_dir(respec_home).resolve()
        linked = path.resolve()
        return linked == root or root in linked.parents
    if item.digest is None or not os.path.lexists(path):
        return False
    try:
        return digest(path) == item.digest
    except OSError:
        return False


def folder_groups(state: State) -> list[tuple[Path, list[str]]]:
    """Owned folders as (folder, targets sharing it), first target first."""
    order = list(targets.registry())
    owned = sorted(
        state.owned.items(),
        key=lambda pair: (order.index(pair[0]) if pair[0] in order else len(order)),
    )
    groups: dict[Path, tuple[Path, list[str]]] = {}
    for target, entry in owned:
        folder = Path(entry.skills_dir)
        key = folder.resolve()
        if key in groups:
            groups[key][1].append(target)
        else:
            groups[key] = (folder, [target])
    return list(groups.values())


def kind_of(entry: Path) -> str:
    if entry.is_symlink():
        return "symlink"
    return "folder" if entry.is_dir() else "file"


def find_unknown(respec_home: Path, state: State) -> list[Unknown]:
    """Unknown entries in every owned folder, folder by folder, sorted by name."""
    managed = {
        real(item.path) for item in state.installed if is_managed(respec_home, item)
    }
    recorded = {real(item.path) for item in state.installed}
    found: list[Unknown] = []
    for folder, group in folder_groups(state):
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir(), key=lambda child: child.name):
            if entry.name.startswith("."):
                continue
            key = real(entry)
            if key in managed:
                continue
            found.append(
                Unknown(
                    name=entry.name,
                    path=str(entry),
                    kind=kind_of(entry),
                    targets=tuple(group),
                    replaced=key in recorded,
                )
            )
    return found


def folder_report(respec_home: Path, state: State) -> dict[str, dict[str, object]]:
    """Per owned target: the target it shares a folder with, and unknown entries."""
    entries = find_unknown(respec_home, state)
    report: dict[str, dict[str, object]] = {}
    for folder, group in folder_groups(state):
        first, aliases = group[0], group[1:]
        report[first] = {
            "same_as": None,
            "unknown": [e.to_dict() for e in entries if e.targets[0] == first],
        }
        for alias in aliases:
            report[alias] = {"same_as": first, "unknown": []}
    return report
