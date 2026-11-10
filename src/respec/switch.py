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

Global skills (``config.yaml``) join the profile's skills in its targets, and
the skills respec ships go into every registered target (see
:mod:`respec.global_skills`); a shipped or global skill whose link is already
in place is kept rather than removed and linked again.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from respec import global_skills, profiles, targets, trees, unknown
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
    """Entries respec did not place sit where it would install or remove a skill.

    ``clashes`` maps the path of an entry named like a shipped or global skill
    to why it can only be removed (:func:`respec.global_skills.clash`).
    """

    def __init__(
        self,
        profile: str,
        entries: list[unknown.Unknown],
        lead: str | None = None,
        note: str = "",
        can_add: bool = True,
        clashes: dict[str, str] | None = None,
    ) -> None:
        self.profile = profile
        self.entries = entries
        self.clashes = dict(clashes or {})
        lines = "\n".join(
            f"  - {describe(entry)}"
            + (f": {self.clashes[entry.path]}" if entry.path in self.clashes else "")
            for entry in entries
        )
        lead = lead or f"cannot switch to profile {profile!r}"
        super().__init__(
            f"{lead}: these entries are not managed by respec and sit where it "
            f"would install or remove a skill:\n{lines}\n"
            + (
                "Resolve them with 'respec adopt': add each to the active "
                "profile, or remove it (it is backed up first)."
                if can_add
                else "No profile is active, so they can only be removed (each is "
                "backed up first): run 'respec adopt --remove <name>'."
            )
            + (f"\n{note}" if note else "")
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


def _plan_all(
    respec_home: Path, user_home: Path, profile: profiles.Profile
) -> list[tuple[str, str, Path, Path]]:
    """Every install of a switch: the profile's enabled skills and global
    skills into its targets, respec's shipped skills into every target.

    A folder shared by several targets gets each skill once.
    """
    registry = targets.registry()
    plan = list(_plan(profile, user_home))
    seen = {trees.real(destination) for _, _, _, destination in plan}

    def add(target_names: list[str], skill: str, source: Path) -> None:
        for target in target_names:
            destination = registry[target].skills_dir(user_home) / skill
            key = trees.real(destination)
            if key not in seen:
                seen.add(key)
                plan.append((target, skill, source, destination))

    for skill in global_skills.load_global(respec_home):
        add(
            list(profile.targets),
            skill,
            global_skills.global_source(respec_home, skill),
        )
    for skill in global_skills.shipped_names():
        add(list(registry), skill, global_skills.shipped_source(respec_home, skill))
    return plan


def plan(
    respec_home: Path, user_home: Path, profile: profiles.Profile
) -> list[tuple[str, str, Path, Path]]:
    """Everything :func:`use` installs for ``profile``, as (target, skill,
    source, destination): its enabled skills, global skills and respec's
    shipped skills. The public seam for checks that compare against a switch.
    """
    return _plan_all(respec_home, user_home, profile)


def _switch_targets(profile: profiles.Profile) -> list[str]:
    """Targets a switch to ``profile`` writes into, in registry order."""
    wanted = set(profile.targets)
    if global_skills.shipped_names():
        wanted.update(targets.registry())
    return [target for target in targets.registry() if target in wanted]


def _check_global(respec_home: Path, profile: profiles.Profile, lead: str) -> None:
    """Refuse when a global skill has no folder or a profile skill takes the
    name of a global or shipped skill."""
    try:
        names = global_skills.load_global(respec_home)
    except RespecError as error:
        raise SwitchBlocked(f"{lead}: {error}") from None
    problems = global_skills.check_sources(respec_home, names)
    lasting = global_skills.kinds(names)
    for skill, entry in profile.skills.items():
        if not entry.enabled:
            continue
        if lasting.get(skill) == global_skills.SHIPPED:
            problems.append(
                f"skill {skill!r} has the name of a skill respec ships and "
                "installs everywhere; rename or remove the profile's skill"
            )
        elif lasting.get(skill) == global_skills.GLOBAL:
            problems.append(
                f"skill {skill!r} is also a global skill in "
                f"{global_skills.config_path(respec_home)}; rename one of them"
            )
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
    plan = _plan_all(respec_home, user_home, profile)
    installs = {trees.real(destination) for _, _, _, destination in plan}
    recorded = {trees.real(item.path) for item in state.installed}
    found: list[unknown.Unknown] = []
    seen: set[Path] = set()
    for entry in unknown.find_unknown(respec_home, state):
        key = trees.real(entry.path)
        if key in installs or key in recorded:
            found.append(entry)
            seen.add(key)
    managed = {
        trees.real(item.path)
        for item in state.installed
        if unknown.is_managed(respec_home, item)
    }
    registry = targets.registry()
    sharing: dict[Path, list[str]] = {}
    for target in _switch_targets(profile):
        sharing.setdefault(registry[target].skills_dir(user_home).resolve(), []).append(
            target
        )
    for _, skill, _, destination in plan:
        key = trees.real(destination)
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
        if trees.real(item.path).parent == real_folder
    ]
    if not items:
        return
    manifest = run_dir / BACKUP_MANIFEST
    data = json.loads(manifest.read_text("utf-8")) if manifest.exists() else {}
    data.setdefault("version", 1)
    data.setdefault("installed", {})[target] = items
    manifest.write_text(json.dumps(data, indent=2) + "\n", "utf-8")


