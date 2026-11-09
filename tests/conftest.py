"""Test isolation: every test runs against temporary homes, never the real one."""

from __future__ import annotations

import os
import pwd
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

# Resolved from the password database so an inherited HOME override cannot hide it.
REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def is_under_real_home(path: Path | str) -> bool:
    resolved = Path(path).expanduser().resolve()
    return resolved == REAL_HOME or REAL_HOME in resolved.parents


@pytest.fixture(autouse=True)
def isolated_homes(tmp_path, monkeypatch):
    """Point HOME, RESPEC_HOME and RESPEC_USER_HOME at temp dirs for every test.

    The respec path resolvers are wrapped so that any resolution under the real
    home fails the test instead of touching the engineer's machine.
    """
    if is_under_real_home(tmp_path):
        pytest.fail(f"pytest tmp_path {tmp_path} is under the real home {REAL_HOME}")

    home = tmp_path / "home"
    respec_home = tmp_path / "respec-home"
    home.mkdir()
    respec_home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RESPEC_HOME", str(respec_home))
    monkeypatch.setenv("RESPEC_USER_HOME", str(home))

    from respec import paths

    for name in ("respec_home", "user_home"):
        original = getattr(paths, name)

        def guarded(*args, _original=original, _name=name, **kwargs):
            result = _original(*args, **kwargs)
            if is_under_real_home(result):
                pytest.fail(
                    f"respec.paths.{_name}() resolved under the real home: {result}"
                )
            return result

        monkeypatch.setattr(paths, name, guarded)

    return SimpleNamespace(home=home, respec_home=respec_home)


@pytest.fixture
def run():
    """Invoke the respec CLI in-process and return the click Result."""
    from respec.cli import app

    runner = CliRunner()

    def invoke(
        *args: str, env: dict[str, str | None] | None = None, input: str | None = None
    ):
        return runner.invoke(app, list(args), env=env, input=input)

    return invoke
