"""One respec at a time: an exclusive lock on ``<respec home>/.lock``.

Every command that changes skills, profiles, takeovers or backups holds it
while it runs (the CLI for the whole command, the TUI for each change it
makes), and so does every journaled change (:func:`respec.journal.begin`) and
its recovery. Commands that only read (``status``, ``profile list``/``show``,
``layer list``/``show``, ``update --check``, ``restore --list``) never take
it exclusively; they read ``state.json`` under a shared lock for an instant
(:func:`reading`), so a change that is still running is never taken for an
interrupted one.

A second process (or a second thread of the same process, such as the TUI's
git worker and its screen) that wants it waits up to :data:`WAIT` seconds,
then fails with :class:`Busy` ("another respec is running") and changes
nothing. The lock is reentrant only within the thread that holds it.

It is an ``flock`` on an open file, so the operating system drops it when
the holder exits, also when it is killed: a crash never leaves a stale lock
behind. Whoever takes it while nobody else holds it removes temporary
``state.json`` files a killed writer left behind (:func:`_sweep`).
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # not on Windows: no locking there
    fcntl = None  # type: ignore[assignment]

from respec.errors import RespecError

LOCK_FILE = ".lock"
# How long a second process waits for the lock before it gives up (seconds).
WAIT = 1.0
_POLL = 0.02
# Temporary files of state.json writes (see respec.state.save_state).
STATE_TEMPORARY = ".state.json.*.tmp"


class Busy(RespecError):
    """Another respec process (or thread) is changing things right now."""


def _busy_error() -> Busy:
    return Busy(
        "another respec is running and changing skills (a command or the "
        "TUI); nothing was changed. Try again when it has finished."
    )


@dataclass
class _Hold:
    descriptor: int
    depth: int
    owner: int  # threading.get_ident() of the holding thread


# respec home -> the lock this process holds there.
_held: dict[Path, _Hold] = {}
_guard = threading.Lock()


def lock_path(respec_home: Path) -> Path:
    return respec_home / LOCK_FILE


def acquire(respec_home: Path) -> None:
    """Take the lock (again, when this thread holds it already); raise
    :class:`Busy` when another process or thread keeps it for :data:`WAIT`
    seconds."""
    key = Path(respec_home)
    me = threading.get_ident()
    deadline = time.monotonic() + WAIT
    while True:
        with _guard:
            hold = _held.get(key)
            if hold is not None and hold.owner == me:
                hold.depth += 1
                return
            if hold is None and _try_take(key, me):
                return
        if time.monotonic() >= deadline:
            raise _busy_error()
        time.sleep(_POLL)  # the guard is free while waiting


def _try_take(key: Path, me: int) -> bool:
    """Take the flock if no other process holds it (called under _guard)."""
    if fcntl is None:
        _held[key] = _Hold(-1, 1, me)
        return True
    key.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path(key), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return False
    _held[key] = _Hold(descriptor, 1, me)
    _sweep(key)
    return True


def _sweep(respec_home: Path) -> None:
    """Remove temporary state files: with the lock taken, no live writer is
    left to finish one, so they were left by a killed process."""
    for leftover in respec_home.glob(STATE_TEMPORARY):
        try:
            leftover.unlink()
        except OSError:
            pass


def release(respec_home: Path) -> None:
    """Undo one :func:`acquire`; the last one lets the lock go."""
    key = Path(respec_home)
    with _guard:
        hold = _held.get(key)
        if hold is None or hold.owner != threading.get_ident():
            return
        hold.depth -= 1
        if hold.depth == 0:
            del _held[key]
            _close(hold.descriptor)


def release_all() -> None:
    """Let every lock this process holds go (the end of a CLI command)."""
    with _guard:
        held = list(_held.values())
        _held.clear()
    for hold in held:
        _close(hold.descriptor)


def _close(descriptor: int) -> None:
    if descriptor >= 0:
        os.close(descriptor)  # closing drops the flock


@contextmanager
def exclusive(respec_home: Path) -> Iterator[None]:
    """Hold the lock while the ``with`` block runs."""
    acquire(respec_home)
    try:
        yield
    finally:
        release(respec_home)


def holds(respec_home: Path) -> bool:
    """Whether this thread holds the lock."""
    with _guard:
        hold = _held.get(Path(respec_home))
        return hold is not None and hold.owner == threading.get_ident()


@contextmanager
def reading(respec_home: Path) -> Iterator[bool]:
    """For a read that must not mistake a running change for an interrupted
    one: yields whether another process or thread is changing things right
    now (``True``: it holds the lock). Otherwise the lock is held shared
    while the ``with`` block reads, so no change starts or ends meanwhile.
    Never waits."""
    key = Path(respec_home)
    with _guard:
        hold = _held.get(key)
        owner = hold.owner if hold is not None else None
    if owner is not None:  # held in this process: by this thread or another
        yield owner != threading.get_ident()
        return
    if fcntl is None:
        yield False
        return
    try:
        descriptor = os.open(lock_path(key), os.O_RDONLY)
    except OSError:
        yield False  # never locked
        return
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            yield True
            return
        except OSError:
            pass
        yield False
    finally:
        os.close(descriptor)  # also drops the shared lock


def busy(respec_home: Path) -> bool:
    """Whether another process or thread holds the lock right now."""
    with reading(respec_home) as running:
        return running
