import json
import os
from datetime import datetime, timezone

import pytest
import yaml

from respec import switch


def make_profile(respec_home, name, targets, skills):
    """Write a profile folder whose skills map name -> enabled."""
    folder = respec_home / "profiles" / name
    for skill in skills:
        skill_dir = folder / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill} from {name}\n")
    (folder / "skills").mkdir(parents=True, exist_ok=True)
    data = {
        "targets": targets,
        "skills": {skill: {"enabled": enabled} for skill, enabled in skills.items()},
    }
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return folder


def tree(folder):
    """Relative paths and file contents below folder (symlinks followed)."""
    result = {}
    for root, dirs, files in os.walk(folder, followlinks=True):
        for name in files:
            path = os.path.join(root, name)
            result[os.path.relpath(path, folder)] = open(path).read()
        for name in dirs:
            result[os.path.relpath(os.path.join(root, name), folder) + "/"] = None
    return result


@pytest.fixture
def dirs(isolated_homes):
    home = isolated_homes.home
    return {
        "claude-code": home / ".claude" / "skills",
        "agents": home / ".agents" / "skills",
        "oh-my-pi": home / ".omp" / "agent" / "skills",
    }


@pytest.fixture
def state_file(isolated_homes):
    return isolated_homes.respec_home / "state.json"


def read_state(state_file):
    return json.loads(state_file.read_text())


def recorded_paths(state_file):
    return sorted(item["path"] for item in read_state(state_file)["installed"])


def test_use_symlinks_enabled_skills_into_every_target_and_records_them(
    run, isolated_homes, dirs, state_file
):
    profile = make_profile(
        isolated_homes.respec_home, "a", ["claude-code", "agents"], {"tdd": True}
    )

    result = run("use", "a")

    assert result.exit_code == 0, result.output
    for target in ("claude-code", "agents"):
        link = dirs[target] / "tdd"
        assert link.is_symlink()
        assert link.resolve() == (profile / "skills" / "tdd").resolve()
        assert (link / "SKILL.md").read_text() == "# tdd from a\n"
    assert not dirs["oh-my-pi"].exists()
    state = read_state(state_file)
    assert state["active_profile"] == "a"
    assert recorded_paths(state_file) == sorted(
        [str(dirs["claude-code"] / "tdd"), str(dirs["agents"] / "tdd")]
    )


def test_disabled_skills_are_never_linked(run, isolated_homes, dirs, state_file):
    make_profile(
        isolated_homes.respec_home,
        "a",
        ["claude-code"],
        {"tdd": True, "notes": False},
    )

    assert run("use", "a").exit_code == 0

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["tdd"]
    assert recorded_paths(state_file) == [str(dirs["claude-code"] / "tdd")]


def test_copy_fallback_when_symlinking_fails(
    run, isolated_homes, dirs, state_file, monkeypatch
):
    make_profile(isolated_homes.respec_home, "a", ["agents"], {"tdd": True})

    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    monkeypatch.setattr(os, "symlink", refuse)

    result = run("use", "a")

    assert result.exit_code == 0, result.output
    copied = dirs["agents"] / "tdd"
    assert copied.is_dir() and not copied.is_symlink()
    assert (copied / "SKILL.md").read_text() == "# tdd from a\n"
    assert recorded_paths(state_file) == [str(copied)]


