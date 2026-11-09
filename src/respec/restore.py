"""Undo respec: ``respec restore [<backup>]`` puts a backup back and releases
ownership of every folder respec took over.

A backup is a run folder ``<respec home>/backups/<run>/`` holding one folder
per target. Takeover backups are written by the first ``respec use`` of a
target; ``respec adopt``/``--unknown backup`` runs hold single entries.

Without ``<backup>``, each owned folder gets the backup taken when respec first
took it over (the earliest takeover of all targets sharing that real folder);
a folder that did not exist then is removed again if it ends up empty. With
``<backup>``, each target folder in that run is restored from it; other owned
folders only lose respec's items.

Order of a restore:

0. Plan (nothing changes): pick the backup for each folder and the entries to
   put back. Entries respec itself created never come back: a symlink into the
   profiles folder, and, in a backup taken after the folder was already owned,
   a copy matching one respec records.
1. Conflicts: an entry in a folder being restored that respec does not manage
   and that differs from (or is absent from) the backup would be overwritten.
   Unknown entries go to ``on_unknown`` (the adopt flow: add, backup, keep);
   entries kept unmanaged stay unless the backup holds the same name. Whatever
   still conflicts refuses the restore with :class:`RestoreBlocked`, unless
   ``overwrite`` confirms it: then each is backed up to a fresh run first.
2. Apply (:func:`_apply`): back up confirmed conflicts, deactivate, remove
   every item respec manages (saving ``state.json`` after each), copy the
   backup's missing entries into place, then clear ``state.json``. A failure
   part way leaves ``state.json`` true to disk and ownership in place, so
   running the same restore again finishes it.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from respec import adopt, profiles, switch, targets, unknown
from respec.errors import RespecError
from respec.state import Installed, State, load_state, save_state


@dataclass(frozen=True)
class Backup:
    name: str
    path: str
    targets: tuple[str, ...]  # target folders the run holds
    takeover: tuple[str, ...]  # owned targets whose takeover backup this is

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "targets": list(self.targets),
            "takeover": list(self.takeover),
        }


@dataclass(frozen=True)
class FolderPlan:
    targets: tuple[str, ...]  # targets sharing the folder, first one first
    folder: Path
    source: Path | None  # backup folder; None: the folder did not exist
    entries: tuple[str, ...]  # names in ``source`` to put back


@dataclass
class RestoreResult:
    backup: str | None  # run name, or None for each folder's takeover backup
    restored: dict[str, str | None] = field(default_factory=dict)
    removed: list[Installed] = field(default_factory=list)
    set_aside: list[adopt.Resolution] = field(default_factory=list)
    released: list[str] = field(default_factory=list)


class RestoreBlocked(RespecError):
    """Restoring would overwrite entries respec does not manage; nothing changed."""

    def __init__(self, entries: list[unknown.Unknown]) -> None:
        self.entries = entries
        lines = "\n".join(f"  - {entry.path} ({entry.kind})" for entry in entries)
        super().__init__(
            "cannot restore: these entries are not managed by respec and would "
            f"be overwritten by the backup:\n{lines}\n"
            "Resolve them with 'respec adopt' or '--unknown add|backup|keep', "
            "or pass '--overwrite' to back them up and replace them."
        )


def _run_key(path: Path) -> tuple[str, int]:
    stamp, _, suffix = path.name.partition("-")
    return (stamp, int(suffix) if suffix.isdigit() else 1)


def list_backups(respec_home: Path) -> list[Backup]:
    """Backup runs, oldest first."""
    root = switch.backups_dir(respec_home)
    if not root.is_dir():
        return []
    state = load_state(respec_home)
    runs = sorted((p for p in root.iterdir() if p.is_dir()), key=_run_key)
    found: list[Backup] = []
    for run in runs:
        held = tuple(sorted(p.name for p in run.iterdir() if p.is_dir()))
        takeover = tuple(
            target
            for target, entry in state.owned.items()
            if entry.backup is not None and Path(entry.backup).parent == run
        )
        found.append(Backup(run.name, str(run), held, takeover))
    return found


def _find_run(respec_home: Path, name: str) -> Path:
    root = switch.backups_dir(respec_home)
    for run in list_backups(respec_home):
        if name in (run.name, run.path) or (
            Path(name).expanduser().absolute() == Path(run.path)
        ):
            return Path(run.path)
    available = ", ".join(b.name for b in list_backups(respec_home)) or "none"
    raise RespecError(f"no backup {name!r} in {root} (available: {available})")


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _respec_link(respec_home: Path, entry: Path, folder: Path) -> bool:
    """Whether a backed-up entry is a symlink respec made into a profile."""
    if not entry.is_symlink():
        return False
    target = Path(os.readlink(entry))
    if not target.is_absolute():
        target = folder / target
    root = profiles.profiles_dir(respec_home)
    return _within(Path(os.path.normpath(target)), Path(os.path.normpath(root))) or (
        _within(target.resolve(), root.resolve())
    )


def _same(left: Path, right: Path) -> bool:
    try:
        return unknown.digest(left) == unknown.digest(right)
    except OSError:
        return False


def _respec_copy(respec_home: Path, state: State, entry: Path) -> bool:
    """Whether a backed-up entry matches a copy respec installs: one recorded
    in ``state.json``, or any profile's item of that name."""
    known = {item.digest for item in state.installed if item.name == entry.name}
    for skills in profiles.profiles_dir(respec_home).glob(
        f"*/{profiles.SKILLS_DIR}/{entry.name}"
    ):
        try:
            known.add(unknown.digest(skills))
        except OSError:
            continue
    try:
        return unknown.digest(entry) in known
    except OSError:
        return False


