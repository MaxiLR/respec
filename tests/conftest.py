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


@pytest.fixture(autouse=True)
def shipped_skills(request, monkeypatch):
    """Leave respec's shipped skills out unless a test is marked ``shipped``.

    respec installs its own skills into every target on each switch. Tests of
    the profile engine assert exact folder contents, so they run without them;
    ``tests/test_global_skills.py`` and the tests marked ``shipped`` cover the
    real behaviour, including how it combines with takeover, adopt and restore.
    """
    if request.node.get_closest_marker("shipped") is None:
        from respec import global_skills

        monkeypatch.setattr(global_skills, "shipped_names", lambda: ())


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


# The JSON fields the README documents as nullable: no active or previous
# profile, a folder that is its own (not ``same_as`` another), and a restored
# folder that did not exist at takeover (a value under ``restored``).
NULLABLE_KEYS = frozenset({"active_profile", "previous_profile", "same_as"})
NULLABLE_UNDER = frozenset({"restored"})


def null_fields(data, where="$", parent=None):
    """Every place in a JSON value that holds ``null`` without being documented
    as nullable, as a path such as ``$.resolved[0].backup``."""
    found = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{where}.{key}"
            if value is None:
                if key not in NULLABLE_KEYS and parent not in NULLABLE_UNDER:
                    found.append(path)
            else:
                found += null_fields(value, path, key)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            if value is None:
                found.append(f"{where}[{index}]")
            else:
                found += null_fields(value, f"{where}[{index}]", None)
    return found


@pytest.fixture
def assert_no_nulls():
    """Check parsed JSON output for undocumented nulls; returns it."""

    def check(data):
        assert null_fields(data) == [], data
        return data

    return check


# Runs the CLI in a child process that SIGKILLs itself at a step boundary:
# ``point`` is a checkpoint name (killed at its ``nth`` pass), ``#`` (killed at
# the ``nth`` checkpoint of any name), ``after-save-profile`` (killed right
# after the ``nth`` profile.yaml write) or ``rmtree-old`` (killed after
# deleting ``nth`` files of the first ``.old`` (or ``.dropping``) folder it
# removes). Nothing in
# the child handles the kill.
KILL_SCRIPT = """
import os, signal, sys
from respec import global_skills, journal, profiles
point, nth = sys.argv[1], int(sys.argv[2])
if os.environ.get("RESPEC_TEST_NO_SHIPPED"):
    global_skills.shipped_names = lambda: ()
seen = []
def die():
    os.kill(os.getpid(), signal.SIGKILL)
def fault(name):
    seen.append(name)
    if (point == "#" and len(seen) == nth) or (
        name == point and seen.count(name) == nth
    ):
        die()
journal._fault = fault
if point == "after-save-profile":
    real = profiles.save_profile
    saved = []
    def save(profile):
        real(profile)
        saved.append(profile)
        if len(saved) == nth:
            die()
    profiles.save_profile = save
if point == "rmtree-old":
    import shutil
    real_rmtree = shutil.rmtree
    def rmtree(path, *args, **kwargs):
        if str(path).endswith((".old", ".dropping")) and os.path.isdir(path):
            # Delete part of it, then die, as a kill mid-delete would.
            files = sorted(
                os.path.join(root, name)
                for root, _, names in os.walk(path)
                for name in names
            )
            for file in files[:nth]:
                os.unlink(file)
            die()
        return real_rmtree(path, *args, **kwargs)
    shutil.rmtree = rmtree
from respec.cli import app
app(sys.argv[3:])
"""


@pytest.fixture
def killed(request):
    """``killed(point, nth, *cli_args)``: run the CLI and kill it at ``point``;
    returns False when the command finished before reaching it."""
    import signal
    import subprocess
    import sys

    def kill(point: str, nth: int, *args: str) -> bool:
        env = os.environ.copy()  # read now: a test may move the homes
        if request.node.get_closest_marker("shipped") is None:
            env["RESPEC_TEST_NO_SHIPPED"] = "1"
        done = subprocess.run(
            [sys.executable, "-c", KILL_SCRIPT, point, str(nth), *args],
            env=env,
            capture_output=True,
            text=True,
        )
        if done.returncode == -signal.SIGKILL:
            return True
        assert done.returncode in (0, 1), done.stdout + done.stderr
        return False

    return kill
