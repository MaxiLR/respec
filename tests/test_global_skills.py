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
    unresolved = json.loads(result.stdout)["unresolved"]
    assert [entry["name"] for entry in unresolved] == ["mine"]


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


# --- reserved names: no path adds a shipped or global skill to a profile ----


def replace_with_folder(path, text="edited\n"):
    path.unlink()
    path.mkdir()
    (path / "SKILL.md").write_text(text)


def profile_skills(respec_home, name):
    data = yaml.safe_load(
        (respec_home / "profiles" / name / "profile.yaml").read_text()
    )
    return data.get("skills") or {}


def is_shipped_link(path, respec_home):
    return (
        path.is_symlink()
        and path.resolve() == (respec_home / "shipped" / path.name).resolve()
    )


def test_adopt_add_of_a_replaced_shipped_skill_is_refused_and_remove_relinks_it(
    run, respec_home, dirs
):
    # The review's reproduction: p2 targets oh-my-pi only.
    make_profile(respec_home, "p2", ["oh-my-pi"], ["tdd"])
    assert run("use", "p2").exit_code == 0
    entry = dirs["oh-my-pi"] / "profile-maker"
    replace_with_folder(entry)

    refused = run("adopt", "--add", "profile-maker")

    assert refused.exit_code == 1
    assert "'profile-maker'" in refused.output and "ships" in refused.output
    assert "--remove" in refused.output
    assert (entry / "SKILL.md").read_text() == "edited\n"
    assert "profile-maker" not in profile_skills(respec_home, "p2")

    removed = run("adopt", "--remove", "profile-maker", "--json")

    assert removed.exit_code == 0, removed.output
    data = json.loads(removed.stdout)
    assert open(os.path.join(data["resolved"][0]["backup"], "SKILL.md")).read() == (
        "edited\n"
    )
    assert is_shipped_link(entry, respec_home)
    assert str(entry) in data["linked"]
    assert run("disable", "tdd").exit_code == 0
    assert run("use", "p2").exit_code == 0


def test_adopt_add_of_a_shipped_skill_outside_the_profile_targets_is_refused(
    run, respec_home, dirs
):
    make_profile(respec_home, "pi", ["oh-my-pi"], ["tdd"])
    assert run("use", "pi").exit_code == 0
    replace_with_folder(dirs["agents"] / "respec")

    assert run("adopt", "--add", "respec").exit_code == 1
    assert (dirs["agents"] / "respec" / "SKILL.md").read_text() == "edited\n"

    assert run("adopt", "--remove", "respec").exit_code == 0
    assert is_shipped_link(dirs["agents"] / "respec", respec_home)
    assert run("use", "pi").exit_code == 0