def _entries(
    respec_home: Path, state: State, source: Path, folder: Path, pre_respec: bool
) -> tuple[str, ...]:
    """Names in ``source`` to put back; respec's own items are left out.

    Copies are only recognised in a backup taken after respec already owned
    the folder (``pre_respec`` false): a pre-respec backup may hold the user's
    original of an item later adopted into a profile, which must come back.
    """
    names: list[str] = []
    for entry in sorted(source.iterdir(), key=lambda child: child.name):
        if _respec_link(respec_home, entry, folder):
            continue
        if not pre_respec and _respec_copy(respec_home, state, entry):
            continue
        names.append(entry.name)
    return tuple(names)


def _oldest_run_holding(respec_home: Path, user_home: Path, key: Path) -> Path:
    """The oldest backup run holding a target whose folder resolves to ``key``."""
    registry = targets.registry()
    for backup in list_backups(respec_home):
        for target in backup.targets:
            if target in registry and (
                registry[target].skills_dir(user_home).resolve() == key
            ):
                return Path(backup.path)
    raise RespecError(f"no backup holds {key}")


def _plan(
    respec_home: Path, user_home: Path, state: State, run: Path | None
) -> list[FolderPlan]:
    groups = {
        folder.resolve(): (folder, group)
        for folder, group in unknown.folder_groups(state)
    }
    earliest: dict[Path, str | None] = {}
    for key, (_, group) in groups.items():
        first = min(
            group,
            key=lambda t: (state.owned[t].taken_over_at, state.owned[t].backup is None),
        )
        earliest[key] = state.owned[first].backup
    if run is None:
        plans = []
        for key, (folder, group) in groups.items():
            backup = earliest[key]
            source = Path(backup) if backup is not None else None
            if source is not None and not source.is_dir():
                raise RespecError(
                    f"the takeover backup of {folder} is missing: {source}; "
                    "name another with 'respec restore <backup>'"
                )
            entries = (
                _entries(respec_home, state, source, folder, pre_respec=True)
                if source is not None
                else ()
            )
            plans.append(FolderPlan(tuple(group), folder, source, entries))
        return plans
    registry = targets.registry()
    plans = []
    seen: set[Path] = set()
    held = [t for t in registry if (run / t).is_dir()]
    if not held:
        raise RespecError(f"backup {run.name!r} holds no target folder")
    for target in held:
        owned = state.owned.get(target)
        folder = (
            Path(owned.skills_dir) if owned else registry[target].skills_dir(user_home)
        )
        key = folder.resolve()
        if key in seen:
            continue
        seen.add(key)
        source = run / target
        group = groups.get(key, (folder, [target]))[1]
        if key in earliest:
            pre_respec = earliest[key] == str(source)
        else:
            pre_respec = _oldest_run_holding(respec_home, user_home, key) == run
        entries = _entries(respec_home, state, source, folder, pre_respec)
        plans.append(FolderPlan(tuple(group), folder, source, entries))
    return plans


