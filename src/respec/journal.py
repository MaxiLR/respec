"""Interruption safety: a journal in ``state.json`` for changes of several steps.

Every change that touches skill folders, takeover backups or profile folders
in more than one step records itself under ``journal`` in ``state.json``
before it changes anything (:func:`begin`), and keeps the one step in flight
there while it runs (:func:`mark`). The journal is dropped when the change
ends. A crash (or a kill) leaves it behind; the next respec command finds it
and either finishes the change or rolls it back (:func:`recover`), and says
which. Nothing is deleted on the way: an entry a step left half made is moved
to a fresh backup run (it is "set aside") unless it is verifiably what that
step was making, in which case it is recorded.

Journal fields (``pending`` and the optional fields are left out when unset)::

    {"operation": "use",              # see OPERATIONS
     "started_at": "2026-11-10T12:00:00+00:00",
     "profile": "work",               # the profile the change is about
     "previous": "home",              # use: the profile active before
     "action": "refresh",             # use: re-applying the active profile
     "backup": "20261110T120000Z",    # restore: the backup named, if any
     "skills": ["tdd"],               # update, add: the skills it changes
     "phase": "apply",                # see below
     "pending": {"step": "install", ...}}

``phase`` is ``prepare`` until a switch or restore starts removing skills and
``apply`` after; an update or an add from git is in ``copy`` until
``profile.yaml`` is saved and in ``refresh`` after.

How each operation is recovered, after the step in flight is settled:

- ``use``: before ``apply`` nothing of the active profile changed, so it is
  rolled back (the previous profile stays active). Otherwise it is finished;
  if the profile cannot be activated, the previous one is activated again,
  and if that fails too, respec's skills are removed and no profile is
  active. ``--rollback`` activates the previous profile instead.
- ``restore``: finished (entries in the way are backed up first). It can only
  be rolled back before it removed any skill.
- ``adopt`` and ``links``: the choices and links already made stay; the
  links of the active profile are put in line with its ``profile.yaml``.
  Staging folders of an interrupted overwrite are settled by
  :func:`respec.adopt._clean_leftovers`, which keeps any that may hold the
  only copy of something.
- ``update`` and ``add``: rolled back in ``copy`` (the previous skill folders
  come back, fetched ones go), finished in ``refresh``.
- ``install``: kept when its ``profile.yaml`` was written (the last step),
  otherwise the half-copied profile folder is removed (fetched content only).

Tests inject failures at every step boundary through :func:`checkpoint`.
"""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from respec import trees
from respec.errors import RespecError
from respec.state import Installed, State, load_state, save_state, state_path

OPERATIONS = ("use", "restore", "adopt", "links", "update", "add", "install")
WARNING = "interrupted-operation"
FINISHED = "finished"
ROLLED_BACK = "rolled-back"
PENDING = "pending"
# Phases after which a failure leaves the change for recovery to finish.
LATE_PHASES = frozenset({"apply", "refresh"})


class Pending(RespecError):
    """An interrupted change waits to be finished or rolled back."""


def _fault(name: str) -> None:
    """Failure-injection seam: tests replace it to stop at a step boundary."""


def checkpoint(name: str) -> None:
    """A step boundary: everything before it is on disk."""
    _fault(name)


# --- in-process bookkeeping ----------------------------------------------------

_local = threading.local()


def _ops() -> list[str]:
    """The changes running in this thread, outermost first."""
    if not hasattr(_local, "ops"):
        _local.ops = []
    return _local.ops


def _depth() -> int:
    return len(_ops())


def _recovering() -> bool:
    return getattr(_local, "recovering", False)


@dataclass
class _Policy:
    """What an interrupted change found by :func:`ready` leads to."""

    auto: bool = False  # recover it (the CLI) or refuse (the TUI, the API)
    user_home: Path | None = None
    reports: list[Recovery] = field(default_factory=list)


_policy = _Policy()


def auto_recover(user_home: Path) -> None:
    """Let :func:`ready` recover an interrupted change instead of refusing."""
    global _policy
    _policy = _Policy(auto=True, user_home=user_home)


