"""Global section (``config.yaml``) and the skills respec ships.

Global skills listed in ``<respec home>/config.yaml`` survive every switch and
go only into the active profile's targets. respec's own shipped skills
(``respec`` and ``profile-maker``) go into every registered target whenever a
profile is active.
"""

import json
import os

import pytest
import yaml

from respec import switch

pytestmark = pytest.mark.shipped

SHIPPED = ["profile-maker", "respec"]


@pytest.fixture
def dirs(isolated_homes):
    home = isolated_homes.home
    return {
        "claude-code": home / ".claude" / "skills",
        "agents": home / ".agents" / "skills",
        "oh-my-pi": home / ".omp" / "agent" / "skills",
    }


@pytest.fixture
def respec_home(isolated_homes):
    return isolated_homes.respec_home


def make_profile(respec_home, name, targets, skills):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill} from {name}\n")
    data = {
        "targets": targets,
        "skills": {skill: {"enabled": True} for skill in skills},
    }
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return folder


def make_global(respec_home, *names):
    for name in names:
        folder = respec_home / "global" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# global {name}\n")
    (respec_home / "config.yaml").write_text(
        yaml.safe_dump({"global": {"skills": list(names)}})
    )


def names(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def recorded(respec_home):
    data = json.loads((respec_home / "state.json").read_text())
    return sorted(item["path"] for item in data["installed"])


def test_global_skills_follow_the_active_targets_and_shipped_go_everywhere(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["claude-code", "agents"], ["tdd"])
    make_profile(respec_home, "b", ["oh-my-pi"], ["lint"])
    make_global(respec_home, "notes")

    assert run("use", "a").exit_code == 0
    assert names(dirs["claude-code"]) == sorted(["notes", "tdd", *SHIPPED])
    assert names(dirs["agents"]) == sorted(["notes", "tdd", *SHIPPED])
    assert names(dirs["oh-my-pi"]) == SHIPPED

    result = run("use", "b")

    assert result.exit_code == 0, result.output
    assert names(dirs["claude-code"]) == SHIPPED
    assert names(dirs["agents"]) == SHIPPED
    assert names(dirs["oh-my-pi"]) == sorted(["lint", "notes", *SHIPPED])
    notes = dirs["oh-my-pi"] / "notes"
    assert (notes / "SKILL.md").read_text() == "# global notes\n"
    # Everything placed is recorded, so a restore or later switch removes it.
    assert recorded(respec_home) == sorted(
        str(folder / name) for folder in dirs.values() for name in names(folder)
    )


def test_global_skill_link_is_not_removed_by_a_switch(run, respec_home, dirs):
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    make_profile(respec_home, "b", ["claude-code"], ["lint"])
    make_global(respec_home, "notes")
    assert run("use", "a").exit_code == 0
    before = {
        name: os.lstat(dirs["claude-code"] / name).st_ino
        for name in ["notes", *SHIPPED]
    }

    result = run("use", "b", "--json")

    assert result.exit_code == 0, result.output
    after = {name: os.lstat(dirs["claude-code"] / name).st_ino for name in before}
    assert after == before
    data = json.loads(result.stdout)
    assert data["removed"] == [str(dirs["claude-code"] / "tdd")]
    assert [item["name"] for item in data["installed"]] == ["lint"]


def test_shipped_skills_are_real_skills_with_matching_names(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], [])

    assert run("use", "a").exit_code == 0

    for target in dirs:
        for name in SHIPPED:
            text = (dirs[target] / name / "SKILL.md").read_text()
            front = yaml.safe_load(text.split("---")[1])
            assert front["name"] == name
            assert front["description"].strip()


def test_stale_shipped_copy_is_refreshed_on_switch(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], [])
    assert run("use", "a").exit_code == 0
    skill = dirs["agents"] / "respec" / "SKILL.md"
    fresh = skill.read_text()
    skill.resolve().write_text("stale\n")

    assert run("use", "a").exit_code == 0

    assert skill.read_text() == fresh


def test_restore_removes_shipped_and_global_skills(run, respec_home, dirs):
    dirs["claude-code"].mkdir(parents=True)
    (dirs["claude-code"] / "mine").mkdir()
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    make_global(respec_home, "notes")
    assert run("use", "a").exit_code == 0

    result = run("restore")

    assert result.exit_code == 0, result.output
    assert names(dirs["claude-code"]) == ["mine"]
    assert not dirs["agents"].exists()
    assert not dirs["oh-my-pi"].exists()
    assert json.loads(run("status", "--json").stdout)["folders"] == []


def test_profile_skill_named_like_a_shipped_skill_is_refused(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["respec"])

    result = run("use", "a")

    assert result.exit_code == 1
    assert "'respec'" in result.output and "ships" in result.output
    assert not (respec_home / "state.json").exists()
    assert not dirs["agents"].exists()


def test_profile_skill_named_like_a_global_skill_is_refused(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["notes"])
    make_global(respec_home, "notes")

    result = run("use", "a")

    assert result.exit_code == 1
    assert "'notes'" in result.output and "config.yaml" in result.output
    assert not dirs["agents"].exists()


