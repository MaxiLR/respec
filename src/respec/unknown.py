"""Unknown entries: anything in a folder respec owns that respec did not put there.

An entry is *managed* when ``state.json`` records it and it is still what respec
created: a recorded symlink must still be a symlink into the profiles folder,
a recorded copy must still exist. A recorded path that now holds something
else (for example a link replaced by a hand-made folder) is unknown again and
flagged ``replaced``. Entries the user chose to keep unmanaged are listed in
``state.unmanaged`` and are not unknown. Hidden entries (``.DS_Store`` and the
like) are never reported.

Targets whose folders resolve to one real directory are scanned once, under the
first of them in registry order; the others are its aliases.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from respec import profiles, targets
from respec.state import Installed, State


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


def is_managed(respec_home: Path, item: Installed) -> bool:
    """Whether the recorded path still holds what respec created there."""
    path = Path(item.path)
    if item.mode == "symlink":
        if not path.is_symlink():
            return False
        root = profiles.profiles_dir(respec_home).resolve()
        linked = path.resolve()
        return linked == root or root in linked.parents
    return os.path.lexists(path)


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


def _kind(entry: Path) -> str:
    if entry.is_symlink():
        return "symlink"
    return "folder" if entry.is_dir() else "file"


def find_unknown(respec_home: Path, state: State) -> list[Unknown]:
    """Unknown entries in every owned folder, folder by folder, sorted by name."""
    managed = {
        real(item.path) for item in state.installed if is_managed(respec_home, item)
    }
    recorded = {real(item.path) for item in state.installed}
    kept = {real(path) for path in state.unmanaged}
    found: list[Unknown] = []
    for folder, group in folder_groups(state):
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir(), key=lambda child: child.name):
            if entry.name.startswith("."):
                continue
            key = real(entry)
            if key in managed or key in kept:
                continue
            found.append(
                Unknown(
                    name=entry.name,
                    path=str(entry),
                    kind=_kind(entry),
                    targets=tuple(group),
                    replaced=key in recorded,
                )
            )
    return found


def folder_report(respec_home: Path, state: State) -> dict[str, dict[str, object]]:
    """Per owned target: its alias, unknown entries and kept unmanaged entries."""
    entries = find_unknown(respec_home, state)
    report: dict[str, dict[str, object]] = {}
    for folder, group in folder_groups(state):
        first, aliases = group[0], group[1:]
        real_folder = folder.resolve()
        kept = [
            {"name": Path(path).name, "path": path}
            for path in state.unmanaged
            if os.path.lexists(path) and real(path).parent == real_folder
        ]
        report[first] = {
            "same_as": None,
            "unknown": [e.to_dict() for e in entries if e.targets[0] == first],
            "unmanaged": kept,
        }
        for alias in aliases:
            report[alias] = {"same_as": first, "unknown": [], "unmanaged": []}
    return report