def refuse_pending() -> None:
    """Back to the default: :func:`ready` refuses while a change is pending."""
    global _policy
    _policy = _Policy()


def peek_reports() -> list[Recovery]:
    """Recoveries made since the policy was set, oldest first (kept)."""
    return list(_policy.reports)


def take_reports() -> list[Recovery]:
    """Recoveries made since the policy was set, oldest first."""
    reports = list(_policy.reports)
    _policy.reports.clear()
    return reports


# --- describing ----------------------------------------------------------------


def describe(journal: dict[str, Any]) -> str:
    """The interrupted change in a few words: "the switch to profile 'work'"."""
    operation = journal.get("operation")
    profile = journal.get("profile")
    if operation == "use":
        if profile is None:
            return "the removal of respec's skills"
        if journal.get("action") == "refresh":
            return f"the re-apply of profile {profile!r}"
        return f"the switch to profile {profile!r}"
    return {
        "restore": "the restore",
        "adopt": "the resolution of unknown entries",
        "links": f"the link changes of profile {profile!r}",
        "update": f"the update of profile {profile!r}",
        "add": f"the add from git to profile {profile!r}",
        "install": f"the install of profile {profile!r}",
    }.get(str(operation), f"an operation {operation!r}")


def pending_message(journal: dict[str, Any]) -> str:
    started = journal.get("started_at", "an earlier run")
    what = describe(journal)
    return (
        f"{what[0].upper()}{what[1:]} (started "
        f"{started}) was interrupted and did not complete. Run 'respec recover' "
        "to finish it, or 'respec recover --rollback' to roll it back (Sync in "
        "the TUI offers both); any respec command that changes skills finishes "
        "it first."
    )


@dataclass
class Recovery:
    """What :func:`recover` did, or (``outcome`` pending) what waits for it."""

    operation: str
    outcome: str  # FINISHED, ROLLED_BACK or PENDING
    message: str
    profile: str | None = None
    set_aside: list[str] = field(default_factory=list)

    def to_warning(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": WARNING,
            "operation": self.operation,
            "outcome": self.outcome,
            "message": self.message,
            "set_aside": list(self.set_aside),
        }
        if self.profile is not None:
            data["profile"] = self.profile
        return data


def pending(respec_home: Path) -> Recovery | None:
    """The interrupted change waiting in ``state.json``, if any (reads only)."""
    journal = load_state(respec_home).journal
    if journal is None:
        return None
    return Recovery(
        operation=str(journal.get("operation")),
        outcome=PENDING,
        message=pending_message(journal),
        profile=journal.get("profile"),
    )


# --- writing -------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ready(respec_home: Path, user_home: Path | None = None) -> None:
    """Call before a change: deal with an interrupted one first.

    Inside a change (or a recovery) this does nothing. Otherwise a pending
    journal is recovered when :func:`auto_recover` is set, and refused with
    :class:`Pending` when it is not.
    """
    if _depth() or _recovering():
        return
    journal = load_state(respec_home).journal
    if journal is None:
        return
    if _policy.auto:
        from respec import paths

        recover(respec_home, user_home or _policy.user_home or paths.user_home())
        return
    raise Pending(pending_message(journal))


@contextmanager
def begin(
    respec_home: Path,
    operation: str,
    state: State | None = None,
    **fields: Any,
) -> Iterator[None]:
    """Journal ``operation`` while the ``with`` block runs.

    Nested inside another change it records nothing of its own; that change's
    recovery covers it. ``state``, when given, is the caller's in-memory state:
    the journal is set on it and it is saved. The journal is dropped when the
    block ends, and also when it fails with an error before any step is in
    flight and before a late phase; otherwise (and after any crash that is
    not an ``Exception``, such as a kill or Ctrl-C) it stays for recovery.
    """
    if _depth():
        yield from _nested(respec_home, operation, state, fields)
        return
    current = state if state is not None else load_state(respec_home)
    if current.journal is not None and not _recovering():
        raise Pending(pending_message(current.journal))
    # A change that fails before doing anything leaves no state file behind
    # when there was none.
    existed = state_path(respec_home).exists()
    current.journal = {
        "operation": operation,
        "started_at": _now(),
        **{key: value for key, value in fields.items() if value is not None},
    }
    save_state(respec_home, current)
    _ops().append(operation)
    try:
        checkpoint(f"{operation}:begin")
        yield
    except Exception as error:
        _end_after_failure(respec_home, error, existed)
        raise
    else:
        _clear(respec_home, existed)
    finally:
        _ops().clear()