def _missing_folders(folder: Path, user_home: Path) -> tuple[str, ...]:
    """``folder`` and its missing parents, deepest first, up to ``user_home``."""
    missing: list[str] = []
    current = folder
    while not os.path.lexists(current) and current != current.parent:
        if current == user_home:
            break
        missing.append(str(current))
        current = current.parent
    return tuple(missing)


def _take_over(
    respec_home: Path,
    user_home: Path,
    profile: profiles.Profile,
    state: State,
    now: Clock,
) -> dict[str, str]:
    """Back up and record every target folder respec has not owned before."""
    registry = targets.registry()
    new_targets = [t for t in _switch_targets(profile) if t not in state.owned]
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
            created=_missing_folders(folder, user_home),
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
    resolved = path.resolve()
    for root in global_skills.source_roots(respec_home):
        if resolved == root or root in resolved.parents:
            raise RespecError(
                f"refusing to delete {path}: it is inside respec's own folder {root}"
            )
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


class LinkFailed(RespecError):
    """Linking stopped part way; ``linked`` lists what was linked before."""

    def __init__(self, message: str, linked: list[str]) -> None:
        super().__init__(message)
        self.linked = list(linked)


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
        key = trees.real(destination)
        record = next((i for i in state.installed if trees.real(i.path) == key), None)
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
            reinstall = (
                " respec's own copy there was removed to be reinstalled; the "
                "next 'respec use' puts it back."
                if record is not None
                else ""
            )
            raise LinkFailed(
                f"linking {skill!r} into {destination.parent} did not complete: "
                f"{error}.{reinstall}",
                result.linked,
            ) from None
        state.installed.append(
            Installed(
                target=target,
                name=skill,
                path=str(destination),
                mode=mode,
                digest=trees.digest(destination) if mode == "copy" else None,
            )
        )
        save_state(respec_home, state)
        result.linked.append(str(destination))
    return result


def relink_lasting(respec_home: Path, user_home: Path) -> list[str]:
    """Link missing shipped and global skills of the active profile's switch
    into folders respec owns, where nothing is in the way (for example after
    an entry in their place was removed). Returns the paths linked."""
    state = load_state(respec_home)
    if state.active_profile is None:
        return []
    lasting = global_skills.lasting(respec_home)
    if not lasting:
        return []
    profile = profiles.load_profile(respec_home, state.active_profile)
    global_skills.refresh_shipped(respec_home)
    owned = {Path(entry.skills_dir).resolve() for entry in state.owned.values()}
    linked: list[str] = []
    for target, skill, source, destination in _plan_all(
        respec_home, user_home, profile
    ):
        if (
            skill not in lasting
            or destination.parent.resolve() not in owned
            or os.path.lexists(destination)
            or not source.is_dir()
        ):
            continue
        key = trees.real(destination)
        state.installed = [i for i in state.installed if trees.real(i.path) != key]
        try:
            mode = _install(source, destination)
        except OSError as error:
            save_state(respec_home, state)
            raise LinkFailed(
                f"linking {skill!r} into {destination.parent} did not complete: "
                f"{error}; the next 'respec use' puts it back.",
                linked,
            ) from None
        state.installed.append(
            Installed(
                target=target,
                name=skill,
                path=str(destination),
                mode=mode,
                digest=trees.digest(destination) if mode == "copy" else None,
            )
        )
        save_state(respec_home, state)
        linked.append(str(destination))
    return linked


def new_backups(respec_home: Path, owned_before: set[str]) -> dict[str, str]:
    """Takeover backups of folders owned now but not in ``owned_before``.

    A switch takes folders over before it resolves the entries in its way, so
    this also names the backups of a switch that failed or was interrupted.
    """
    return {
        target: entry.backup
        for target, entry in load_state(respec_home).owned.items()
        if target not in owned_before and entry.backup
    }