def test_installing_respec_alone_changes_nothing(run, isolated_homes, dirs):
    (dirs["claude-code"] / "mine").mkdir(parents=True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("mine\n")
    before = tree(isolated_homes.home)

    assert run("status").exit_code == 0
    assert run("profile", "new", "a", "-t", "claude-code").exit_code == 0
    assert run("profile", "list").exit_code == 0

    assert tree(isolated_homes.home) == before
    assert not (isolated_homes.respec_home / "backups").exists()
    assert not (isolated_homes.respec_home / "state.json").exists()


def test_first_takeover_backs_up_full_folder_contents(run, isolated_homes, dirs):
    folder = dirs["claude-code"]
    (folder / "mine" / "refs").mkdir(parents=True)
    (folder / "mine" / "SKILL.md").write_text("mine\n")
    (folder / "mine" / "refs" / "a.md").write_text("ref\n")
    (folder / "loose.txt").write_text("loose\n")
    original = tree(folder)
    make_profile(isolated_homes.respec_home, "a", ["claude-code"], {"tdd": True})

    result = run("use", "a")

    assert result.exit_code == 0, result.output
    [backup_run] = list((isolated_homes.respec_home / "backups").iterdir())
    assert tree(backup_run / "claude-code") == original
    assert json.loads(run("status", "--json").stdout)["active_profile"] == "a"


def test_folder_is_backed_up_only_on_first_takeover(run, isolated_homes, dirs):
    (dirs["claude-code"]).mkdir(parents=True)
    (dirs["claude-code"] / "loose.txt").write_text("loose\n")
    make_profile(isolated_homes.respec_home, "a", ["claude-code"], {"tdd": True})
    make_profile(isolated_homes.respec_home, "b", ["claude-code"], {"lint": True})

    assert run("use", "a").exit_code == 0
    assert run("use", "b").exit_code == 0
    assert run("use", "a").exit_code == 0

    backups = isolated_homes.respec_home / "backups"
    [backup_run] = list(backups.iterdir())
    assert tree(backup_run) == {
        "claude-code/": None,
        "claude-code/loose.txt": "loose\n",
    }


def test_backups_taken_in_the_same_second_do_not_collide(
    isolated_homes, dirs, monkeypatch
):
    dirs["claude-code"].mkdir(parents=True)
    (dirs["claude-code"] / "first.txt").write_text("first\n")
    dirs["oh-my-pi"].mkdir(parents=True)
    (dirs["oh-my-pi"] / "second.txt").write_text("second\n")
    make_profile(isolated_homes.respec_home, "a", ["claude-code"], {"tdd": True})
    make_profile(isolated_homes.respec_home, "b", ["oh-my-pi"], {"tdd": True})
    frozen = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)

    homes = (isolated_homes.respec_home, isolated_homes.home)
    switch.use(*homes, "a", now=lambda: frozen)
    switch.use(*homes, "b", now=lambda: frozen)

    runs = sorted((isolated_homes.respec_home / "backups").iterdir())
    assert len(runs) == 2
    contents = [tree(run_dir) for run_dir in runs]
    assert {"claude-code/": None, "claude-code/first.txt": "first\n"} in contents
    assert {"oh-my-pi/": None, "oh-my-pi/second.txt": "second\n"} in contents


def test_switch_scenario_a_to_b_leaves_former_folders_free_of_a(
    run, isolated_homes, dirs, state_file
):
    make_profile(
        isolated_homes.respec_home,
        "a",
        ["claude-code", "agents"],
        {"tdd": True, "review": True},
    )
    make_profile(isolated_homes.respec_home, "b", ["oh-my-pi"], {"pi-skill": True})

    assert run("use", "a").exit_code == 0
    result = run("use", "b")

    assert result.exit_code == 0, result.output
    assert list(dirs["claude-code"].iterdir()) == []
    assert list(dirs["agents"].iterdir()) == []
    assert sorted(p.name for p in dirs["oh-my-pi"].iterdir()) == ["pi-skill"]
    assert read_state(state_file)["active_profile"] == "b"
    assert recorded_paths(state_file) == [str(dirs["oh-my-pi"] / "pi-skill")]


def test_switch_removes_copied_items_too(
    run, isolated_homes, dirs, state_file, monkeypatch
):
    make_profile(isolated_homes.respec_home, "a", ["agents"], {"tdd": True})
    make_profile(isolated_homes.respec_home, "b", ["oh-my-pi"], {"other": True})
    with monkeypatch.context() as patch:
        patch.setattr(os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError()))
        assert run("use", "a").exit_code == 0
    assert (dirs["agents"] / "tdd").is_dir()

    assert run("use", "b").exit_code == 0

    assert list(dirs["agents"].iterdir()) == []


def test_switch_only_removes_recorded_paths_and_keeps_profile_folders(
    run, isolated_homes, dirs
):
    profile_a = make_profile(
        isolated_homes.respec_home, "a", ["claude-code"], {"tdd": True}
    )
    make_profile(isolated_homes.respec_home, "b", ["claude-code"], {"lint": True})
    assert run("use", "a").exit_code == 0
    # Dropped in after activation by another tool: not recorded, must survive.
    (dirs["claude-code"] / "foreign").mkdir()
    (dirs["claude-code"] / "foreign" / "SKILL.md").write_text("foreign\n")
    profile_a_before = tree(profile_a)

    assert run("use", "b").exit_code == 0

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == [
        "foreign",
        "lint",
    ]
    assert (dirs["claude-code"] / "foreign" / "SKILL.md").read_text() == "foreign\n"
    assert tree(profile_a) == profile_a_before


def test_use_refuses_to_overwrite_unrecorded_entry(run, isolated_homes, dirs):
    (dirs["claude-code"] / "tdd").mkdir(parents=True)
    (dirs["claude-code"] / "tdd" / "SKILL.md").write_text("mine\n")
    make_profile(isolated_homes.respec_home, "a", ["claude-code"], {"tdd": True})

    result = run("use", "a")

    assert result.exit_code == 1
    assert "not managed by respec" in result.output
    assert (dirs["claude-code"] / "tdd" / "SKILL.md").read_text() == "mine\n"
    assert not (isolated_homes.respec_home / "state.json").exists()
    assert not (isolated_homes.respec_home / "backups").exists()


