"""Undo respec: ``respec restore [<backup>]`` puts a backup back and releases
ownership of every folder respec took over.

A backup is a run folder ``<respec home>/backups/<run>/`` holding one folder
per target. Takeover backups are written by the first ``respec use`` of a
target; ``respec adopt``/``--unknown remove`` runs hold single entries.

Without ``<backup>``, each owned folder gets the backup taken when respec first
took it over (the earliest takeover of all targets sharing that real folder);
a folder that did not exist then is removed again if it ends up empty. With
``<backup>``, each target folder in that run is restored from it; other owned
folders only lose respec's items.

Order of a restore:

0. Plan (nothing changes): pick the backup for each folder and the entries to
   put back. Entries respec itself created never come back, judged only by
   facts from backup time: a symlink into the profiles folder (or respec's
   global or shipped skill folders), or a copy whose
   digest matches one the backup run's ``manifest.json`` says respec had
   installed there. Skipped entries are reported.
1. Conflicts: an entry in a folder being restored that respec does not manage
   and that differs from (or is absent from) the backup would be overwritten.
   Unknown entries go to ``on_unknown`` (the adopt flow: add or remove);
   hidden entries stay, and are reported, unless the backup holds the same
   name. Entries count as identical only with the same bytes, link targets and
   permissions. Whatever
   still conflicts refuses the restore with :class:`RestoreBlocked`, unless
   ``overwrite`` confirms it: then each is backed up to a fresh run first.
2. Apply (:func:`_apply`): back up confirmed conflicts, deactivate, remove
   every item respec manages (saving ``state.json`` after each), copy the
   backup's missing entries into place, then clear ``state.json``. A failure
   part way leaves ``state.json`` true to disk and ownership in place, so
   running the same restore again finishes it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from respec import adopt, global_skills, journal, switch, targets, trees, unknown
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
    skipped: tuple[str, ...]  # names in ``source`` that are respec's own items


@dataclass
class RestoreResult:
    backup: str | None  # run name, or None for each folder's takeover backup
    restored: dict[str, str | None] = field(default_factory=dict)
    removed: list[Installed] = field(default_factory=list)
    set_aside: list[adopt.Resolution] = field(default_factory=list)
    released: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # backup paths left out
    left: list[str] = field(default_factory=list)  # hidden, not in the backup


class RestoreBlocked(RespecError):
    """Restoring would overwrite entries respec does not manage; nothing changed."""

    def __init__(self, entries: list[unknown.Unknown]) -> None:
        self.entries = entries
        lines = "\n".join(f"  - {entry.path} ({entry.kind})" for entry in entries)
        super().__init__(
            "cannot restore: these entries are not managed by respec and would "
            f"be overwritten by the backup:\n{lines}\n"
            "Resolve them with 'respec adopt' or '--unknown add|remove', "
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
        if not held:
            continue  # nothing to restore (for example a damaged state.json)
        recorded = _recorded_takeovers(run)
        takeover = tuple(
            target
            for target in held
            if target in recorded
            or any(
                entry.backup is not None and Path(entry.backup) == run / target
                for entry in state.owned.values()
            )
        )
        found.append(Backup(run.name, str(run), held, takeover))
    return found


def _recorded_takeovers(run: Path) -> set[str]:
    """Targets whose takeover backup the run's manifest records."""
    try:
        data = json.loads((run / switch.BACKUP_MANIFEST).read_text("utf-8"))
        return {
            target
            for target, record in data.get("takeover", {}).items()
            if record.get("backup")
        }
    except (OSError, ValueError, AttributeError):
        return set()


def find_run(respec_home: Path, name: str) -> Path:
    """The backup run named ``name`` (by name or path)."""
    return _find_run(respec_home, name)


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
    """Whether a backed-up entry is a symlink into respec's profiles folder
    (or its global or shipped skill folders), by its written or real path."""
    if not entry.is_symlink():
        return False
    target = Path(os.readlink(entry))
    if not target.is_absolute():
        target = folder / target
    written = Path(os.path.normpath(target))
    return any(
        _within(written, Path(os.path.normpath(root)))
        for root in global_skills.source_roots(respec_home, resolve=False)
    ) or any(
        _within(target.resolve(), root)
        for root in global_skills.source_roots(respec_home)
    )


