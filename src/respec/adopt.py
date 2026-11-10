"""Resolve unknown entries in owned folders (see :mod:`respec.unknown`).

Everything unresolved comes from :func:`unresolved`: entries respec did not
place, and copies or links of its own skills that were edited or replaced
(``Unknown.replaced``). Each gets one of two choices:

- ``add``: copy it into the active profile as an enabled skill (through
  :func:`respec.items.add_local`, keeping the entry's own name), then remove
  the original; it is linked back right away. An edited or replaced copy of a
  skill the profile already has overwrites the profile's copy instead, so the
  edit is kept; the profile's previous copy goes to a backup run first.
  Without an active profile, ``add`` is not available (:func:`choices`).
- ``remove``: copy it to ``<respec home>/backups/<timestamp>/<target>/<name>``,
  then remove the original.

An original is only removed after its copy (in a profile or in a backup) is
complete, so nothing is lost. A symlink entry is removed by unlinking it; what
it points to is never touched.

:func:`adopt` asks about every entry before it changes anything, and refuses
up front to add into a profile with conflicting exclusive layers. If an add or
linking fails part way, the adds of that run are undone: each entry is put
back, and its profile copy is deleted only once the original is verifiably
restored (otherwise the copy stays in the profile and the error says where).
Removals already done stay done and are reported with their backups.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from respec import global_skills, items, profiles, switch, unknown
from respec.errors import RespecError
from respec.state import State, load_state, save_state

CHOICES = ("add", "remove")

Decide = Callable[[unknown.Unknown], str | None]


def choices(
    profile: str | None,
    entry: unknown.Unknown | None = None,
    respec_home: Path | None = None,
) -> tuple[str, ...]:
    """The choices available when ``add`` would go to ``profile``.

    Given ``entry`` and ``respec_home``, an entry named like a shipped or
    global skill can only be removed: respec links its own skill there again.
    """
    if profile is None:
        return ("remove",)
    if entry is not None and respec_home is not None:
        if entry.name in global_skills.lasting_or_shipped(respec_home):
            return ("remove",)
    return CHOICES


def _reserved_hint(name: str) -> str:
    return (
        f"Choose remove instead ('respec adopt --remove {name}'): the entry is "
        "backed up first, and respec links its own skill there again."
    )


@dataclass
class Resolution:
    entry: unknown.Unknown
    choice: str
    profile: str | None = None
    backup: str | None = None
    # Where an added symlink entry pointed, to put it back on rollback.
    link: str | None = field(default=None, repr=False)
    # Backup of the profile's own copy that an edited copy replaced.
    replaced_copy: str | None = None
    # Staging folders of earlier interrupted changes, kept and reported.
    leftovers: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """What was done, in the words the CLI and the TUI print."""
        path = self.entry.path
        if self.choice != "add":
            return f"Backed up {path} to {self.backup} and removed it"
        if self.replaced_copy is not None:
            text = (
                f"Replaced the copy of {self.entry.name!r} in profile "
                f"{self.profile!r} with {path} (the previous copy is backed up "
                f"at {self.replaced_copy})"
            )
            for leftover in self.leftovers:
                text += (
                    f"\n  left {leftover} in place: it is from an interrupted "
                    "change and may hold the only copy of earlier content"
                )
            return text
        return f"Added {path} to profile {self.profile!r}"

    def to_dict(self) -> dict[str, object]:
        return {
            **self.entry.to_dict(),
            "choice": self.choice,
            "profile": self.profile,
            "backup": self.backup,
            "replaced_copy": self.replaced_copy,
            "leftovers": list(self.leftovers),
        }


@dataclass
class AdoptResult:
    resolved: list[Resolution] = field(default_factory=list)
    unknown: list[unknown.Unknown] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)


def unresolved(respec_home: Path) -> list[unknown.Unknown]:
    """Everything in owned folders that waits for add or remove.

    Unknown entries, and edited or replaced copies of installed skills
    (flagged ``replaced``), folder by folder, sorted by name.
    """
    return unknown.find_unknown(respec_home, load_state(respec_home))


def _delete(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _settle(respec_home: Path, entry: unknown.Unknown) -> None:
    """Record the outcome: the path no longer holds anything of respec's."""
    state = load_state(respec_home)
    key = unknown.real(entry.path)
    state.installed = [i for i in state.installed if unknown.real(i.path) != key]
    save_state(respec_home, state)


