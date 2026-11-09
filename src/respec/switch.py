"""Profile switching: ``respec use`` removes the previous profile's items and
installs the new profile's enabled skills into its targets.

Order of a switch:

0. Unknown entries in owned folders (see :mod:`respec.unknown`): refuse with
   :class:`UnknownEntries` unless the caller passes ``on_unknown`` to resolve
   them (add to the profile, back up and remove, or keep unmanaged).
1. Preflight (nothing changes): load the profile, check every enabled skill has
   a folder, and refuse when an install path is occupied by an entry respec did
   not create.
2. Take over target folders seen for the first time: copy their full contents
   to ``<respec home>/backups/<timestamp>/<target>/`` and record ownership.
3. Remove every path recorded in ``state.json`` (any folder, any target).
4. Link each enabled skill into each of the profile's targets (symlink, or copy
   when symlinking fails) and record every created path.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from respec import profiles, targets, unknown
from respec.errors import RespecError
from respec.state import Installed, Owned, State, load_state, save_state

Clock = Callable[[], datetime]
UnknownHandler = Callable[[list[unknown.Unknown]], None]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SwitchResult:
    profile: str
    previous: str | None
    backups: dict[str, str] = field(default_factory=dict)
    removed: list[Installed] = field(default_factory=list)
    installed: list[Installed] = field(default_factory=list)


class SwitchBlocked(RespecError):
    """The preflight refused the switch; nothing on disk was changed."""


class UnknownEntries(SwitchBlocked):
    """Owned folders hold entries respec did not create; the user must choose."""

    def __init__(self, profile: str, entries: list[unknown.Unknown]) -> None:
        self.entries = entries
        lines = "\n".join(
            f"  - {entry.path} ({entry.kind}"
            + (", replaced an item respec installed)" if entry.replaced else ")")
            for entry in entries
        )
        super().__init__(
            f"cannot switch to profile {profile!r}: folders respec owns hold "
            f"entries not managed by respec:\n{lines}\n"
            "Choose for each: add to profile, back up and remove, or keep "
            "unmanaged. Run 'respec adopt', or pass '--unknown add|backup|keep' "
            "to 'respec use'."
        )


def backups_dir(respec_home: Path) -> Path:
    return respec_home / "backups"


def new_backup_run(respec_home: Path, moment: datetime) -> Path:
    """Create a fresh backup run folder; never reuse one from the same second."""
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent = backups_dir(respec_home)
    parent.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        candidate = parent / (stamp if suffix == 1 else f"{stamp}-{suffix}")
        try:
            candidate.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        return candidate


def _real(path: Path) -> Path:
    """``path`` with its parent folders' symlinks resolved (not the entry itself)."""
    return path.parent.resolve() / path.name


