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

    {"operation": "use",              # one of the keys of _HANDLERS
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
- ``adopt`` and ``links``: what was done stays; the step in flight is
  finished when its copy was whole, otherwise undone (``rolled-back``), and a
  link change whose ``profile.yaml`` was not saved yet (``profile_digest``
  unchanged) is reported rolled back. The links of the active profile are then
  put in line with its ``profile.yaml``. Staging folders are settled by
  :func:`respec.adopt._clean_leftovers` (fix-6); those of the overwrite in
  flight that it keeps are set aside.
  A local add journals the folder it makes (``created``; dropped unless
  ``profile.yaml`` lists it), a remove the skill whose folder goes
  (``removing``; deleted once ``profile.yaml`` no longer lists it).
- ``update``: rolled back while ``profile.yaml`` still has the digest taken
  at the start (also after an in-process undo in a late phase), finished
  once it differs. Only the skills journaled under ``swaps`` are touched: a
  rollback puts back their ``.old`` only while it has the recorded digest; a
  finished update deletes its own ``.old`` whatever is left of it. Any other
  ``.old`` folder is kept and reported.
- ``add``: rolled back in ``copy`` (only the skill folders journaled under
  ``created``, which did not exist before, are removed), finished in
  ``refresh``.
- ``install``: kept when its ``profile.yaml`` was written (the last step),
  otherwise the half-copied profile folder is removed (fetched content only).
- An unknown ``operation`` or a malformed journal is only discarded, by
  ``recover(rollback=True)``.

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

from respec import lock, trees
from respec.errors import RespecError
from respec.state import (
    STATE_FILE,
    Installed,
    Owned,
    State,
    load_state,
    save_state,
    state_path,
)

WARNING = "interrupted-operation"
FINISHED = "finished"
REBUILT = "rebuilt"
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


# How :func:`describe` names each operation: on its own, or of its profile.
_NAMES = {"restore": "the restore", "adopt": "the resolution of unknown entries"}
_NAMES_OF_PROFILE = {
    "links": "the link changes of profile {!r}",
    "update": "the update of profile {!r}",
    "add": "the add from git to profile {!r}",
    "install": "the install of profile {!r}",
}


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
    if operation in _NAMES:
        return _NAMES[str(operation)]
    if operation in _NAMES_OF_PROFILE and profile is not None:
        return _NAMES_OF_PROFILE[str(operation)].format(profile)
    return f"a {operation!r} change"


def pending_message(journal: dict[str, Any]) -> str:
    what = describe(journal)
    started = journal.get("started_at")
    when = f" (started {started})" if started else ""
    return (
        f"{what[0].upper()}{what[1:]}{when} was interrupted and did not "
        "complete. Run 'respec recover' to finish it, or 'respec recover "
        "--rollback' to roll it back (Sync in the TUI offers both); any respec "
        "command that changes skills finishes it first."
    )


@dataclass
class Recovery:
    """What :func:`recover` did, or (``outcome`` pending) what waits for it."""

    operation: str
    outcome: str  # FINISHED, ROLLED_BACK, REBUILT or PENDING
    message: str
    profile: str | None = None
    set_aside: list[str] = field(default_factory=list)
    # pending: the path of the step in flight, part of this change (not an
    # unknown entry) until it is recovered.
    in_flight: list[str] = field(default_factory=list)
    # A finished restore: its RestoreResult, so a rerun reports what it did.
    result: Any = None

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
        if self.in_flight:
            data["in_flight"] = list(self.in_flight)
        return data


# Steps whose path is an entry in a target folder that the step makes,
# removes or puts back.
_FOLDER_STEPS = frozenset({"install", "remove", "put-back"})


def in_flight(journal: dict[str, Any] | None) -> list[str]:
    """The entry the step in flight was changing, when it exists: part of the
    interrupted change, which settles it, not an unknown entry."""
    step = (journal or {}).get("pending")
    if not isinstance(step, dict) or step.get("step") not in _FOLDER_STEPS:
        return []
    path = step.get("path")
    return [str(path)] if path and os.path.lexists(path) else []


def pending(respec_home: Path) -> Recovery | None:
    """The interrupted change waiting in ``state.json``, if any (reads only).

    A journal of a change that another respec process is still running (it
    holds the lock) is not interrupted: None. The lock is checked first and
    held shared while ``state.json`` is read (:func:`respec.lock.reading`),
    so a change that ends meanwhile is never reported."""
    with lock.reading(respec_home) as running:
        if running:
            return None
        journal = load_state(respec_home).journal
    if journal is None:
        return None
    paths = in_flight(journal)
    return Recovery(
        operation=str(journal.get("operation")),
        outcome=PENDING,
        message=pending_message(journal)
        + "".join(
            f"\n  {path} is the entry it was changing when it stopped; "
            "recovering the change settles it."
            for path in paths
        ),
        profile=journal.get("profile"),
        in_flight=paths,
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
    # Under the lock: a journal of a change another process is running is
    # not an interrupted one (that process holds the lock: Busy).
    with lock.exclusive(respec_home):
        journal = load_state(respec_home).journal
        if journal is None:
            return
        if _policy.auto:
            from respec import paths

            home = user_home or _policy.user_home or paths.user_home()
            recover(respec_home, home)
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
    with lock.exclusive(respec_home):
        yield from _outermost(respec_home, operation, state, fields)


def _outermost(
    respec_home: Path, operation: str, state: State | None, fields: dict[str, Any]
) -> Iterator[None]:
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
    save_state(respec_home, current, durable=True)
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
        save_state(respec_home, state, durable=True)


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
    save_state(respec_home, target, durable=True)
    checkpoint(f"phase:{phase}")


def note(respec_home: Path, key: str, value: Any) -> None:
    """Append ``value`` to the list ``key`` of the outermost change and save,
    before the step it describes runs (for example a folder about to be made,
    so recovery removes only what this run made)."""
    if _depth() != 1:
        return
    target = _journal_of(respec_home, None)
    if target is None or target.journal is None:
        return
    target.journal.setdefault(key, []).append(value)
    save_state(respec_home, target)
    checkpoint(f"note:{key}")


def file_digest(path: Path) -> str | None:
    """Fingerprint of one file's bytes, None when it is missing."""
    import hashlib

    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


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
        notes += _settle_adopt(respec_home, state, step, path, aside)
    if state.journal is not None:
        state.journal.pop("pending", None)
    save_state(respec_home, state)
    return notes


def _settle_adopt(
    respec_home: Path,
    state: State,
    step: dict[str, Any],
    original: Path,
    aside: _Aside,
) -> list[str]:
    """An add or remove of an unknown entry: its original is only deleted once
    its copy (in a backup or the profile) is complete, so finish that delete,
    or drop a copy that was cut short (the original is still whole). Sets
    ``_local.undone`` when the entry was left as it was."""
    from respec import adopt, profiles

    notes: list[str] = []
    stage = step.get("stage")
    if step.get("choice") == "remove":
        backup = Path(step["backup"])
        if stage == "copy":
            if os.path.lexists(backup):
                trees.delete_entry(backup)
            _local.undone = True
            return notes
    else:
        profile = profiles.load_profile(respec_home, step["profile"])
        live = profile.path / profiles.SKILLS_DIR / step["name"]
        if stage == "copy":
            if step.get("overwrite"):
                # An overwrite starts only when no staging folder of this skill
                # exists, so the ones left now are this step's: settled by the
                # fix-6 rules, and whatever those keep goes to a backup run
                # (never deleted), so a retry is not blocked.
                ours = {
                    f".{step['name']}{adopt.STAGED}",
                    f".{step['name']}{adopt.RETIRED}",
                }
                for kept in adopt._clean_leftovers(respec_home, profile):
                    if Path(kept).name in ours:
                        aside(Path(kept), f"profiles/{profile.name}")
                    else:
                        notes.append(
                            f"left {kept} in place: it is from an interrupted "
                            "change and may hold the only copy of earlier content"
                        )
                if not (
                    os.path.lexists(original) and trees.same_content(live, original)
                ):
                    _local.undone = True
                    return notes  # the profile keeps its previous copy
            elif step["name"] not in profile.skills:
                if os.path.lexists(live):
                    trees.delete_entry(live)  # a copy cut short; the original is whole
                _local.undone = True
                return notes
    if os.path.lexists(original):
        trees.delete_entry(original)
    _drop_records(state, original)
    return notes


def recover(
    respec_home: Path, user_home: Path, rollback: bool = False
) -> Recovery | None:
    """Finish or roll back the interrupted change in ``state.json``, if any.

    ``rollback`` asks to undo it where that is possible (see the module
    docstring). Returns what was done, also kept for :func:`take_reports`.
    Holds respec's lock (:mod:`respec.lock`), so a change another process is
    running is never taken for an interrupted one (:class:`lock.Busy`).
    """
    with lock.exclusive(respec_home):
        return _recover(respec_home, user_home, rollback)


def _recover(respec_home: Path, user_home: Path, rollback: bool) -> Recovery | None:
    state = load_state(respec_home)
    journal = state.journal
    if journal is None:
        return None
    what = describe(journal)
    aside = _Aside(respec_home)
    _local.aside = aside
    _local.undone = False
    _local.result = None
    _local.recovering = True
    if str(journal.get("operation")) not in _HANDLERS:
        _local.recovering = False
        if not rollback:
            raise RespecError(
                f"could not recover {what}: respec does not know this kind of "
                f"change. {_DISCARD_HINT}"
            )
        return _discard(respec_home, journal, "which respec does not know")
    try:
        notes = _settle_pending(respec_home, journal, aside)
        journal = load_state(respec_home).journal or journal
        inner = journal.get("switch")
        if isinstance(inner, dict) and inner.get("profile"):
            # A refresh inside this change was cut short: activate its profile
            # again first, so the change below finds it active.
            _recover_use(respec_home, user_home, {"operation": "use", **inner}, False)
        handler = _HANDLERS[str(journal.get("operation"))]
        outcome, message = handler(respec_home, user_home, journal, rollback)
        if journal.get("operation") == "use" or isinstance(inner, dict):
            # A switch cut between logging its takeovers and recording them in
            # state.json: those folders were not taken over after all.
            from respec import takeovers

            takeovers.release_unowned(respec_home, load_state(respec_home).owned)
        _clear(respec_home)
    except (KeyError, TypeError, ValueError) as error:
        if rollback:
            _local.recovering = False
            return _discard(respec_home, journal, f"which is malformed ({error!r})")
        raise RespecError(
            f"could not recover {what}: its journal in state.json is malformed "
            f"({error!r}). It stays recorded. {_DISCARD_HINT}"
        ) from None
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
        result=_local.result,
    )
    _policy.reports.append(report)
    return report


_DISCARD_HINT = (
    "'respec recover --rollback' discards the journal: the records of "
    "state.json are kept as they are, and Sync (or 'respec status') checks the "
    "folders afterwards."
)


def _discard(respec_home: Path, journal: dict[str, Any], why: str) -> Recovery:
    """Drop a journal that cannot be recovered; the records stay as they are."""
    _clear(respec_home)
    report = Recovery(
        operation=str(journal.get("operation")),
        outcome=ROLLED_BACK,
        message=(
            f"Discarded the journal of {describe(journal)}, {why}; the records "
            "in state.json are kept. Run Sync (or 'respec status') to check "
            "the folders."
        ),
    )
    _policy.reports.append(report)
    return report


def rebuild_state(respec_home: Path, user_home: Path) -> Recovery:
    """Replace a ``state.json`` that cannot be read (empty or cut off after a
    power loss) with a record rebuilt from disk. Nothing is deleted.

    The damaged file goes to a fresh backup run. respec owns again every
    target folder that holds a link into its own folders (profiles, global or
    shipped skills), and records those links as its own; everything else in
    those folders (copies included) becomes an unknown entry for
    ``respec adopt`` or ``respec use --unknown``. No profile is active.
    """
    with lock.exclusive(respec_home):
        return _rebuild_state(respec_home, user_home)


def _rebuild_state(respec_home: Path, user_home: Path) -> Recovery:
    from respec import global_skills, switch, targets
    from respec import takeovers as takeover_log

    # Read first: a log from a newer respec refuses before anything changes.
    takeovers = takeover_log.current(respec_home)
    run = switch.new_backup_run(respec_home, switch.utc_now())
    kept = run / STATE_FILE
    shutil.move(str(state_path(respec_home)), str(kept))
    roots = global_skills.source_roots(respec_home)
    state = State()
    owned_folders: set[Path] = set()
    recorded: set[Path] = set()
    moment = _now()
    for target, spec in targets.registry().items():
        folder = spec.skills_dir(user_home)
        if not folder.is_dir():
            continue
        links = [
            entry
            for entry in sorted(folder.iterdir(), key=lambda e: e.name)
            if entry.is_symlink()
            and any(
                entry.resolve() == root or root in entry.resolve().parents
                for root in roots
            )
        ]
        if not links and folder.resolve() not in owned_folders:
            continue
        owned_folders.add(folder.resolve())
        found = takeovers.get(target)
        if found is not None:
            state.owned[target] = found
        else:
            state.owned[target] = Owned(
                skills_dir=str(folder),
                backup=None,
                taken_over_at=moment,
                takeover_unknown=True,
            )
        for entry in links:
            key = trees.real(entry)
            if key not in recorded:
                recorded.add(key)
                state.installed.append(
                    Installed(target, entry.name, str(entry), "symlink")
                )
    save_state(respec_home, state, durable=True)
    unknown_takeover = sorted(t for t, e in state.owned.items() if e.takeover_unknown)
    found_note = (
        f" No takeover record was found for {', '.join(unknown_takeover)}: "
        "'respec restore' then needs a backup run named ('respec restore "
        "--list' shows them), or 'respec restore --release-only' lets go of "
        "the folders without putting anything back."
        if unknown_takeover
        else " Each folder's takeover (its backup run, or that the folder did "
        "not exist) was found again in the takeover log, takeovers.json."
    )
    report = Recovery(
        operation="state",
        outcome=REBUILT,
        message=(
            f"Rebuilt state.json from disk; the damaged file is kept at {kept}. "
            f"respec owns the {len(state.owned)} target folders that hold its "
            f"links and recorded {len(state.installed)} links as its own. No "
            "profile is active: run 'respec use <profile>'. Anything else in "
            "those folders (copies included) is an unknown entry: 'respec "
            "adopt' or 'respec use <profile> --unknown remove' backs it up."
            + found_note
        ),
        set_aside=[str(kept)],
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
        from respec import global_skills

        try:
            # A refresh of respec's own skills may have been cut short.
            global_skills.refresh_shipped(respec_home)
        except RespecError:
            pass  # reported by the next switch
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
            detail = str(error).replace("\n", "\n    ")
            tried.append(f"profile {name!r} could not be activated: {detail}")
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
    if journal.get("release_only"):
        result = restore.RestoreResult(backup=None)
        if load_state(respec_home).owned:
            restore.release_only(respec_home, user_home, progress=result)
        # Items kept before the interruption were already dropped from the
        # records; the journal named them.
        result.kept = list(journal.get("kept", [])) + result.kept
        _local.result = result
        return FINISHED, (
            "Finished letting go of respec's folders: what respec could verify "
            "as its own was removed, nothing was put back."
            + "".join(
                f"\n  kept {path}: respec cannot verify it as its own"
                for path in result.kept
            )
        )
    _local.result = restore.restore(
        respec_home, user_home, journal.get("backup"), overwrite=True
    )
    return FINISHED, (
        "Finished the restore: respec released its folders (entries in the "
        "way were backed up first)."
    )


def _recover_links(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    """adopt and link changes: what was done stays (they cannot be undone),
    the step in flight was finished or undone (``_local.undone``), and the
    active profile's links are put in line with its ``profile.yaml``."""
    from respec import adopt, profiles

    notes: list[str] = []
    name = journal.get("profile")
    profile = None
    if name is not None and name in profiles.list_profile_names(respec_home):
        try:
            profile = profiles.load_profile(respec_home, name)
        except RespecError:
            profile = None
        if profile is not None:
            notes = [
                f"left {kept} in place: it is from an interrupted change and may "
                "hold the only copy of earlier content"
                for kept in adopt._clean_leftovers(respec_home, profile)
            ]
    if profile is not None:
        folders = profile.path / profiles.SKILLS_DIR
        for skill in journal.get("created", []):
            # A local add: its copy goes unless profile.yaml lists it.
            if skill not in profile.skills and os.path.lexists(folders / skill):
                trees.delete_entry(folders / skill)  # a copy; its source is untouched
        for skill in journal.get("removing", []):
            # A remove: the folder goes once profile.yaml no longer lists it.
            if skill not in profile.skills and os.path.lexists(folders / skill):
                trees.delete_entry(folders / skill)
    unchanged = (
        profile is not None
        and "profile_digest" in journal
        and journal["profile_digest"]
        == file_digest(profile.path / profiles.PROFILE_FILE)
    )
    if name is not None:
        _reapply(respec_home, user_home, name)
    if rollback:
        notes.append("it cannot be undone, so it was settled instead")
    tail = "".join(f"\n  {note}" for note in notes)
    what = describe(journal)
    if journal.get("operation") == "adopt":
        if getattr(_local, "undone", False):
            return ROLLED_BACK, (
                f"Rolled back the step in flight of {what}: that entry is as it "
                "was and still waits for a choice; choices completed before it "
                "stay." + tail
            )
        return FINISHED, f"Finished {what}: every choice made stays." + tail
    if unchanged:
        return ROLLED_BACK, (
            f"Rolled back {what}: profile.yaml had not been changed yet"
            + (
                ", and the links match it."
                if load_state(respec_home).active_profile == name
                else "."
            )
            + tail
        )
    if load_state(respec_home).active_profile != name:
        return FINISHED, (
            f"Finished {what}: its profile.yaml is as saved; it is not the "
            "active profile, so no links changed." + tail
        )
    return FINISHED, (
        f"Finished {what}: the links of the active profile match its "
        "profile.yaml." + tail
    )


def _reapply(respec_home: Path, user_home: Path, name: str) -> None:
    from respec import switch

    if load_state(respec_home).active_profile != name:
        return
    try:
        switch.use(respec_home, user_home, name, action="refresh")
    except switch.SwitchBlocked:
        switch.align_links(respec_home, user_home)


def _old_leftovers(skills_dir: Path) -> list[str]:
    """Notes for the ``.<skill>.old`` folders left once this run's own are
    settled: they are kept, as they may hold the only copy of something."""
    return [
        f"left {old} in place: it is not from this update and may hold the "
        "only copy of earlier content"
        for old in sorted(skills_dir.glob(".*.old"))
    ]


def _recover_update(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    """Act only on the skills this run journaled as swapped, and only when the
    folders are still the ones it recorded. Once ``profile.yaml`` holds the new
    commits (it differs from the digest taken at the start) the update is
    finished; before that it is rolled back."""
    from respec import adopt, profiles

    name = journal["profile"]
    profile = profiles.load_profile(respec_home, name)
    skills_dir = profile.path / profiles.SKILLS_DIR
    yaml_file = profile.path / profiles.PROFILE_FILE
    # profile.yaml decides: an in-process undo may have put the old one back
    # after the refresh phase began.
    if "profile_digest" in journal:
        committed = journal["profile_digest"] != file_digest(yaml_file)
    else:
        committed = journal.get("phase") == "refresh"
    swaps = {swap["skill"]: swap for swap in journal.get("swaps", [])}
    fetched = {entry["skill"]: entry["digest"] for entry in journal.get("fetched", [])}
    aside = _local.aside
    notes: list[str] = []
    for skill, swap in swaps.items():
        before = swap["live"]
        live = skills_dir / skill
        old = Path(swap.get("old", skills_dir / f".{skill}.old"))
        incoming = skills_dir / f".{skill}.incoming"
        ours = old.is_dir() and not old.is_symlink() and _digest_or_none(old) == before
        if committed and old.is_dir() and not old.is_symlink():
            # This run's own .old: an update starts only when there is none,
            # and the journal kept every other writer out since. It holds the
            # previous files, which profile.yaml no longer records.
            trees.delete_entry(old)
            if not ours:
                notes.append(
                    f"removed the rest of {old}: this update's previous files "
                    f"of {skill!r}, whose removal the interruption had cut short"
                )
        elif ours:
            if os.path.lexists(live):
                if fetched.get(skill) and _digest_or_none(live) == fetched[skill]:
                    # Fetched upstream files; fetched again later.
                    trees.delete_entry(live)
                else:
                    aside(live, f"profiles/{name}")
            os.replace(old, live)
        if os.path.lexists(incoming):
            # Fetched by this run (an older one was removed).
            trees.delete_entry(incoming)
    ours_dropping = {Path(path) for path in journal.get("dropping", [])}
    for dropping in sorted(skills_dir.glob(".*.dropping")):
        if not dropping.is_dir() or dropping.is_symlink():
            continue
        if dropping in ours_dropping:
            # This run verified it redundant before the delete.
            trees.delete_entry(dropping)
            continue
        skill = dropping.name[1 : -len(".dropping")]
        live = skills_dir / skill
        if (os.path.lexists(live) and trees.same_content(dropping, live)) or (
            adopt._backed_up(respec_home, name, skill, dropping)
        ):
            trees.delete_entry(dropping)  # its content is held elsewhere
        else:
            notes.append(
                f"left {dropping} in place: no update recorded it and its "
                "content is held nowhere else, so it may be the only copy"
            )
    notes += _old_leftovers(skills_dir)
    _reapply(respec_home, user_home, name)
    tail = "".join(f"\n  {note}" for note in notes)
    if committed:
        return FINISHED, (
            f"Finished {describe(journal)}: profile.yaml already recorded the "
            "new commits." + tail
        )
    return ROLLED_BACK, (
        f"Rolled back {describe(journal)}: its skills are as they were before; "
        "run 'respec update' again." + tail
    )


def _digest_or_none(path: Path) -> str | None:
    try:
        return trees.digest(path)
    except OSError:
        return None


def _recover_add(
    respec_home: Path, user_home: Path, journal: dict[str, Any], rollback: bool
) -> tuple[str, str]:
    """Roll back only the skill folders this run journaled as made by it; a
    folder that was there before is never touched."""
    import dataclasses

    from respec import profiles

    name = journal["profile"]
    if journal.get("phase") == "refresh":
        _reapply(respec_home, user_home, name)
        return FINISHED, f"Finished {describe(journal)}."
    profile = profiles.load_profile(respec_home, name)
    created = set(journal.get("created", []))
    skills = {k: v for k, v in profile.skills.items() if k not in created}
    if skills != profile.skills:
        profiles.save_profile(dataclasses.replace(profile, skills=skills))
    for skill in sorted(created):
        folder = profile.path / profiles.SKILLS_DIR / skill
        if os.path.lexists(folder):
            # Made by this run from git; nothing of the user's.
            trees.delete_entry(folder)
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
            trees.delete_entry(folder)  # fetched from git; nothing of the user's
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
