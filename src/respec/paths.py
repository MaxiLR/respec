"""Resolution of respec's own home and of the user home that targets live in.

Both are overridable through advanced/testing environment variables so that
tests and experiments never touch the real home:

- ``RESPEC_USER_HOME`` relocates the home that target skill folders such as
  ``~/.claude/skills`` resolve against.
- ``RESPEC_HOME`` relocates respec's data directory (default
  ``<user home>/.respec``).
"""

from __future__ import annotations

import os
from pathlib import Path

RESPEC_HOME_ENV = "RESPEC_HOME"
USER_HOME_ENV = "RESPEC_USER_HOME"


def _absolute(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def user_home() -> Path:
    """Home directory that target folders resolve against."""
    env = os.environ.get(USER_HOME_ENV)
    if env:
        return _absolute(env)
    return Path.home().resolve()


def respec_home() -> Path:
    """respec's data directory (``~/.respec`` unless relocated)."""
    env = os.environ.get(RESPEC_HOME_ENV)
    if env:
        return _absolute(env)
    return user_home() / ".respec"


def below(path: Path, folder: Path) -> tuple[str, ...] | None:
    """Where ``path`` is in ``folder``: the names from ``folder`` down to it
    (none when it is ``folder`` itself), or None when it is not inside.

    Folders are compared by what they are on disk, not by how they are
    spelled, so a path through a symlink or, on a volume that ignores case,
    in another case is still found inside. A part that does not exist is
    compared by its resolved spelling.
    """
    path, folder = path.resolve(), folder.resolve()
    names: list[str] = []
    for candidate in (path, *path.parents):
        if candidate == folder or _same(candidate, folder):
            return tuple(reversed(names))
        names.append(candidate.name)
    return None


def _same(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False