def test_global_skill_without_a_folder_is_refused(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    (respec_home / "config.yaml").write_text("global:\n  skills: [ghost]\n")

    result = run("use", "a")

    assert result.exit_code == 1
    assert "ghost" in result.output
    assert not dirs["agents"].exists()


@pytest.mark.parametrize(
    "text",
    [
        "global: [notes]\n",
        "global:\n  skills: notes\n",
        "global:\n  skills: [notes, notes]\n",
        "global:\n  skills: [respec]\n",
        "global:\n  skills: ['../escape']\n",
        "global:\n  colour: blue\n",
        "other: 1\n",
        "global: [\n",
    ],
)
def test_invalid_config_is_refused_without_changes(run, respec_home, dirs, text):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    (respec_home / "global" / "skills" / "notes").mkdir(parents=True)
    (respec_home / "config.yaml").write_text(text)

    result = run("use", "a")

    assert result.exit_code == 1
    assert "config.yaml" in result.output
    assert not dirs["agents"].exists()
    assert not (respec_home / "state.json").exists()


def test_takeover_of_a_folder_outside_the_profile_backs_it_up(run, respec_home, dirs):
    dirs["claude-code"].mkdir(parents=True)
    (dirs["claude-code"] / "mine").mkdir()
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("mine\n")
    make_profile(respec_home, "a", ["oh-my-pi"], ["tdd"])

    result = run("use", "a", "--json")

    assert result.exit_code == 0, result.output
    backup = json.loads(result.stdout)["backups"]["claude-code"]
    assert (dirs["claude-code"] / "mine" / "SKILL.md").exists()
    assert open(os.path.join(backup, "mine", "SKILL.md")).read() == "mine\n"
    # The user's own skill stays and is reported, never blocking the switch.
    warnings = json.loads(result.stdout)["warnings"]
    assert [w["name"] for w in warnings] == ["mine"]


def test_unknown_entry_where_a_shipped_skill_goes_is_resolved_first(
    run, respec_home, dirs
):
    (dirs["oh-my-pi"] / "respec").mkdir(parents=True)
    (dirs["oh-my-pi"] / "respec" / "SKILL.md").write_text("old\n")
    make_profile(respec_home, "a", ["agents"], ["tdd"])

    refused = run("use", "a")
    assert refused.exit_code == 1
    assert str(dirs["oh-my-pi"] / "respec") in refused.output
    assert (dirs["oh-my-pi"] / "respec" / "SKILL.md").read_text() == "old\n"

    result = run("use", "a", "--unknown", "remove")

    assert result.exit_code == 0, result.output
    assert (dirs["oh-my-pi"] / "respec").is_symlink()


def test_enabling_a_skill_reports_only_that_skill(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0
    assert run("disable", "tdd").exit_code == 0

    result = run("enable", "tdd", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["linked"] == [str(dirs["agents"] / "tdd")]
    assert names(dirs["agents"]) == sorted(["tdd", *SHIPPED])


def test_global_skill_dropped_from_config_is_removed_on_next_switch(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_global(respec_home, "notes")
    assert run("use", "a").exit_code == 0
    (respec_home / "config.yaml").write_text("global:\n  skills: []\n")

    assert run("use", "a").exit_code == 0

    assert names(dirs["agents"]) == sorted(["tdd", *SHIPPED])


def test_status_lists_shipped_skills_in_folders_outside_the_profile(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0

    report = json.loads(run("status", "--json").stdout)

    folders = {folder["target"]: folder for folder in report["folders"]}
    assert report["targets"] == ["agents"]
    assert [s["name"] for s in folders["oh-my-pi"]["skills"]] == SHIPPED
    assert [s["name"] for s in folders["agents"]["skills"]] == sorted(["tdd", *SHIPPED])


def test_shipped_skills_install_once_into_folders_shared_by_two_targets(
    run, respec_home, dirs
):
    dirs["agents"].mkdir(parents=True)
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"])
    make_profile(respec_home, "a", ["oh-my-pi"], ["tdd"])

    result = run("use", "a")

    assert result.exit_code == 0, result.output
    assert names(dirs["agents"]) == SHIPPED
    shared = [p for p in recorded(respec_home) if "/.omp/" not in p]
    assert len(shared) == len(SHIPPED)


def test_switch_api_reports_shipped_installs_on_first_use(respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], [])

    result = switch.use(respec_home, respec_home.parent / "home", "a")

    installed = sorted((item.target, item.name) for item in result.installed)
    assert installed == sorted((t, n) for t in dirs for n in SHIPPED)


def test_invalid_config_refuses_a_refresh_and_leaves_the_profile_unchanged(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0
    (respec_home / "config.yaml").write_text("global: [\n")

    result = run("disable", "tdd")

    assert result.exit_code == 1
    assert "config.yaml" in result.output
    profile = yaml.safe_load((respec_home / "profiles/a/profile.yaml").read_text())
    assert profile["skills"]["tdd"]["enabled"] is True
    assert (dirs["agents"] / "tdd").is_symlink()