def _preflight(
    profile: profiles.Profile, state: State, user_home: Path
) -> list[tuple[str, str, Path, Path]]:
    """Plan installs as (target, skill, source, destination); fail on conflicts."""
    registry = targets.registry()
    recorded = {_real(Path(item.path)) for item in state.installed}
    plan: list[tuple[str, str, Path, Path]] = []
    seen_folders: set[Path] = set()
    problems: list[str] = []
    enabled = [name for name, entry in profile.skills.items() if entry.enabled]
    for skill in enabled:
        source = profile.path / profiles.SKILLS_DIR / skill
        if not source.is_dir():
            problems.append(f"skill {skill!r} has no folder at {source}")
    for target in profile.targets:
        folder = registry[target].skills_dir(user_home)
        # Targets whose folders resolve to one real directory (for example
        # ~/.claude/skills linked to ~/.agents/skills) get each skill once.
        if folder.resolve() in seen_folders:
            continue
        seen_folders.add(folder.resolve())
        for skill in enabled:
            destination = folder / skill
            if os.path.lexists(destination) and _real(destination) not in recorded:
                problems.append(
                    f"{destination} already exists and is not managed by respec; "
                    "move it out of the way before switching"
                )
            source = profile.path / profiles.SKILLS_DIR / skill
            plan.append((target, skill, source, destination))
    if problems:
        raise SwitchBlocked(
            f"cannot switch to profile {profile.name!r}:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )
    return plan


BACKUP_MANIFEST = "manifest.json"


def _record_backed_up_items(
    run_dir: Path, target: str, folder: Path, state: State
) -> None:
    """Note, next to a takeover backup, which entries respec had installed in
    the folder when it was copied (a folder another target already owns).
    Without such items no manifest is written.

    ``respec restore`` uses this record of backup time to leave respec's own
    items out; it never guesses from current profiles.
    """
    real_folder = folder.resolve()
    items = [
        item.to_dict()
        for item in state.installed
        if unknown.real(item.path).parent == real_folder
    ]
    if not items:
        return
    manifest = run_dir / BACKUP_MANIFEST
    data = json.loads(manifest.read_text("utf-8")) if manifest.exists() else {}
    data.setdefault("version", 1)
    data.setdefault("installed", {})[target] = items
    manifest.write_text(json.dumps(data, indent=2) + "\n", "utf-8")


def _take_over(
    respec_home: Path,
    user_home: Path,
    profile: profiles.Profile,
    state: State,
    now: Clock,
) -> dict[str, str]:
    """Back up and record every target folder respec has not owned before."""
    registry = targets.registry()
    new_targets = [t for t in profile.targets if t not in state.owned]
    if not new_targets:
        return {}
    moment = now()
    run_dir: Path | None = None
    backups: dict[str, str] = {}
    owned: dict[str, Owned] = {}
    for target in new_targets:
        folder = registry[target].skills_dir(user_home)
        backup: str | None = None
        if folder.is_dir():
            if run_dir is None:
                run_dir = new_backup_run(respec_home, moment)
            destination = run_dir / target
            try:
                shutil.copytree(folder, destination, symlinks=True)
                _record_backed_up_items(run_dir, target, folder, state)
            except (OSError, shutil.Error) as error:
                # Nothing has changed yet: drop the partial backup run and stop.
                shutil.rmtree(run_dir, ignore_errors=True)
                raise RespecError(
                    f"could not back up {folder} before taking it over; "
                    f"nothing was changed: {error}"
                ) from None
            backup = str(destination)
            backups[target] = backup
        owned[target] = Owned(
            skills_dir=str(folder),
            backup=backup,
            taken_over_at=moment.isoformat(),
        )
    state.owned.update(owned)
    return backups


def remove_installed(respec_home: Path, item: Installed) -> bool:
    """Remove one recorded path that still holds what respec created there.

    Never follows links into profile folders. A path that was replaced or
    edited is left alone; :func:`use` resolves it as unknown before removal.
    """
    path = Path(item.path)
    if not unknown.is_managed(respec_home, item):
        # The recorded path no longer holds what respec created; leave it alone.
        return False
    if path.is_symlink():
        path.unlink()
        return True
    profiles_root = profiles.profiles_dir(respec_home).resolve()
    resolved = path.resolve()
    if resolved == profiles_root or profiles_root in resolved.parents:
        raise RespecError(f"refusing to delete {path}: it is inside a profile folder")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _install(source: Path, destination: Path) -> str:
    """Symlink ``source`` at ``destination``, copying when links are refused.

    Raises ``OSError`` with nothing left at ``destination`` when neither works.
    An existing destination is never overwritten or copied into.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(source, destination, target_is_directory=True)
        return "symlink"
    except FileExistsError:
        raise
    except OSError:
        pass
    try:
        shutil.copytree(source, destination, symlinks=True)
    except (OSError, shutil.Error) as error:
        shutil.rmtree(destination, ignore_errors=True)
        raise OSError(f"could not link or copy {source} to {destination}: {error}")
    return "copy"


def _forget_replaced(respec_home: Path) -> None:
    """Drop records of paths that now hold a foreign entry; it is not respec's."""
    state = load_state(respec_home)
    replaced = {
        unknown.real(entry.path)
        for entry in unknown.find_unknown(respec_home, state)
        if entry.replaced
    }
    if not replaced:
        return
    state.installed = [
        item for item in state.installed if unknown.real(item.path) not in replaced
    ]
    save_state(respec_home, state)


def use(
    respec_home: Path,
    user_home: Path,
    name: str,
    now: Clock = utc_now,
    on_unknown: UnknownHandler | None = None,
) -> SwitchResult:
    """Activate profile ``name``; see the module docstring for the order.

    ``on_unknown`` receives the unknown entries of owned folders before
    anything else happens; entries it leaves in place stay untouched.
    """
    profile = profiles.load_profile(respec_home, name)
    entries = unknown.find_unknown(respec_home, load_state(respec_home))
    if entries:
        if on_unknown is None:
            raise UnknownEntries(profile.name, entries)
        on_unknown(entries)
        _forget_replaced(respec_home)
        profile = profiles.load_profile(respec_home, name)
    state = load_state(respec_home)
    plan = _preflight(profile, state, user_home)
    result = SwitchResult(profile=profile.name, previous=state.active_profile)

    result.backups = _take_over(respec_home, user_home, profile, state, now)
    save_state(respec_home, state)

    # state.json is saved after every removal and every install, so it always
    # lists each path respec has created and a later switch can remove it.
    state.active_profile = None
    try:
        for item in list(state.installed):
            if remove_installed(respec_home, item):
                result.removed.append(item)
            state.installed.remove(item)
            save_state(respec_home, state)

        for target, skill, source, destination in plan:
            mode = _install(source, destination)
            record = Installed(
                target=target,
                name=skill,
                path=str(destination),
                mode=mode,
                digest=unknown.digest(destination) if mode == "copy" else None,
            )
            state.installed.append(record)
            result.installed.append(record)
            save_state(respec_home, state)
    except OSError as error:
        save_state(respec_home, state)
        raise RespecError(
            f"switch to profile {profile.name!r} did not complete: {error}\n"
            "No profile is active. Items installed so far are recorded in "
            "state.json and are removed by the next 'respec use'."
        ) from None

    state.active_profile = profile.name
    save_state(respec_home, state)
    return result


def status(respec_home: Path) -> dict[str, object]:
    """Active profile, its targets and the items respec placed in each folder."""
    state = load_state(respec_home)
    active_targets: list[str] = []
    if state.active_profile is not None:
        try:
            profile = profiles.load_profile(respec_home, state.active_profile)
            active_targets = list(profile.targets)
        except RespecError:
            active_targets = sorted({item.target for item in state.installed})
    order = list(targets.registry())
    owned = sorted(
        state.owned.items(),
        key=lambda pair: (order.index(pair[0]) if pair[0] in order else len(order)),
    )
    extra = unknown.folder_report(respec_home, state)
    # Targets sharing one real folder list its items once, under the first.
    sharing = {group[0]: group for _, group in unknown.folder_groups(state)}
    folders = [
        {
            "target": target,
            "skills_dir": entry.skills_dir,
            "items": [
                {"name": item.name, "path": item.path, "mode": item.mode}
                for item in sorted(state.installed, key=lambda i: i.name)
                if item.target in sharing.get(target, ())
                and unknown.is_managed(respec_home, item)
            ],
            **extra[target],
        }
        for target, entry in owned
    ]
    return {
        "active_profile": state.active_profile,
        "targets": active_targets,
        "folders": folders,
    }