def _copy_entry(source: Path, destination: Path) -> None:
    """Copy one entry as it is (links stay links); clean up on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
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
        raise RespecError(
            f"could not back up {source}; it was left in place: {error}"
        ) from None


STAGED = ".respec-new"
RETIRED = ".respec-old"


def _same_content(left: Path, right: Path) -> bool:
    try:
        return unknown.digest(left) == unknown.digest(right)
    except OSError:
        return False


def _backed_up(respec_home: Path, profile: str, name: str, folder: Path) -> bool:
    """Whether a backup run holds a profile copy of ``name`` like ``folder``."""
    pattern = f"*/profiles/{profile}/{name}"
    return any(
        _same_content(saved, folder)
        for saved in switch.backups_dir(respec_home).glob(pattern)
    )


def _clean_leftovers(respec_home: Path, profile: profiles.Profile) -> list[str]:
    """Settle staging folders that an interrupted overwrite may have left.

    A leftover is deleted only when its content is verifiably held elsewhere:
    by the live folder of that skill, or (for a previous copy) by a backup run.
    A previous copy whose live folder is gone is moved back into place. Any
    other leftover is kept, and its path is returned so it can be reported.
    """
    skills_dir = profile.path / profiles.SKILLS_DIR
    kept: list[str] = []
    # Previous copies first, so a missing live folder is restored before the
    # staged copy of the same skill is judged against it.
    for suffix in (RETIRED, STAGED):
        for leftover in sorted(skills_dir.glob(f".*{suffix}")):
            if leftover.is_symlink() or not leftover.is_dir():
                continue
            name = leftover.name[1 : -len(suffix)]
            live = skills_dir / name
            try:
                if not os.path.lexists(live) and suffix == RETIRED:
                    os.replace(leftover, live)
                    continue
                if (os.path.lexists(live) and _same_content(live, leftover)) or (
                    suffix == RETIRED
                    and _backed_up(respec_home, profile.name, name, leftover)
                ):
                    shutil.rmtree(leftover)
                    continue
            except OSError:
                pass
            kept.append(str(leftover))
    return kept


def _overwrite(
    respec_home: Path,
    profile: profiles.Profile,
    entry: unknown.Unknown,
    run_dir: Callable[[], Path],
) -> tuple[str, list[str]]:
    """Replace the profile's copy of ``entry.name`` with the entry's content.

    The profile's previous copy is backed up first. Returns where, and the
    leftover staging folders kept because they may hold the only copy of
    something.
    """
    source = Path(entry.path).resolve()
    if not source.is_dir():
        raise RespecError(f"{source} is not a folder; give the path of a skill folder")
    if not (source / items.SKILL_FILE).is_file():
        raise RespecError(
            f"{source} has no {items.SKILL_FILE}; a skill folder needs one"
        )
    destination = profile.path / profiles.SKILLS_DIR / entry.name
    staged = destination.with_name(f".{entry.name}{STAGED}")
    retired = destination.with_name(f".{entry.name}{RETIRED}")
    _clean_leftovers(respec_home, profile)
    for leftover in (staged, retired):
        if os.path.lexists(leftover):
            raise RespecError(
                f"cannot add {source}: {leftover} is left from an interrupted "
                "change and may hold the only copy of earlier content; move it "
                "out of the way first. Nothing was changed."
            )
    saved = run_dir() / "profiles" / profile.name / entry.name
    _copy_entry(destination, saved)
    try:
        shutil.copytree(source, staged)
        if os.path.lexists(destination):
            os.replace(destination, retired)
        os.replace(staged, destination)
    except (OSError, shutil.Error) as error:
        if not os.path.lexists(destination) and os.path.lexists(retired):
            os.replace(retired, destination)
        shutil.rmtree(staged, ignore_errors=True)
        raise RespecError(
            f"could not add {source} to profile {profile.name!r}; "
            f"both were left as they were: {error}"
        ) from None
    # The previous copy now sits in ``retired`` and in the backup run.
    return str(saved), _clean_leftovers(respec_home, profile)


def _add(
    respec_home: Path,
    resolution: Resolution,
    profile_name: str | None,
    run_dir: Callable[[], Path],
) -> str:
    entry = resolution.entry
    if profile_name is None:
        raise RespecError(
            f"cannot add {entry.path}: no active profile to add it to; "
            "remove it instead (it is backed up first), or activate a profile "
            "with 'respec use <profile>'"
        )
    global_skills.refuse_reserved(
        respec_home, [entry.name], profile_name, _reserved_hint(entry.name)
    )
    profile = profiles.load_profile(respec_home, profile_name)
    if entry.replaced and entry.name in profile.skills:
        resolution.replaced_copy, resolution.leftovers = _overwrite(
            respec_home, profile, entry, run_dir
        )
    elif entry.name in profile.skills:
        raise RespecError(
            f"cannot add {entry.path}: profile {profile_name!r} already has a "
            f"skill {entry.name!r}; choose remove instead ('respec adopt "
            f"--remove {entry.name}'): the entry is backed up first, and the "
            "profile's own copy is kept"
        )
    else:
        items.add_local(respec_home, profile_name, Path(entry.path), name=entry.name)
    if Path(entry.path).is_symlink():
        resolution.link = os.readlink(entry.path)
    _delete(Path(entry.path))
    _settle(respec_home, entry)
    return profile_name


def _put_back(resolution: Resolution, copy: Path) -> bool:
    """Restore an added entry at its original path from the profile copy.

    Returns True only when the original is verifiably back: the moved folder
    itself, a folder with the same content, or the same symlink. Whatever
    respec placed there (its link to the copy, or its copy of it) is replaced.
    Anything else at the original path is left alone and False is returned,
    so the caller keeps the copy.
    """
    original = Path(resolution.entry.path)
    link = resolution.link
    if not copy.is_dir() or copy.is_symlink():
        return False
    if os.path.lexists(original):
        if original.is_symlink():
            if original.resolve() != copy.resolve():
                return False
            original.unlink()  # respec's link to the copy
        elif original.is_dir() and unknown.digest(original) == unknown.digest(copy):
            if link is None:
                return True  # respec's copy holds exactly the original content
            shutil.rmtree(original)  # respec's copy; the content is in ``copy``
        else:
            return False
    if link is not None:
        os.symlink(link, original)
        return original.is_symlink() and os.readlink(original) == link
    shutil.move(str(copy), str(original))
    return original.is_dir() and not original.is_symlink() and not copy.exists()


def _undo_adds(
    respec_home: Path,
    before: profiles.Profile,
    state_before: State,
    adds: list[Resolution],
) -> list[str]:
    """Put added entries back where they were, never losing their content.

    A profile copy is deleted only after :func:`_put_back` verified the
    original is restored; otherwise the copy stays in the profile (listed and
    enabled) and a note says where. Returns those notes.
    """
    notes: list[str] = []
    restored: set[Path] = set()
    kept: list[str] = []
    for resolution in adds:
        name = resolution.entry.name
        copy = before.path / profiles.SKILLS_DIR / name
        try:
            back = _put_back(resolution, copy)
        except (OSError, shutil.Error):
            back = False
        if back:
            restored.add(unknown.real(resolution.entry.path))
            if copy.exists() or copy.is_symlink():
                shutil.rmtree(copy, ignore_errors=True)
            if resolution.replaced_copy is not None:
                # The profile gets its own previous copy back from the backup.
                shutil.copytree(resolution.replaced_copy, copy, symlinks=True)
        else:
            kept.append(name)
            notes.append(
                f"could not put {resolution.entry.path} back; its content is kept "
                f"in profile {before.name!r} at {copy}"
                + (
                    f" (its previous copy is backed up at {resolution.replaced_copy})"
                    if resolution.replaced_copy
                    else ""
                )
            )
    if kept:
        skills = dict(before.skills)
        for name in kept:
            skills[name] = profiles.SkillEntry(enabled=True)
        profiles.save_profile(dataclasses.replace(before, skills=skills))
    else:
        profiles.restore_profile(before)
    state = load_state(respec_home)
    state.installed = [
        item for item in state.installed if unknown.real(item.path) not in restored
    ]
    for item in state_before.installed:
        if unknown.real(item.path) in restored:
            state.installed.append(item)
    save_state(respec_home, state)
    return notes


def _remove(respec_home: Path, entry: unknown.Unknown, run_dir: Path) -> str:
    source = Path(entry.path)
    destination = run_dir / entry.targets[0] / entry.name
    _copy_entry(source, destination)
    _delete(source)
    _settle(respec_home, entry)
    return str(destination)


def resolve(
    respec_home: Path,
    entries: list[unknown.Unknown],
    decide: Decide,
    profile: str | None,
    now: switch.Clock = switch.utc_now,
    done: list[Resolution] | None = None,
) -> list[Resolution]:
    """Ask ``decide`` about each entry and apply its choice at once.

    ``decide`` returns one of :data:`CHOICES`, or ``None`` to leave the entry
    as it is for now. ``add`` goes to ``profile``; with ``None`` it fails, as
    only ``remove`` is available then. Each applied choice is appended to
    ``done`` (when given) as it happens, so a caller still knows what was done
    when a later entry fails.
    """
    resolutions: list[Resolution] = []
    run_dir: Path | None = None

    def new_run() -> Path:
        nonlocal run_dir
        if run_dir is None:
            run_dir = switch.new_backup_run(respec_home, now())
        return run_dir

    # Entries named like a shipped or global skill are asked about first, so
    # an ``add`` of one is refused before any entry changes.
    taken = global_skills.lasting_or_shipped(respec_home)
    early: dict[str, str | None] = {}
    for entry in entries:
        if entry.name in taken:
            early[entry.path] = decide(entry)
            if early[entry.path] == "add" and profile is not None:
                global_skills.refuse_reserved(
                    respec_home, [entry.name], profile, _reserved_hint(entry.name)
                )

    for entry in entries:
        choice = early[entry.path] if entry.path in early else decide(entry)
        if choice is None:
            continue
        if choice not in CHOICES:
            raise RespecError(
                f"unknown choice {choice!r} for {entry.path}; "
                f"use one of: {', '.join(CHOICES)}"
            )
        resolution = Resolution(entry=entry, choice=choice)
        if choice == "add":
            resolution.profile = _add(respec_home, resolution, profile, new_run)
        else:
            resolution.backup = _remove(respec_home, entry, new_run())
        resolutions.append(resolution)
        if done is not None:
            done.append(resolution)
    return resolutions


def link_added(
    respec_home: Path,
    user_home: Path,
    resolutions: list[Resolution],
) -> switch.LinkResult:
    """Link skills just added to the active profile into its owned folders.

    Unrelated unknown entries never block this; a destination that is itself
    in the way is reported in ``blocked`` and stays for ``respec adopt``.
    """
    active = load_state(respec_home).active_profile
    added = [
        r.entry.name for r in resolutions if r.choice == "add" and r.profile == active
    ]
    if active is None:
        return switch.LinkResult()
    result = (
        switch.link_skills(respec_home, user_home, active, added)
        if added
        else switch.LinkResult()
    )
    if resolutions:
        # A removed entry may have sat where a shipped or global skill goes.
        try:
            result.linked += switch.relink_lasting(respec_home, user_home)
        except switch.LinkFailed as error:
            raise switch.LinkFailed(str(error), result.linked + error.linked) from None
    return result


def taken_over(respec_home: Path, targets: Iterable[str]) -> list[unknown.Unknown]:
    """Unknown entries in the folders of ``targets`` (those a switch took over
    first, see :func:`respec.switch.new_backups`)."""
    wanted = set(targets)
    if not wanted:
        return []
    return [entry for entry in unresolved(respec_home) if set(entry.targets) & wanted]


def takeover_profile(result: switch.SwitchResult) -> str:
    """Where ``add`` goes for entries found at a takeover: the profile being
    left, or at the very first takeover the profile being activated."""
    return result.previous if result.previous is not None else result.profile


def adopt(
    respec_home: Path,
    user_home: Path,
    decide: Decide,
    now: switch.Clock = switch.utc_now,
    done: list[Resolution] | None = None,
) -> AdoptResult:
    """Resolve unknown entries outside a switch; ``add`` goes to the active profile.

    Entries added are linked right away where nothing is in the way. Each
    applied choice is appended to ``done`` as it happens.
    """
    result = AdoptResult()
    if done is None:
        done = []
    entries = unresolved(respec_home)
    active = load_state(respec_home).active_profile
    # Ask everything first, so a refusal below happens before any change.
    chosen = {entry.path: decide(entry) for entry in entries}
    before: profiles.Profile | None = None
    if "add" in chosen.values():
        if active is None:
            raise RespecError(
                "cannot add: there is no active profile to add to; remove the "
                "entries instead (they are backed up first), or activate a "
                "profile with 'respec use <profile>'"
            )
        before = profiles.load_profile(respec_home, active)
        switch.refuse_layer_conflicts(before, "adopt into")
    state_before = load_state(respec_home)
    start = len(done)
    try:
        result.resolved = resolve(
            respec_home, entries, lambda e: chosen[e.path], active, now, done=done
        )
        result.linked = link_added(respec_home, user_home, result.resolved).linked
    except RespecError as error:
        adds = [r for r in done[start:] if r.choice == "add"]
        if not adds:
            raise
        assert before is not None
        notes = _undo_adds(respec_home, before, state_before, adds)
        for resolution in adds:
            done.remove(resolution)
        message = f"{error}\nThe skills added in this run were taken back out."
        if notes:
            message += "\n" + "\n".join(f"  - {note}" for note in notes)
        raise RespecError(message) from None
    result.unknown = unresolved(respec_home)
    return result
