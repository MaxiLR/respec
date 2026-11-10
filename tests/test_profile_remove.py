"""``respec profile remove <name>``: a profile goes to a backup, never deleted.

The profile's folder (``profile.yaml`` and its skill copies) moves in one
rename to ``<respec home>/removed-profiles/<run>/<name>/``. The active profile,
an unknown or invalid name, an interrupted change and a running respec are
refused, and change nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def respec_home(isolated_homes):
    return isolated_homes.respec_home


def make_profile(respec_home, name, targets=("claude-code",), skills=("tdd",)):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill} of {name}\n")
    data = {"targets": list(targets), "skills": {s: {"enabled": True} for s in skills}}
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return folder


def snapshot(folder):
    """Every file below ``folder`` with its content."""
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def listed(run):
    result = run("profile", "list", "--json")
    assert result.exit_code == 0, result.output
    return [entry["name"] for entry in json.loads(result.stdout)["profiles"]]


def removed_copies(respec_home, name):
    root = respec_home / "removed-profiles"
    return sorted(root.glob(f"*/{name}")) if root.is_dir() else []


# --- success ---------------------------------------------------------------


def test_remove_moves_the_profile_folder_to_a_backup(run, respec_home):
    folder = make_profile(respec_home, "spare", skills=("tdd", "lint"))
    before = snapshot(folder)

    result = run("profile", "remove", "spare")

    assert result.exit_code == 0, result.output
    assert not folder.exists()
    assert listed(run) == []
    [backup] = removed_copies(respec_home, "spare")
    assert snapshot(backup) == before
    assert "Removed profile 'spare'" in result.output
    assert str(backup) in result.output
    # The way back is spelled out.
    assert str(respec_home / "profiles" / "spare") in result.output


def test_remove_json_reports_the_backup(run, respec_home, assert_no_nulls):
    folder = make_profile(respec_home, "spare")

    result = run("profile", "remove", "spare", "--json")

    assert result.exit_code == 0, result.output
    data = assert_no_nulls(json.loads(result.stdout))
    [backup] = removed_copies(respec_home, "spare")
    assert data == {
        "name": "spare",
        "path": str(folder),
        "backup": str(backup),
        "warnings": [],
    }


def test_removing_twice_keeps_both_backups(run, respec_home):
    make_profile(respec_home, "spare", skills=("one",))
    assert run("profile", "remove", "spare").exit_code == 0
    make_profile(respec_home, "spare", skills=("two",))
    assert run("profile", "remove", "spare").exit_code == 0

    backups = removed_copies(respec_home, "spare")
    assert len(backups) == 2
    assert {next(iter((b / "skills").iterdir())).name for b in backups} == {
        "one",
        "two",
    }


def test_a_profile_with_an_invalid_profile_yaml_can_still_be_removed(run, respec_home):
    folder = make_profile(respec_home, "broken")
    (folder / "profile.yaml").write_text("targets: [nowhere]\n")

    result = run("profile", "remove", "broken")

    assert result.exit_code == 0, result.output
    assert not folder.exists()
    assert len(removed_copies(respec_home, "broken")) == 1


def test_a_removed_profile_comes_back_by_moving_its_folder(run, respec_home):
    make_profile(respec_home, "spare")
    data = json.loads(run("profile", "remove", "spare", "--json").stdout)

    (respec_home / "profiles").mkdir(exist_ok=True)
    Path(data["backup"]).rename(respec_home / "profiles" / "spare")

    assert listed(run) == ["spare"]
    assert run("use", "spare").exit_code == 0


# --- refusals --------------------------------------------------------------


def test_the_active_profile_is_refused(run, respec_home):
    folder = make_profile(respec_home, "work")
    make_profile(respec_home, "other", skills=("lint",))
    assert run("use", "work").exit_code == 0
    before = snapshot(folder)

    result = run("profile", "remove", "work")

    assert result.exit_code == 1
    assert "active" in result.output
    assert "respec use" in result.output and "respec restore" in result.output
    assert snapshot(folder) == before
    assert removed_copies(respec_home, "work") == []


def test_the_active_profile_is_refused_with_json(run, respec_home, assert_no_nulls):
    make_profile(respec_home, "work")
    assert run("use", "work").exit_code == 0

    result = run("profile", "remove", "work", "--json")

    assert result.exit_code == 1
    data = assert_no_nulls(json.loads(result.stdout))
    assert set(data) == {"name", "error", "warnings"}
    assert data["name"] == "work"
    assert "respec use" in data["error"]
    assert (respec_home / "profiles" / "work").is_dir()


def test_after_switching_away_the_former_profile_can_be_removed(run, respec_home):
    make_profile(respec_home, "work")
    make_profile(respec_home, "other", skills=("lint",))
    assert run("use", "work").exit_code == 0
    assert run("use", "other").exit_code == 0

    assert run("profile", "remove", "work").exit_code == 0
    assert listed(run) == ["other"]


def test_an_unknown_profile_is_refused(run, respec_home, assert_no_nulls):
    result = run("profile", "remove", "ghost")
    assert result.exit_code == 1
    assert "profile 'ghost' does not exist" in result.output

    data = assert_no_nulls(
        json.loads(run("profile", "remove", "ghost", "--json").stdout)
    )
    assert "does not exist" in data["error"]
    assert not (respec_home / "removed-profiles").exists()


@pytest.mark.parametrize("name", ["../profiles", "..", "a/b", ".hidden", "x\n"])
def test_invalid_names_are_refused_and_nothing_moves(run, respec_home, name):
    make_profile(respec_home, "keep")
    before = snapshot(respec_home / "profiles")

    result = run("profile", "remove", name)

    assert result.exit_code == 1
    assert "invalid profile name" in result.output
    assert snapshot(respec_home / "profiles") == before
    assert not (respec_home / "removed-profiles").exists()


def test_an_interrupted_change_is_refused_not_recovered(run, respec_home, killed):
    make_profile(respec_home, "a")
    spare = make_profile(respec_home, "spare", skills=("lint",))
    assert killed("use:begin", 1, "use", "a")
    from respec.state import load_state

    journal_before = load_state(respec_home).journal
    assert journal_before is not None

    result = run("profile", "remove", "spare", "--json")

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert "respec recover" in data["error"]
    assert spare.is_dir()
    # The interrupted change still waits; this command did not settle it.
    assert load_state(respec_home).journal == journal_before
    assert run("profile", "remove", "spare").exit_code == 1


def test_a_running_respec_is_refused(run, respec_home, holder, monkeypatch):
    from respec import lock

    monkeypatch.setattr(lock, "WAIT", 0.05)
    make_profile(respec_home, "work")
    spare = make_profile(respec_home, "spare", skills=("lint",))
    assert run("use", "work").exit_code == 0
    running = holder("links:begin", "disable", "tdd")

    text = run("profile", "remove", "spare")
    as_json = run("profile", "remove", "spare", "--json")

    assert text.exit_code == 1
    assert "another respec is running" in text.output
    assert as_json.exit_code == 1
    data = json.loads(as_json.stdout)
    assert set(data) == {"name", "error", "warnings"}
    assert "another respec is running" in data["error"]
    assert spare.is_dir()
    assert running.finish()[0] == 0
    assert run("profile", "remove", "spare").exit_code == 0


# --- interruption ----------------------------------------------------------


@pytest.mark.parametrize("point", ["profile-remove:move", "profile-remove:moved"])
def test_a_kill_around_the_move_loses_nothing(run, respec_home, killed, point):
    folder = make_profile(respec_home, "spare", skills=("tdd", "lint"))
    before = snapshot(folder)

    assert killed(point, 1, "profile", "remove", "spare")

    copies = removed_copies(respec_home, "spare")
    if folder.exists():
        assert copies == []
        assert snapshot(folder) == before
    else:
        [backup] = copies
        assert snapshot(backup) == before
    # Nothing is left for recovery to do, and nothing it does loses it.
    status = json.loads(run("status", "--json").stdout)
    assert status["warnings"] == []
    assert run("recover").exit_code == 0
    if folder.exists():
        assert listed(run) == ["spare"]
        assert run("profile", "remove", "spare").exit_code == 0
    assert [snapshot(c) for c in removed_copies(respec_home, "spare")] == [before]
