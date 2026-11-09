"""Resolution of respec's own home and of the user home that targets live in.

Both are overridable so that tests and experiments never touch the real home:

- ``RESPEC_HOME`` relocates respec's data directory (default ``~/.respec``).
- ``RESPEC_USER_HOME`` (or the ``--home`` CLI option) relocates the home that
  target skill folders such as ``~/.claude/skills`` resolve against.
"""

from __future__ import annotations

import os
from pathlib import Path

RESPEC_HOME_ENV = "RESPEC_HOME"
USER_HOME_ENV = "RESPEC_USER_HOME"


def _absolute(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def user_home(override: str | os.PathLike[str] | None = None) -> Path:
    """Home directory that target folders resolve against."""
    if override:
        return _absolute(override)
    env = os.environ.get(USER_HOME_ENV)
    if env:
        return _absolute(env)
    return Path.home().resolve()


def respec_home(override: str | os.PathLike[str] | None = None) -> Path:
    """respec's data directory (``~/.respec`` unless relocated)."""
    if override:
        return _absolute(override)
    env = os.environ.get(RESPEC_HOME_ENV)
    if env:
        return _absolute(env)
    return user_home() / ".respec"