def _conflicts(
    respec_home: Path, state: State, plans: list[FolderPlan]
) -> tuple[list[unknown.Unknown], list[unknown.Unknown]]:
    """(unknown entries, kept entries) that the restore would overwrite."""
    managed = {
        unknown.real(item.path)
        for item in state.installed
        if unknown.is_managed(respec_home, item)
    }
    recorded = {unknown.real(item.path) for item in state.installed}
    kept = {unknown.real(path) for path in state.unmanaged}
    found: list[unknown.Unknown] = []
    kept_found: list[unknown.Unknown] = []
    for plan in plans:
        if not plan.folder.is_dir():
            continue
        for entry in sorted(plan.folder.iterdir(), key=lambda child: child.name):
            key = unknown.real(entry)
            if key in managed:
                continue
            backed_up = plan.source is not None and entry.name in plan.entries
            if backed_up and _same(entry, plan.source / entry.name):
                continue
            if (key in kept or entry.name.startswith(".")) and not backed_up:
                continue
            conflict = unknown.Unknown(
                name=entry.name,
                path=str(entry),
                kind=_kind(entry),
                targets=plan.targets,
                replaced=key in recorded,
            )
            (kept_found if key in kept else found).append(conflict)
    return found, kept_found


def _kind(entry: Path) -> str:
    if entry.is_symlink():
        return "symlink"
    return "folder" if entry.is_dir() else "file"


def _put_back(source: Path, destination: Path) -> None:
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
        raise OSError(f"could not restore {destination} from {source}: {error}")


def _restore_folder(plan: FolderPlan) -> None:
    folder = plan.folder
    if plan.source is None:
        if folder.is_dir() and not folder.is_symlink() and not any(folder.iterdir()):
            folder.rmdir()
        return
    folder.mkdir(parents=True, exist_ok=True)
    for name in plan.entries:
        source, destination = plan.source / name, folder / name
        if os.path.lexists(destination):
            if _same(destination, source):
                continue
            raise OSError(f"{destination} appeared during the restore; left as is")
        _put_back(source, destination)


def _apply(
    respec_home: Path,
    plans: list[FolderPlan],
    overwritten: list[unknown.Unknown],
    result: RestoreResult,
    now: switch.Clock,
) -> None:
    """Every change a restore makes to disk and ``state.json``, in order."""
    if overwritten:
        result.set_aside = adopt.resolve(
            respec_home, overwritten, lambda entry: "backup", now=now
        )
    state = load_state(respec_home)
    state.active_profile = None
    save_state(respec_home, state)
    try:
        for item in list(state.installed):
            if switch.remove_installed(respec_home, item):
                result.removed.append(item)
            state.installed.remove(item)
            save_state(respec_home, state)
        for plan in plans:
            _restore_folder(plan)
            for target in plan.targets:
                result.restored[target] = str(plan.source) if plan.source else None
    except OSError as error:
        save_state(respec_home, state)
        again = f" {result.backup}" if result.backup else ""
        raise RespecError(
            f"restore did not complete: {error}\n"
            "respec's items are removed and no profile is active; respec still "
            f"owns its folders. Run 'respec restore{again}' again to finish."
        ) from None
    result.released = sorted(state.owned)
    save_state(respec_home, State())


def restore(
    respec_home: Path,
    user_home: Path,
    backup: str | None = None,
    on_unknown: switch.UnknownHandler | None = None,
    overwrite: bool = False,
    now: switch.Clock = switch.utc_now,
) -> RestoreResult:
    """Restore ``backup`` (default: each folder's takeover backup) and release."""
    state = load_state(respec_home)
    if backup is None and not state.owned:
        raise RespecError(
            "respec owns no folders; nothing to restore. "
            "Name a backup with 'respec restore <backup>' ('--list' shows them)."
        )
    run = _find_run(respec_home, backup) if backup is not None else None
    plans = _plan(respec_home, user_home, state, run)
    found, kept = _conflicts(respec_home, state, plans)
    if found and on_unknown is not None:
        on_unknown(found)
        state = load_state(respec_home)
        plans = _plan(respec_home, user_home, state, run)
        found, kept = _conflicts(respec_home, state, plans)
    blocking = found + kept
    if blocking and not overwrite:
        raise RestoreBlocked(blocking)
    result = RestoreResult(backup=run.name if run is not None else None)
    _apply(respec_home, plans, blocking, result, now)
    return result
