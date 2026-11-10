"""Unknown entries: anything in a folder respec owns that respec did not put there.

An entry is *managed* when ``state.json`` records it and it is still what respec
created: a recorded symlink must still be a symlink into the profiles folder
(or into respec's global or shipped skill folders),
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

import os
from dataclasses import dataclass
from pathlib import Path

from respec import global_skills, targets, trees
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


def is_managed(respec_home: Path, item: Installed) -> bool:
    """Whether the recorded path still holds what respec created there."""
    path = Path(item.path)
    if item.mode == "symlink":
        if not path.is_symlink():
            return False
        linked = path.resolve()
        return any(
            linked == root or root in linked.parents
            for root in global_skills.source_roots(respec_home)
        )
    if item.digest is None or not os.path.lexists(path):
        return False
    try:
        return trees.digest(path) == item.digest
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
        trees.real(item.path)
        for item in state.installed
        if is_managed(respec_home, item)
    }
    recorded = {trees.real(item.path) for item in state.installed}
    found: list[Unknown] = []
    for folder, group in folder_groups(state):
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir(), key=lambda child: child.name):
            if entry.name.startswith("."):
                continue
            key = trees.real(entry)
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
