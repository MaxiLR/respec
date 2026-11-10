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
