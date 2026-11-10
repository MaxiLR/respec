"""Profile switching: ``respec use`` removes the previous profile's skills and
installs the new profile's enabled skills into its targets.

Order of a switch:

1. Preflight (nothing changes): load the profile, check every enabled skill has
   a folder, and find the unknown entries in the way (:func:`conflicts`): those
   at a path the switch installs to, or at a recorded path it would remove (an
   edited or replaced copy). They refuse the switch with
   :class:`UnknownEntries` unless the caller passes ``on_unknown`` to resolve
   them (:mod:`respec.adopt`: add to the active profile, or remove). Unknown
   entries anywhere else do not block; callers report them as warnings.
2. Take over target folders seen for the first time: copy their full contents
   to ``<respec home>/backups/<timestamp>/<target>/`` and record ownership.
3. Resolve the entries in the way through ``on_unknown``.
4. Remove every path recorded in ``state.json`` (any folder, any target).
5. Link each enabled skill into each of the profile's targets (symlink, or copy
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


def describe(entry: unknown.Unknown) -> str:
    """How an unknown entry reads in messages."""
    if entry.replaced:
        return f"{entry.path} (an edited or replaced copy of skill {entry.name!r})"
    return f"{entry.path} ({entry.kind})"


class UnknownEntries(SwitchBlocked):
    """Entries respec did not place sit where it would install or remove a skill."""

    def __init__(
        self,
        profile: str,
        entries: list[unknown.Unknown],
        lead: str | None = None,
        note: str = "",
    ) -> None:
        self.profile = profile
        self.entries = entries
        lines = "\n".join(f"  - {describe(entry)}" for entry in entries)
        lead = lead or f"cannot switch to profile {profile!r}"
        super().__init__(
            f"{lead}: these entries are not managed by respec and sit where it "
            f"would install or remove a skill:\n{lines}\n"
            "Resolve them with 'respec adopt': add each to the active profile, "
            "or remove it (it is backed up first)." + (f"\n{note}" if note else "")
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


def _plan(
    profile: profiles.Profile, user_home: Path
) -> list[tuple[str, str, Path, Path]]:
    """Installs as (target, skill, source, destination)."""
    registry = targets.registry()
    plan: list[tuple[str, str, Path, Path]] = []
    seen_folders: set[Path] = set()
    enabled = [name for name, entry in profile.skills.items() if entry.enabled]
    for target in profile.targets:
        folder = registry[target].skills_dir(user_home)
        # Targets whose folders resolve to one real directory (for example
        # ~/.claude/skills linked to ~/.agents/skills) get each skill once.
        if folder.resolve() in seen_folders:
            continue
        seen_folders.add(folder.resolve())
        for skill in enabled:
            source = profile.path / profiles.SKILLS_DIR / skill
            plan.append((target, skill, source, folder / skill))
    return plan


def _check_sources(profile: profiles.Profile, lead: str) -> None:
    """Refuse when an enabled skill has no folder in the profile."""
    problems = [
        f"skill {skill!r} has no folder at {profile.path / profiles.SKILLS_DIR / skill}"
        for skill, entry in profile.skills.items()
        if entry.enabled and not (profile.path / profiles.SKILLS_DIR / skill).is_dir()
    ]
    if problems:
        raise SwitchBlocked(
            f"{lead}:\n" + "\n".join(f"  - {problem}" for problem in problems)
        )


def conflicts(
    respec_home: Path, user_home: Path, profile: profiles.Profile, state: State
) -> list[unknown.Unknown]:
    """Unknown entries in the way of activating ``profile``.

    That is every entry respec did not place (or that was edited or replaced)
    sitting exactly at a path the switch installs to or removes, including
    paths in folders respec does not own yet.
    """
    plan = _plan(profile, user_home)
    installs = {_real(destination) for _, _, _, destination in plan}
    recorded = {_real(Path(item.path)) for item in state.installed}
    found: list[unknown.Unknown] = []
    seen: set[Path] = set()
    for entry in unknown.find_unknown(respec_home, state):
        key = _real(Path(entry.path))
        if key in installs or key in recorded:
            found.append(entry)
            seen.add(key)
    managed = {
        _real(Path(item.path))
        for item in state.installed
        if unknown.is_managed(respec_home, item)
    }
    registry = targets.registry()
    sharing: dict[Path, list[str]] = {}
    for target in profile.targets:
        sharing.setdefault(registry[target].skills_dir(user_home).resolve(), []).append(
            target
        )
    for _, skill, _, destination in plan:
        key = _real(destination)
        if key in seen or key in managed or not os.path.lexists(destination):
            continue
        seen.add(key)
        found.append(
            unknown.Unknown(
                name=skill,
                path=str(destination),
                kind=unknown.kind_of(destination),
                targets=tuple(sharing[destination.parent.resolve()]),
                replaced=key in recorded,
            )
        )
    return found


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


@dataclass
class LinkResult:
    linked: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)  # destinations in the way


def link_skills(
    respec_home: Path, user_home: Path, name: str, skills: list[str]
) -> LinkResult:
    """Link ``skills`` of the active profile ``name`` without a full switch.

    Only folders respec already owns are touched. A destination that holds an
    unknown entry is left alone and reported in ``blocked``; other unknown
    entries do not matter. A managed copy is reinstalled so it matches the
    profile's current files; a managed link already points at them.
    """
    profile = profiles.load_profile(respec_home, name)
    state = load_state(respec_home)
    owned = {Path(entry.skills_dir).resolve() for entry in state.owned.values()}
    wanted = {
        skill
        for skill in skills
        if skill in profile.skills and profile.skills[skill].enabled
    }
    result = LinkResult()
    for target, skill, source, destination in _plan(profile, user_home):
        if skill not in wanted or destination.parent.resolve() not in owned:
            continue
        key = _real(destination)
        record = next((i for i in state.installed if _real(Path(i.path)) == key), None)
        if os.path.lexists(destination):
            if record is None or not unknown.is_managed(respec_home, record):
                result.blocked.append(str(destination))
                continue
            if record.mode == "symlink":
                continue
            remove_installed(respec_home, record)
        if record is not None:
            state.installed.remove(record)
        try:
            mode = _install(source, destination)
        except OSError as error:
            save_state(respec_home, state)
            raise RespecError(
                f"linking {skill!r} into {destination.parent} did not complete: "
                f"{error}"
            ) from None
        state.installed.append(
            Installed(
                target=target,
                name=skill,
                path=str(destination),
                mode=mode,
                digest=unknown.digest(destination) if mode == "copy" else None,
            )
        )
        save_state(respec_home, state)
        result.linked.append(str(destination))
    return result


def refuse_layer_conflicts(
    profile: profiles.Profile, action: str = "switch to"
) -> None:
    """Never install two skills of one exclusive layer; nothing changes."""
    conflicts = profiles.exclusivity_conflicts(profile)
    if conflicts:
        raise SwitchBlocked(
            f"cannot {action} profile {profile.name!r}:\n"
            + "\n".join(f"  - {conflict.message}" for conflict in conflicts)
        )


def use(
    respec_home: Path,
    user_home: Path,
    name: str,
    now: Clock = utc_now,
    on_unknown: UnknownHandler | None = None,
    action: str = "switch to",
) -> SwitchResult:
    """Activate profile ``name``; see the module docstring for the order.

    ``on_unknown`` receives the unknown entries in the way (:func:`conflicts`)
    after new folders are taken over and before anything is removed. Entries it
    leaves in place refuse the switch with :class:`UnknownEntries`. ``action``
    names what a refusal says could not be done ("cannot <action> profile"):
    ``"refresh"`` when an edited profile is re-applied.
    """
    profile = profiles.load_profile(respec_home, name)
    refuse_layer_conflicts(profile, action)
    lead = f"cannot {action} profile {profile.name!r}"
    state = load_state(respec_home)
    _check_sources(profile, lead)
    found = conflicts(respec_home, user_home, profile, state)
    if found and on_unknown is None:
        raise UnknownEntries(profile.name, found, lead=lead)
    result = SwitchResult(profile=profile.name, previous=state.active_profile)

    result.backups = _take_over(respec_home, user_home, profile, state, now)
    save_state(respec_home, state)

    if found and on_unknown is not None:
        on_unknown(found)
        profile = profiles.load_profile(respec_home, name)
        refuse_layer_conflicts(profile, action)
        state = load_state(respec_home)
        _check_sources(profile, lead)
        left = conflicts(respec_home, user_home, profile, state)
        if left:
            raise UnknownEntries(profile.name, left, lead=lead)
    plan = _plan(profile, user_home)

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
            "No profile is active. Skills installed so far are recorded in "
            "state.json and are removed by the next 'respec use'."
        ) from None

    state.active_profile = profile.name
    save_state(respec_home, state)
    return result


def status(respec_home: Path) -> dict[str, object]:
    """Active profile, its targets and the skills respec placed in each folder."""
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
            "skills": [
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