def _nested(
    respec_home: Path, operation: str, state: State | None, fields: dict[str, Any]
) -> Iterator[None]:
    """A change inside another: the outer one's recovery covers it. A switch
    (a refresh of the active profile) notes which profile it activates under
    ``switch``, so recovery can finish it before the outer change."""
    _ops().append(operation)
    switching = operation == "use"
    if switching:
        target = _journal_of(respec_home, state)
        if target is not None and target.journal is not None:
            target.journal["switch"] = {
                key: fields[key]
                for key in ("profile", "previous", "phase")
                if fields.get(key) is not None
            }
            save_state(respec_home, target)
    try:
        yield
    finally:
        _ops().pop()
    if switching:  # only reached when the switch went through
        done = load_state(respec_home)
        if done.journal is not None and done.journal.pop("switch", None):
            save_state(respec_home, done)


def _end_after_failure(respec_home: Path, error: Exception, existed: bool) -> None:
    from respec.switch import SwitchBlocked

    state = load_state(respec_home)
    journal = state.journal
    if journal is None:
        return
    late = journal.get("phase") in LATE_PHASES or journal.get("pending") is not None
    if isinstance(error, SwitchBlocked) or not late:
        _clear(respec_home, existed)


def _clear(respec_home: Path, existed: bool = True) -> None:
    """Drop the journal; a state file the change created only for it goes too."""
    state = load_state(respec_home)
    if state.journal is None:
        return
    state.journal = None
    if not existed and state.to_dict() == State().to_dict():
        state_path(respec_home).unlink()
    else:
        save_state(respec_home, state)


def _journal_of(respec_home: Path, state: State | None) -> State | None:
    """The state to record on: ``state`` (with the journal from disk when it
    was loaded before the change began), or the state on disk."""
    if state is None:
        state = load_state(respec_home)
    elif state.journal is None:
        state.journal = load_state(respec_home).journal
    return state if state.journal is not None else None


def mark(
    respec_home: Path,
    step: dict[str, Any] | None,
    state: State | None = None,
) -> None:
    """Record the step about to run (``None``: the step is done) and save.

    With ``state``, the caller's in-memory state is updated and saved, so
    whatever else it changed (a record added or dropped) lands in the same
    write. Outside a change nothing is recorded.
    """
    if not _depth() and not _recovering():
        if state is not None:
            save_state(respec_home, state)
        return
    target = _journal_of(respec_home, state)
    if target is None:
        if state is not None:
            save_state(respec_home, state)
        return
    assert target.journal is not None
    if step is None:
        target.journal.pop("pending", None)
    else:
        target.journal["pending"] = step
    save_state(respec_home, target)
    checkpoint(f"{step['step']}:start" if step else "step:done")


def set_phase(
    respec_home: Path, phase: str, state: State | None = None, **fields: Any
) -> None:
    """Move the change to ``phase``. Only the outermost change has phases, and
    a switch inside another change (its ``switch`` record)."""
    record: dict[str, Any] | None = None
    target = _journal_of(respec_home, state) if _depth() else None
    if target is not None and target.journal is not None:
        if _depth() == 1:
            record = target.journal
        elif _ops()[-1] == "use" and isinstance(target.journal.get("switch"), dict):
            record = target.journal["switch"]
    if record is None:
        if state is not None:
            save_state(respec_home, state)
        return
    assert target is not None
    record["phase"] = phase
    record.update({k: v for k, v in fields.items() if v is not None})
    save_state(respec_home, target)
    checkpoint(f"phase:{phase}")


# --- recovering ----------------------------------------------------------------


