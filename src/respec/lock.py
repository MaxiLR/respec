"""One respec at a time: an exclusive lock on ``<respec home>/.lock``.

Every command that changes skills, profiles, takeovers or backups holds it
while it runs (the CLI for the whole command, the TUI for each change it
makes), and so does every journaled change (:func:`respec.journal.begin`) and
its recovery. Commands that only read (``status``, ``profile list``/``show``,
``layer list``/``show``, ``update --check``, ``restore --list``) never take
it.

A second process that wants it waits up to :data:`WAIT` seconds, then fails
with :class:`Busy` ("another respec is running") and changes nothing.

It is an ``flock`` on an open file, so the operating system drops it when
the holder exits, also when it is killed: a crash never leaves a stale lock
behind. While some process holds it, a journal in ``state.json`` belongs to
a change that is still running, not to an interrupted one (:func:`busy`).
The lock is reentrant within one process.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
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


class Busy(RespecError):
    """Another respec process is changing things right now."""


# respec home -> [open descriptor, depth] for the locks this process holds.
_held: dict[Path, list[int]] = {}
_guard = threading.Lock()


def lock_path(respec_home: Path) -> Path:
    return respec_home / LOCK_FILE


def acquire(respec_home: Path) -> None:
    """Take the lock (again, when this process holds it already); raise
    :class:`Busy` when another process keeps it for :data:`WAIT` seconds."""
    key = Path(respec_home)
    with _guard:
        if key in _held:
            _held[key][1] += 1
            return
        if fcntl is None:
            _held[key] = [-1, 1]
            return
        key.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path(key), os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + WAIT
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise Busy(
                        "another respec is running and changing skills (a "
                        "command or the TUI); nothing was changed. Try again "
                        "when it has finished."
                    ) from None
                time.sleep(_POLL)
        _held[key] = [descriptor, 1]


def release(respec_home: Path) -> None:
    """Undo one :func:`acquire`; the last one lets the lock go."""
    key = Path(respec_home)
    with _guard:
        entry = _held.get(key)
        if entry is None:
            return
        entry[1] -= 1
        if entry[1] == 0:
            del _held[key]
            _close(entry[0])


def release_all() -> None:
    """Let every lock this process holds go (the end of a CLI command)."""
    with _guard:
        held = list(_held.values())
        _held.clear()
    for descriptor, _ in held:
        _close(descriptor)


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
    """Whether this process holds the lock."""
    with _guard:
        return Path(respec_home) in _held


def busy(respec_home: Path) -> bool:
    """Whether another process holds the lock right now (reads only: a free
    lock is taken shared for an instant, never kept)."""
    if fcntl is None or holds(respec_home):
        return False
    try:
        descriptor = os.open(lock_path(respec_home), os.O_RDONLY)
    except OSError:
        return False  # never locked
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(descriptor)  # also drops the shared lock
    return False