def test_use_unknown_profile_fails_without_changes(run, isolated_homes):
    result = run("use", "missing")

    assert result.exit_code == 1
    assert "profile 'missing' does not exist" in result.output
    assert not (isolated_homes.respec_home / "state.json").exists()


def test_status_json_before_any_switch(run):
    result = run("status", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "active_profile": None,
        "targets": [],
        "folders": [],
    }


def test_status_json_shows_profile_targets_and_items_per_folder(
    run, isolated_homes, dirs
):
    make_profile(
        isolated_homes.respec_home, "a", ["claude-code", "agents"], {"tdd": True}
    )
    make_profile(
        isolated_homes.respec_home, "b", ["agents"], {"lint": True, "review": True}
    )
    assert run("use", "a").exit_code == 0
    assert run("use", "b").exit_code == 0

    result = run("status", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "active_profile": "b",
        "targets": ["agents"],
        "folders": [
            {
                "target": "claude-code",
                "skills_dir": str(dirs["claude-code"]),
                "items": [],
            },
            {
                "target": "agents",
                "skills_dir": str(dirs["agents"]),
                "items": [
                    {
                        "name": "lint",
                        "path": str(dirs["agents"] / "lint"),
                        "mode": "symlink",
                    },
                    {
                        "name": "review",
                        "path": str(dirs["agents"] / "review"),
                        "mode": "symlink",
                    },
                ],
            },
        ],
    }


def test_status_human_lists_active_profile_and_items(run, isolated_homes, dirs):
    make_profile(isolated_homes.respec_home, "a", ["oh-my-pi"], {"tdd": True})
    assert run("use", "a").exit_code == 0

    result = run("status")

    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "Active profile: a" in out
    assert str(dirs["oh-my-pi"]) in out
    assert any(line.strip().startswith("tdd") for line in out.splitlines())


def test_status_human_without_active_profile(run):
    result = run("status")

    assert result.exit_code == 0
    assert "No active profile" in result.stdout
    assert "respec use" in result.stdout


def test_targets_sharing_one_real_folder_are_installed_once_and_tracked(
    run, isolated_homes, dirs, state_file
):
    # A common setup: ~/.claude/skills is a symlink to ~/.agents/skills.
    dirs["agents"].mkdir(parents=True)
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    make_profile(
        isolated_homes.respec_home, "a", ["claude-code", "agents"], {"tdd": True}
    )
    make_profile(isolated_homes.respec_home, "b", ["oh-my-pi"], {"other": True})

    result = run("use", "a")

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in dirs["agents"].iterdir()) == ["tdd"]
    assert (dirs["agents"] / "tdd" / "SKILL.md").read_text() == "# tdd from a\n"
    assert len(read_state(state_file)["installed"]) == 1

    assert run("use", "b").exit_code == 0

    assert list(dirs["agents"].iterdir()) == []
    assert dirs["claude-code"].is_symlink()


def test_failed_install_is_reported_and_earlier_installs_stay_tracked(
    run, isolated_homes, dirs, state_file
):
    make_profile(
        isolated_homes.respec_home, "a", ["claude-code", "agents"], {"tdd": True}
    )
    make_profile(isolated_homes.respec_home, "b", ["oh-my-pi"], {"other": True})
    dirs["agents"].mkdir(parents=True)
    dirs["agents"].chmod(0o555)  # neither a symlink nor a copy can be created
    try:
        result = run("use", "a")

        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "error:" in result.output
        assert recorded_paths(state_file) == [str(dirs["claude-code"] / "tdd")]
        assert (dirs["claude-code"] / "tdd").is_symlink()
    finally:
        dirs["agents"].chmod(0o755)

    assert run("use", "b").exit_code == 0

    assert list(dirs["claude-code"].iterdir()) == []
    assert list(dirs["agents"].iterdir()) == []


def test_failed_backup_leaves_no_partial_backup_and_no_changes(
    run, isolated_homes, dirs
):
    make_profile(
        isolated_homes.respec_home, "a", ["claude-code", "agents"], {"tdd": True}
    )
    (dirs["claude-code"] / "mine").mkdir(parents=True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("mine\n")
    secret = dirs["agents"] / "secret.txt"
    dirs["agents"].mkdir(parents=True)
    secret.write_text("unreadable\n")
    secret.chmod(0o000)
    try:
        result = run("use", "a")
    finally:
        secret.chmod(0o644)

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "back up" in result.output
    backups = isolated_homes.respec_home / "backups"
    assert not backups.exists() or list(backups.iterdir()) == []
    assert not (isolated_homes.respec_home / "state.json").exists()
    assert not (dirs["claude-code"] / "tdd").exists()