def test_adopt_all_add_is_refused_before_any_entry_changes(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0
    (dirs["agents"] / "aaa").mkdir()
    (dirs["agents"] / "aaa" / "SKILL.md").write_text("aaa\n")
    replace_with_folder(dirs["agents"] / "respec")

    result = run("adopt", "--all", "add")

    assert result.exit_code == 1
    assert (dirs["agents"] / "aaa" / "SKILL.md").read_text() == "aaa\n"
    assert set(profile_skills(respec_home, "a")) == {"tdd"}


def test_use_unknown_add_of_a_reserved_entry_is_refused(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_profile(respec_home, "b", ["agents"], ["lint"])
    assert run("use", "a").exit_code == 0
    replace_with_folder(dirs["agents"] / "respec")

    result = run("use", "b", "--unknown", "add")

    assert result.exit_code == 1
    assert "'respec'" in result.output
    assert (dirs["agents"] / "respec" / "SKILL.md").read_text() == "edited\n"
    assert set(profile_skills(respec_home, "a")) == {"tdd"}
    assert json.loads(run("status", "--json").stdout)["active_profile"] == "a"

    assert run("use", "b", "--unknown", "remove").exit_code == 0
    assert is_shipped_link(dirs["agents"] / "respec", respec_home)


def test_adopt_prompt_offers_only_remove_for_a_reserved_entry(
    run, respec_home, dirs, monkeypatch
):
    from respec import cli

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0
    replace_with_folder(dirs["agents"] / "respec")

    result = run("adopt", input="add\nremove\n")

    assert result.exit_code == 0, result.output
    assert "please answer: remove" in result.output
    assert is_shipped_link(dirs["agents"] / "respec", respec_home)
    assert "respec" not in profile_skills(respec_home, "a")


def test_resolve_api_refuses_add_of_a_reserved_entry_before_changes(
    respec_home, dirs, run
):
    from respec import adopt
    from respec.errors import RespecError

    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0
    (dirs["agents"] / "aaa").mkdir()
    (dirs["agents"] / "aaa" / "SKILL.md").write_text("aaa\n")
    replace_with_folder(dirs["agents"] / "respec")
    entries = adopt.unresolved(respec_home)
    assert [e.name for e in entries] == ["aaa", "respec"]

    with pytest.raises(RespecError, match="ships"):
        adopt.resolve(respec_home, entries, lambda entry: "add", "a")

    assert (dirs["agents"] / "aaa").is_dir()
    assert set(profile_skills(respec_home, "a")) == {"tdd"}


@pytest.mark.parametrize("reserved", ["respec", "notes"])
def test_local_add_of_a_reserved_name_to_an_inactive_profile_is_refused(
    run, respec_home, tmp_path, reserved
):
    make_profile(respec_home, "b", ["agents"], [])
    make_global(respec_home, "notes")
    source = tmp_path / "src" / reserved
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("mine\n")

    result = run("add", str(source), "-p", "b")

    assert result.exit_code == 1
    assert f"'{reserved}'" in result.output
    assert profile_skills(respec_home, "b") == {}
    assert not (respec_home / "profiles" / "b" / "skills" / reserved).exists()


# --- restore removes the parent folders respec created ----------------------


def test_restore_removes_parent_folders_respec_created(run, respec_home, dirs):
    home = respec_home.parent / "home"
    dirs["claude-code"].mkdir(parents=True)
    (dirs["claude-code"] / "mine").mkdir()
    (home / ".omp").mkdir()  # existed before respec; must stay
    make_profile(respec_home, "pi", ["oh-my-pi"], ["tdd"])
    assert run("use", "pi").exit_code == 0

    assert run("restore").exit_code == 0

    assert names(dirs["claude-code"]) == ["mine"]
    assert not (home / ".agents").exists()
    assert not (home / ".omp" / "agent").exists()
    assert (home / ".omp").is_dir()


def test_restore_keeps_created_parents_that_gained_other_content(
    run, respec_home, dirs
):
    home = respec_home.parent / "home"
    make_profile(respec_home, "pi", ["oh-my-pi"], ["tdd"])
    assert run("use", "pi").exit_code == 0
    (home / ".omp" / "agent" / "config.yml").write_text("installed later\n")

    assert run("restore").exit_code == 0

    assert (home / ".omp" / "agent" / "config.yml").read_text() == "installed later\n"
    assert not dirs["oh-my-pi"].exists()
    assert not (home / ".agents").exists()


def test_restore_never_removes_folders_that_existed_before_takeover(
    run, respec_home, dirs
):
    dirs["agents"].mkdir(parents=True)  # empty, but the user's
    make_profile(respec_home, "pi", ["oh-my-pi"], ["tdd"])
    assert run("use", "pi").exit_code == 0

    assert run("restore").exit_code == 0

    assert dirs["agents"].is_dir() and names(dirs["agents"]) == []


# Status marks shipped and global skills, as the TUI does.


def test_status_json_says_where_each_installed_skill_comes_from(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_global(respec_home, "notes")
    assert run("use", "a").exit_code == 0

    report = json.loads(run("status", "--json").stdout)

    folders = {folder["target"]: folder for folder in report["folders"]}
    origins = {s["name"]: s["origin"] for s in folders["agents"]["skills"]}
    assert origins == {
        "notes": "global",
        "profile-maker": "shipped",
        "respec": "shipped",
        "tdd": "profile",
    }


def test_status_text_marks_shipped_and_global_skills(run, respec_home, dirs):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_global(respec_home, "notes")
    assert run("use", "a").exit_code == 0

    lines = run("status").stdout.splitlines()

    agents = lines.index(next(line for line in lines if line.startswith("agents")))
    block = lines[agents + 1 : agents + 5]
    by_name = {line.split()[0]: line for line in block}
    assert by_name["respec"].rstrip().endswith("shipped")
    assert by_name["notes"].rstrip().endswith("global")
    assert by_name["tdd"].split(None, 2) == [
        "tdd",
        "symlink",
        "added locally, original",
    ]


# A user's own entry with a reserved name at the very first takeover.


def test_first_takeover_says_an_entry_clashes_with_a_shipped_skill(
    run, respec_home, dirs
):
    make_profile(respec_home, "cc", ["claude-code"], ["tdd"])
    own = dirs["agents"] / "respec"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("# my own respec notes\n")

    result = run("use", "cc")

    assert result.exit_code == 1
    assert str(own) in result.output
    assert "respec ships a skill named 'respec'" in result.output
    assert (own / "SKILL.md").read_text() == "# my own respec notes\n"


def test_first_takeover_says_an_entry_clashes_with_a_global_skill(
    run, respec_home, dirs
):
    make_profile(respec_home, "cc", ["claude-code"], ["tdd"])
    make_global(respec_home, "notes")
    own = dirs["claude-code"] / "notes"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("# mine\n")

    result = run("use", "cc")

    assert result.exit_code == 1
    assert "'notes' is a global skill listed in" in result.output
    assert "config.yaml" in result.output


def test_status_judges_a_link_by_what_it_points_into_not_its_name(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    assert run("use", "a").exit_code == 0
    # A global skill of the same name is listed by hand afterwards.
    make_global(respec_home, "tdd")

    report = json.loads(run("status", "--json").stdout)

    folders = {folder["target"]: folder for folder in report["folders"]}
    origins = {s["name"]: s["origin"] for s in folders["agents"]["skills"]}
    assert origins["tdd"] == "profile"
    assert origins["respec"] == "shipped"
