"""Profile switching: ``respec use`` removes the previous profile's items and
installs the new profile's enabled skills into its targets.

Order of a switch:

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

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from respec import profiles, targets
from respec.errors import RespecError
from respec.state import Installed, Owned, State, load_state, save_state

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SwitchResult:
    profile: str
    previous: str | None
    backups: dict[str, str] = field(default_factory=dict)
    removed: list[Installed] = field(default_factory=list)
    installed: list[Installed] = field(default_factory=list)


def backups_dir(respec_home: Path) -> Path:
    return respec_home / "backups"


def _new_backup_run(respec_home: Path, moment: datetime) -> Path:
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


def _preflight(
    profile: profiles.Profile, state: State, user_home: Path
) -> list[tuple[str, str, Path, Path]]:
    """Plan installs as (target, skill, source, destination); fail on conflicts."""
    registry = targets.registry()
    recorded = {item.path for item in state.installed}
    plan: list[tuple[str, str, Path, Path]] = []
    problems: list[str] = []
    enabled = [name for name, entry in profile.skills.items() if entry.enabled]
    for skill in enabled:
        source = profile.path / profiles.SKILLS_DIR / skill
        if not source.is_dir():
            problems.append(f"skill {skill!r} has no folder at {source}")
    for target in profile.targets:
        folder = registry[target].skills_dir(user_home)
        for skill in enabled:
            destination = folder / skill
            if os.path.lexists(destination) and str(destination) not in recorded:
                problems.append(
                    f"{destination} already exists and is not managed by respec; "
                    "move it out of the way before switching"
                )
            source = profile.path / profiles.SKILLS_DIR / skill
            plan.append((target, skill, source, destination))
    if problems:
        raise RespecError(
            f"cannot switch to profile {profile.name!r}:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )
    return plan


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
    for target in new_targets:
        folder = registry[target].skills_dir(user_home)
        backup: str | None = None
        if folder.is_dir():
            if run_dir is None:
                run_dir = _new_backup_run(respec_home, moment)
            destination = run_dir / target
            shutil.copytree(folder, destination, symlinks=True)
            backup = str(destination)
            backups[target] = backup
        state.owned[target] = Owned(
            skills_dir=str(folder),
            backup=backup,
            taken_over_at=moment.isoformat(),
        )
    return backups


def _remove(respec_home: Path, item: Installed) -> bool:
    """Remove one recorded path; never follow links into profile folders."""
    path = Path(item.path)
    if path.is_symlink():
        path.unlink()
        return True
    if not path.exists():
        return False
    if item.mode != "copy":
        # A recorded symlink was replaced by something else; leave it alone.
        return False
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(source, destination, target_is_directory=True)
        return "symlink"
    except OSError:
        shutil.copytree(source, destination, symlinks=True)
        return "copy"


def use(
    respec_home: Path,
    user_home: Path,
    name: str,
    now: Clock = _utc_now,
) -> SwitchResult:
    """Activate profile ``name``; see the module docstring for the order."""
    profile = profiles.load_profile(respec_home, name)
    state = load_state(respec_home)
    plan = _preflight(profile, state, user_home)
    result = SwitchResult(profile=profile.name, previous=state.active_profile)

    result.backups = _take_over(respec_home, user_home, profile, state, now)
    save_state(respec_home, state)

    for item in state.installed:
        if _remove(respec_home, item):
            result.removed.append(item)
    state.installed = []
    state.active_profile = None
    save_state(respec_home, state)

    for target, skill, source, destination in plan:
        mode = _install(source, destination)
        record = Installed(target=target, name=skill, path=str(destination), mode=mode)
        state.installed.append(record)
        result.installed.append(record)
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
    folders = [
        {
            "target": target,
            "skills_dir": entry.skills_dir,
            "items": [
                {"name": item.name, "path": item.path, "mode": item.mode}
                for item in sorted(state.installed, key=lambda i: i.name)
                if item.target == target
            ],
        }
        for target, entry in owned
    ]
    return {
        "active_profile": state.active_profile,
        "targets": active_targets,
        "folders": folders,
    }
