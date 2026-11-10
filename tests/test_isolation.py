from pathlib import Path

import pytest

from conftest import REAL_HOME
from respec import paths


def test_homes_point_at_temporary_directories(isolated_homes):
    assert Path.home() == isolated_homes.home
    assert paths.respec_home() == isolated_homes.respec_home
    assert paths.user_home() == isolated_homes.home


def test_resolving_under_the_real_home_fails_the_test(monkeypatch):
    monkeypatch.setenv("RESPEC_USER_HOME", str(REAL_HOME))
    with pytest.raises(pytest.fail.Exception, match="real home"):
        paths.user_home()


def test_respec_home_under_the_real_home_fails_the_test(monkeypatch):
    monkeypatch.setenv("RESPEC_HOME", str(REAL_HOME / ".respec"))
    with pytest.raises(pytest.fail.Exception, match="real home"):
        paths.respec_home()