class _Aside:
    """Moves half-made entries into one fresh backup run, made when needed."""

    def __init__(self, respec_home: Path) -> None:
        self.respec_home = respec_home
        self.run: Path | None = None
        self.moved: list[str] = []

    def __call__(self, path: Path, group: str) -> None:
        from respec import switch

        if self.run is None:
            self.run = switch.new_backup_run(self.respec_home, switch.utc_now())
        destination = self.run / group / path.name
        suffix = 2
        while os.path.lexists(destination):
            destination = self.run / group / f"{path.name}-{suffix}"
            suffix += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        self.moved.append(str(destination))


def _drop_records(state: State, path: str | Path) -> None:
    key = trees.real(path)
    state.installed = [i for i in state.installed if trees.real(i.path) != key]


def _delete(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _settle_pending(
    respec_home: Path, journal: dict[str, Any], aside: _Aside
) -> list[str]:
    """Finish or undo the one step in flight; returns notes for the report."""
    from respec import unknown

    step = journal.get("pending")
    if not step:
        return []
    notes: list[str] = []
    state = load_state(respec_home)
    kind = step.get("step")
    path = Path(step["path"]) if "path" in step else None
    if kind == "backup" and path is not None:
        # A takeover backup run being written: the folders it copies were not
        # changed yet, so a run no ownership refers to is only a partial copy.
        used = any(
            entry.backup is not None and Path(entry.backup).parent == path
            for entry in state.owned.values()
        )
        if not used and path.is_dir():
            shutil.rmtree(path)
    elif kind == "remove" and path is not None:
        item = Installed(**step["item"])
        if not os.path.lexists(path):
            _drop_records(state, path)
        elif not unknown.is_managed(respec_home, item):
            aside(path, item.target)  # a copy removed only in part
            _drop_records(state, path)
    elif kind == "install" and path is not None:
        source = Path(step["source"])
        key = trees.real(path)
        recorded = any(trees.real(i.path) == key for i in state.installed)
        if not recorded and os.path.lexists(path):
            record: Installed | None = None
            if path.is_symlink():
                if path.resolve() == source.resolve():
                    record = Installed(
                        step["target"], step["name"], str(path), "symlink"
                    )
            elif path.is_dir() and trees.same_content(path, source):
                record = Installed(
                    step["target"], step["name"], str(path), "copy", trees.digest(path)
                )
            if record is not None:
                state.installed.append(record)
            else:
                aside(path, step["target"])  # a copy made only in part
    elif kind == "put-back" and path is not None:
        if os.path.lexists(path) and not trees.same_entry(path, Path(step["source"])):
            aside(path, step["target"])  # a backup entry copied only in part
    elif kind == "adopt" and path is not None:
        notes += _settle_adopt(respec_home, state, step, path)
    if state.journal is not None:
        state.journal.pop("pending", None)
    save_state(respec_home, state)
    return notes


def _settle_adopt(
    respec_home: Path,
    state: State,
    step: dict[str, Any],
    original: Path,
) -> list[str]:
    """An add or remove of an unknown entry: its original is only deleted once
    its copy (in a backup or the profile) is complete, so finish that delete,
    or drop a copy that was cut short (the original is still whole)."""
    from respec import adopt, profiles

    notes: list[str] = []
    stage = step.get("stage")
    if step.get("choice") == "remove":
        backup = Path(step["backup"])
        if stage == "copy":
            if os.path.lexists(backup):
                _delete(backup)
            return notes
    else:
        profile = profiles.load_profile(respec_home, step["profile"])
        live = profile.path / profiles.SKILLS_DIR / step["name"]
        if stage == "copy":
            if step.get("overwrite"):
                for kept in adopt._clean_leftovers(respec_home, profile):
                    notes.append(
                        f"left {kept} in place: it is from an interrupted change "
                        "and may hold the only copy of earlier content"
                    )
                if not (
                    os.path.lexists(original) and trees.same_content(live, original)
                ):
                    return notes  # the profile keeps its previous copy
            elif step["name"] not in profile.skills:
                if os.path.lexists(live):
                    _delete(live)  # a copy cut short; the original is whole
                return notes
    if os.path.lexists(original):
        _delete(original)
    _drop_records(state, original)
    return notes


def recover(
    respec_home: Path, user_home: Path, rollback: bool = False
) -> Recovery | None:
    """Finish or roll back the interrupted change in ``state.json``, if any.

    ``rollback`` asks to undo it where that is possible (see the module
    docstring). Returns what was done, also kept for :func:`take_reports`.
    """
    state = load_state(respec_home)
    journal = state.journal
    if journal is None:
        return None
    what = describe(journal)
    aside = _Aside(respec_home)
    _local.recovering = True
    try:
        notes = _settle_pending(respec_home, journal, aside)
        journal = load_state(respec_home).journal or journal
        inner = journal.get("switch")
        if isinstance(inner, dict) and inner.get("profile"):
            # A refresh inside this change was cut short: activate its profile
            # again first, so the change below finds it active.
            _recover_use(respec_home, user_home, {"operation": "use", **inner}, False)
        handler = _HANDLERS.get(str(journal.get("operation")))
        if handler is None:
            raise RespecError(f"unknown operation {journal.get('operation')!r}")
        outcome, message = handler(respec_home, user_home, journal, rollback)
        _clear(respec_home)
    except RespecError as error:
        raise RespecError(
            f"could not recover {what}: {error}\nIt stays recorded in "
            "state.json; fix the problem and run 'respec recover' again."
        ) from None
    finally:
        _local.recovering = False
    if aside.moved:
        notes.append(
            "set aside what an interrupted step left half made: "
            + ", ".join(aside.moved)
        )
    if notes:
        message += "\n" + "\n".join(f"  {note}" for note in notes)
    report = Recovery(
        operation=str(journal.get("operation")),
        outcome=outcome,
        message=message,
        profile=journal.get("profile"),
        set_aside=aside.moved,
    )
    _policy.reports.append(report)
    return report


Handler = Callable[[Path, Path, dict[str, Any], bool], tuple[str, str]]


def _activate(respec_home: Path, user_home: Path, name: str | None) -> None:
    """Make ``name`` the active profile, or (``None``) remove respec's skills."""
    from respec import switch

    if name is not None:
        switch.use(respec_home, user_home, name)
        return
    state = load_state(respec_home)
    with begin(respec_home, "use", state=state, phase="apply"):
        state.active_profile = None
        for item in list(state.installed):
            mark(
                respec_home,
                {"step": "remove", "path": item.path, "item": item.to_dict()},
                state,
            )
            switch.remove_installed(respec_home, item)
            checkpoint("removed")
            state.installed.remove(item)
            mark(respec_home, None, state)


def _recover_use(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    profile = journal.get("profile")
    previous = journal.get("previous")
    what = describe(journal)
    if journal.get("phase") != "apply":
        stays = f"profile {previous!r}" if previous else "no profile"
        return ROLLED_BACK, (
            f"Rolled back {what}: it had not changed any skill yet, so {stays} "
            "stays active."
        )
    order = [previous, profile] if rollback else [profile, previous]
    tried: list[str] = []
    for name in dict.fromkeys(order):
        try:
            _activate(respec_home, user_home, name)
        except RespecError as error:
            first = str(error).splitlines()[0]
            tried.append(f"profile {name!r} could not be activated: {first}")
            continue
        if name == profile:
            return FINISHED, f"Finished {what}." + _because(tried)
        return ROLLED_BACK, (
            f"Rolled back {what}: "
            + (
                f"profile {name!r} is active again."
                if name
                else "no profile is active."
            )
            + _because(tried)
        )
    _activate(respec_home, user_home, None)
    return ROLLED_BACK, (
        f"Rolled back {what}: no profile is active and respec's skills were "
        "removed." + _because(tried)
    )


def _because(tried: list[str]) -> str:
    return "".join(f"\n  {line}" for line in tried)


def _recover_restore(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    from respec import restore

    if rollback:
        if journal.get("phase") == "apply":
            raise RespecError(
                "a restore cannot be rolled back once it has removed skills; "
                "run 'respec recover' to finish it"
            )
        return ROLLED_BACK, (
            "Rolled back the restore: it had not removed any skill yet. Entries "
            "it set aside stay in their backup run."
        )
    restore.restore(respec_home, user_home, journal.get("backup"), overwrite=True)
    return FINISHED, (
        "Finished the restore: respec released its folders (entries in the "
        "way were backed up first)."
    )


def _recover_links(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    from respec import adopt, profiles, switch

    notes: list[str] = []
    name = journal.get("profile")
    if name is not None and name in profiles.list_profile_names(respec_home):
        try:
            profile = profiles.load_profile(respec_home, name)
        except RespecError:
            profile = None
        if profile is not None:
            notes = [
                f"\n  left {kept} in place: it is from an interrupted change and "
                "may hold the only copy of earlier content"
                for kept in adopt._clean_leftovers(respec_home, profile)
            ]
    switch.align_links(respec_home, user_home)
    return FINISHED, (
        f"Finished {describe(journal)}: the choices made stay, and the links "
        "of the active profile match its profile.yaml." + "".join(notes)
    )


def _reapply(respec_home: Path, user_home: Path, name: str) -> None:
    from respec import switch

    if load_state(respec_home).active_profile != name:
        return
    try:
        switch.use(respec_home, user_home, name, action="refresh")
    except switch.SwitchBlocked:
        switch.align_links(respec_home, user_home)


def _recover_update(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    from respec import profiles

    name = journal["profile"]
    profile = profiles.load_profile(respec_home, name)
    skills_dir = profile.path / profiles.SKILLS_DIR
    if journal.get("phase") != "refresh":
        for skill in journal.get("skills", []):
            live = skills_dir / skill
            old = skills_dir / f".{skill}.old"
            incoming = skills_dir / f".{skill}.incoming"
            if old.is_dir() and not old.is_symlink():
                if os.path.lexists(live):
                    _delete(live)  # fetched upstream files; fetched again later
                os.replace(old, live)
            if os.path.lexists(incoming):
                _delete(incoming)
        _reapply(respec_home, user_home, name)
        return ROLLED_BACK, (
            f"Rolled back {describe(journal)}: its skills are as they were "
            "before; run 'respec update' again."
        )
    for skill in journal.get("skills", []):
        for leftover in (f".{skill}.old", f".{skill}.incoming"):
            if os.path.lexists(skills_dir / leftover):
                _delete(skills_dir / leftover)
    _reapply(respec_home, user_home, name)
    return FINISHED, f"Finished {describe(journal)}."


def _recover_add(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    import dataclasses

    from respec import profiles

    name = journal["profile"]
    if journal.get("phase") == "refresh":
        _reapply(respec_home, user_home, name)
        return FINISHED, f"Finished {describe(journal)}."
    profile = profiles.load_profile(respec_home, name)
    added = set(journal.get("skills", []))
    skills = {k: v for k, v in profile.skills.items() if k not in added}
    if skills != profile.skills:
        profiles.save_profile(dataclasses.replace(profile, skills=skills))
    for skill in added:
        folder = profile.path / profiles.SKILLS_DIR / skill
        if os.path.lexists(folder):
            _delete(folder)  # fetched from git; nothing of the user's
    return ROLLED_BACK, (
        f"Rolled back {describe(journal)}: none of its skills were added; run "
        "'respec add' again."
    )


def _recover_install(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    from respec import profiles

    name = journal["profile"]
    folder = Path(journal["path"])
    try:
        profiles.load_profile(respec_home, name)
    except RespecError:
        if os.path.lexists(folder):
            _delete(folder)  # fetched from git; nothing of the user's
        return ROLLED_BACK, (
            f"Rolled back {describe(journal)}: the half-copied profile was "
            "removed; run 'respec profile install' again."
        )
    return FINISHED, f"Finished {describe(journal)}."


_HANDLERS: dict[str, Handler] = {
    "use": _recover_use,
    "restore": _recover_restore,
    "adopt": _recover_links,
    "links": _recover_links,
    "update": _recover_update,
    "add": _recover_add,
    "install": _recover_install,
}