def _clashes(respec_home: Path, entries: list[unknown.Unknown]) -> dict[str, str]:
    """Why each entry named like a shipped or global skill can only be removed."""
    found = {}
    for entry in entries:
        reason = global_skills.clash(respec_home, entry.name)
        if reason is not None:
            found[entry.path] = reason
    return found


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
    _check_global(respec_home, profile, lead)
    found = conflicts(respec_home, user_home, profile, state)
    if found and on_unknown is None:
        raise UnknownEntries(
            profile.name,
            found,
            lead=lead,
            can_add=state.active_profile is not None,
            clashes=_clashes(respec_home, found),
        )
    result = SwitchResult(profile=profile.name, previous=state.active_profile)

    try:
        global_skills.refresh_shipped(respec_home)
    except RespecError as error:
        raise SwitchBlocked(f"{lead}: {error}") from None
    result.backups = _take_over(respec_home, user_home, profile, state, now)
    save_state(respec_home, state)

    if found and on_unknown is not None:
        on_unknown(found)
        profile = profiles.load_profile(respec_home, name)
        refuse_layer_conflicts(profile, action)
        state = load_state(respec_home)
        _check_sources(profile, lead)
        _check_global(respec_home, profile, lead)
        left = conflicts(respec_home, user_home, profile, state)
        if left:
            raise UnknownEntries(
                profile.name,
                left,
                lead=lead,
                can_add=state.active_profile is not None,
                clashes=_clashes(respec_home, left),
            )
    plan = _plan_all(respec_home, user_home, profile)
    kept = _kept(respec_home, state, plan)
    plan = [entry for entry in plan if trees.real(entry[3]) not in kept]

    # state.json is saved after every removal and every install, so it always
    # lists each path respec has created and a later switch can remove it.
    state.active_profile = None
    try:
        for item in list(state.installed):
            if trees.real(item.path) in kept:
                continue
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
                digest=trees.digest(destination) if mode == "copy" else None,
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


def _kept(
    respec_home: Path, state: State, plan: list[tuple[str, str, Path, Path]]
) -> set[Path]:
    """Destinations of global and shipped skills already linked as planned.

    These survive the switch untouched. Copies are always reinstalled, so
    they match the current files.
    """
    sources = {
        trees.real(destination): (skill, source)
        for _, skill, source, destination in plan
    }
    lasting = global_skills.lasting(respec_home)
    kept: set[Path] = set()
    for item in state.installed:
        key = trees.real(item.path)
        planned = sources.get(key)
        if (
            item.mode == "symlink"
            and item.name in lasting
            and planned is not None
            and planned[0] == item.name
            and unknown.is_managed(respec_home, item)
            and Path(item.path).resolve() == planned[1].resolve()
        ):
            kept.add(key)
    return kept


def status(respec_home: Path) -> dict[str, object]:
    """Active profile, its targets, the skills respec placed in each folder
    (each with its ``origin``: ``profile``, ``shipped`` or ``global``) and the
    unknown entries still waiting for a decision (``unresolved``)."""
    state = load_state(respec_home)
    active_targets: list[str] = []
    if state.active_profile is not None:
        try:
            profile = profiles.load_profile(respec_home, state.active_profile)
            active_targets = list(profile.targets)
        except RespecError:
            active_targets = sorted({item.target for item in state.installed})
    # Targets sharing one real folder list its items once, under the first.
    first_of = {
        target: group[0]
        for _, group in unknown.folder_groups(state)
        for target in group
    }
    order = list(targets.registry())
    folders = []
    for target in sorted(
        state.owned, key=lambda t: order.index(t) if t in order else len(order)
    ):
        first = first_of[target]
        folders.append(
            {
                "target": target,
                "skills_dir": state.owned[target].skills_dir,
                "same_as": None if target == first else first,
                "skills": [
                    {
                        "name": item.name,
                        "path": item.path,
                        "mode": item.mode,
                        "origin": global_skills.origin(
                            respec_home, Path(item.path), item.name
                        ),
                    }
                    for item in sorted(state.installed, key=lambda i: i.name)
                    if target == first
                    and first_of.get(item.target) == first
                    and unknown.is_managed(respec_home, item)
                ],
            }
        )
    return {
        "active_profile": state.active_profile,
        "targets": active_targets,
        "folders": folders,
        "unresolved": [
            entry.to_dict() for entry in unknown.find_unknown(respec_home, state)
        ],
    }