def _recorded_at_backup(run: Path, target: str) -> list[dict[str, object]]:
    """Items respec had installed in ``target``'s folder when ``run`` was taken."""
    manifest = run / switch.BACKUP_MANIFEST
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text("utf-8"))
        items = data["installed"].get(target, [])
    except (OSError, ValueError, KeyError, AttributeError) as error:
        raise RespecError(f"invalid backup manifest {manifest}: {error}") from None
    return [item for item in items if isinstance(item, dict)]


def _entries(
    respec_home: Path, source: Path, target: str, folder: Path
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(names to put back, names left out as respec's own items).

    Left out are symlinks into the profiles folder and copies whose content
    matches a copy respec had recorded in that folder when the backup was
    taken (see :func:`respec.switch._record_backed_up_items`). Nothing is
    judged by current profiles.
    """
    copies = {
        item.get("name"): item.get("digest")
        for item in _recorded_at_backup(source.parent, target)
        if item.get("mode") == "copy" and item.get("digest")
    }
    names: list[str] = []
    skipped: list[str] = []
    for entry in sorted(source.iterdir(), key=lambda child: child.name):
        respec_own = _respec_link(respec_home, entry, folder)
        if not respec_own and entry.name in copies and not entry.is_symlink():
            try:
                respec_own = trees.digest(entry) == copies[entry.name]
            except OSError:
                respec_own = False
        (skipped if respec_own else names).append(entry.name)
    return tuple(names), tuple(skipped)


def _plan(
    respec_home: Path, user_home: Path, state: State, run: Path | None
) -> list[FolderPlan]:
    groups = {
        folder.resolve(): (folder, group)
        for folder, group in unknown.folder_groups(state)
    }
    plans: list[FolderPlan] = []
    if run is None:
        unknown_takeover = sorted(
            target for target, entry in state.owned.items() if entry.takeover_unknown
        )
        if unknown_takeover:
            raise RespecError(
                "cannot restore without naming a backup: state.json was rebuilt "
                "and respec no longer knows the takeover backup of "
                f"{', '.join(unknown_takeover)}. Nothing was changed. Name the "
                "backup run to put back: 'respec restore <backup>' "
                "('respec restore --list' shows them)."
            )
        for folder, group in groups.values():
            first = min(
                group,
                key=lambda t: (
                    state.owned[t].taken_over_at,
                    state.owned[t].backup is None,
                ),
            )
            backup = state.owned[first].backup
            if backup is None:
                plans.append(FolderPlan(tuple(group), folder, None, (), ()))
                continue
            source = Path(backup)
            if not source.is_dir():
                raise RespecError(
                    f"the takeover backup of {folder} is missing: {source}; "
                    "name another with 'respec restore <backup>'"
                )
            entries, skipped = _entries(respec_home, source, first, folder)
            plans.append(FolderPlan(tuple(group), folder, source, entries, skipped))
        return plans
    registry = targets.registry()
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
        entries, skipped = _entries(respec_home, source, target, folder)
        plans.append(FolderPlan(tuple(group), folder, source, entries, skipped))
    return plans


def _conflicts(
    respec_home: Path, state: State, plans: list[FolderPlan]
) -> tuple[list[unknown.Unknown], list[str]]:
    """Unknown entries the restore would overwrite, and the hidden entries it
    leaves in place because the backup lacks them."""
    managed = {
        trees.real(item.path)
        for item in state.installed
        if unknown.is_managed(respec_home, item)
    }
    recorded = {trees.real(item.path) for item in state.installed}
    found: list[unknown.Unknown] = []
    left: list[str] = []
    for plan in plans:
        if not plan.folder.is_dir():
            continue
        for entry in sorted(plan.folder.iterdir(), key=lambda child: child.name):
            key = trees.real(entry)
            if key in managed:
                continue
            backed_up = plan.source is not None and entry.name in plan.entries
            if backed_up and trees.same_entry(entry, plan.source / entry.name):
                continue
            if entry.name.startswith(".") and not backed_up:
                left.append(str(entry))
                continue
            conflict = unknown.Unknown(
                name=entry.name,
                path=str(entry),
                kind=unknown.kind_of(entry),
                targets=plan.targets,
                replaced=key in recorded,
            )
            found.append(conflict)
    return found, left


def _put_back(source: Path, destination: Path) -> None:
    try:
        trees.copy_entry(source, destination)
    except OSError as error:
        raise OSError(
            f"could not restore {destination} from {source}: {error}"
        ) from None


def _restore_folder(respec_home: Path, plan: FolderPlan) -> None:
    folder = plan.folder
    if plan.source is None:
        if folder.is_dir() and not folder.is_symlink() and not any(folder.iterdir()):
            folder.rmdir()
        return
    folder.mkdir(parents=True, exist_ok=True)
    for name in plan.entries:
        source, destination = plan.source / name, folder / name
        if os.path.lexists(destination):
            if trees.same_entry(destination, source):
                continue
            raise OSError(f"{destination} appeared during the restore; left as is")
        journal.mark(
            respec_home,
            {
                "step": "put-back",
                "path": str(destination),
                "source": str(source),
                "target": plan.targets[0],
            },
        )
        _put_back(source, destination)
        journal.checkpoint("put-back")
        journal.mark(respec_home, None)


def _remove_created(state: State, plans: list[FolderPlan]) -> None:
    """Remove the folders respec created at takeover that are empty again.

    Only folders of targets left without a backup to restore (it did not exist
    at takeover, or a named backup does not hold it) are considered; a folder
    that holds anything, or is a symlink, stays.
    """
    restored = {
        target for plan in plans if plan.source is not None for target in plan.targets
    }
    folders = {
        Path(path)
        for target, entry in state.owned.items()
        if target not in restored
        for path in entry.created
    }
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        try:
            if folder.is_dir() and not folder.is_symlink():
                folder.rmdir()
        except OSError:
            pass  # not empty: something else lives there now


def _apply(
    respec_home: Path,
    plans: list[FolderPlan],
    overwritten: list[unknown.Unknown],
    result: RestoreResult,
    now: switch.Clock,
) -> None:
    """Every change a restore makes to disk and ``state.json``, in order.

    Journaled (see :mod:`respec.journal`): a crash part way is finished by
    the next respec command.
    """
    with journal.begin(respec_home, "restore", backup=result.backup, phase="prepare"):
        if overwritten:
            adopt.resolve(
                respec_home,
                overwritten,
                lambda entry: "remove",
                None,
                now=now,
                done=result.set_aside,
            )
        state = load_state(respec_home)
        state.active_profile = None
        journal.set_phase(respec_home, "apply", state)
        try:
            for item in list(state.installed):
                if switch.remove_step(respec_home, state, item):
                    result.removed.append(item)
            for plan in plans:
                _restore_folder(respec_home, plan)
                for target in plan.targets:
                    result.restored[target] = str(plan.source) if plan.source else None
        except OSError as error:
            again = f" {result.backup}" if result.backup else ""
            raise RespecError(
                f"restore did not complete: {error}\n"
                "respec's skills are removed and no profile is active; respec "
                f"still owns its folders. Run 'respec restore{again}' (or any "
                "respec command that changes skills) to finish it."
            ) from None
        result.released = sorted(state.owned)
        _remove_created(state, plans)
        save_state(respec_home, State())


def restore(
    respec_home: Path,
    user_home: Path,
    backup: str | None = None,
    on_unknown: switch.UnknownHandler | None = None,
    overwrite: bool = False,
    now: switch.Clock = switch.utc_now,
    progress: RestoreResult | None = None,
) -> RestoreResult:
    """Restore ``backup`` (default: each folder's takeover backup) and release.

    Given ``progress``, that result is filled in as the restore goes and
    returned, so a caller can report what was done when it fails part way.
    """
    journal.ready(respec_home, user_home)
    state = load_state(respec_home)
    if backup is None and not state.owned:
        raise RespecError(
            "respec owns no folders; nothing to restore. "
            "Name a backup with 'respec restore <backup>' ('--list' shows them)."
        )
    run = _find_run(respec_home, backup) if backup is not None else None
    plans = _plan(respec_home, user_home, state, run)
    found, left = _conflicts(respec_home, state, plans)
    if found and on_unknown is not None:
        on_unknown(found)
        state = load_state(respec_home)
        plans = _plan(respec_home, user_home, state, run)
        found, left = _conflicts(respec_home, state, plans)
    if found and not overwrite:
        raise RestoreBlocked(found)
    result = progress if progress is not None else RestoreResult(backup=None)
    result.backup = run.name if run is not None else None
    result.left = left
    result.skipped = [
        str(plan.source / name)
        for plan in plans
        if plan.source is not None
        for name in plan.skipped
    ]
    _apply(respec_home, plans, found, result, now)
    return result
