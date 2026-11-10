"""respec add / remove / enable / disable against temporary homes."""

import json
import shutil

import pytest
import yaml


@pytest.fixture
def dirs(isolated_homes):
    home = isolated_homes.home
    return {
        "claude-code": home / ".claude" / "skills",
        "agents": home / ".agents" / "skills",
        "oh-my-pi": home / ".omp" / "agent" / "skills",
    }


@pytest.fixture
def profiles_root(isolated_homes):
    return isolated_homes.respec_home / "profiles"


def read_yaml(profiles_root, profile):
    return yaml.safe_load((profiles_root / profile / "profile.yaml").read_text())


def write_yaml(profiles_root, profile, data):
    (profiles_root / profile / "profile.yaml").write_text(yaml.safe_dump(data))


def recorded(isolated_homes):
    state = json.loads((isolated_homes.respec_home / "state.json").read_text())
    return sorted(item["path"] for item in state["installed"])


def local_skill(tmp_path, name, body=None):
    folder = tmp_path / "src" / name
    (folder / "refs").mkdir(parents=True)
    (folder / "SKILL.md").write_text(body or f"# {name}\n")
    (folder / "refs" / "note.txt").write_text("note\n")
    return folder


def folder_source(folder):
    """The source record of a skill added from ``folder`` (digest aside)."""
    return {"folder": str(folder.resolve())}


def without_digest(entry):
    """A skill's profile.yaml entry without its source digest."""
    source = {k: v for k, v in entry.get("source", {}).items() if k != "digest"}
    return {**entry, "source": source} if "source" in entry else entry


def new_profile(run, name, *targets):
    args = ["profile", "new", name]
    for target in targets:
        args += ["--target", target]
    result = run(*args)
    assert result.exit_code == 0, result.output


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def test_add_copies_folder_into_named_profile_and_enables_it(
    run, tmp_path, profiles_root, dirs
):
    new_profile(run, "work", "claude-code")
    source = local_skill(tmp_path, "tdd")

    ok(run("add", str(source), "-p", "work"))

    copied = profiles_root / "work" / "skills" / "tdd"
    assert (copied / "SKILL.md").read_text() == "# tdd\n"
    assert (copied / "refs" / "note.txt").read_text() == "note\n"
    assert not copied.is_symlink()
    assert (source / "SKILL.md").exists()
    entry = read_yaml(profiles_root, "work")["skills"]["tdd"]
    assert without_digest(entry) == {"enabled": True, "source": folder_source(source)}
    # The profile is not active, so no target folder is touched.
    assert not dirs["claude-code"].exists()


def test_add_defaults_to_active_profile_and_links_immediately(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code", "agents")
    new_profile(run, "other", "claude-code")
    ok(run("use", "work"))

    ok(run("add", str(local_skill(tmp_path, "tdd"))))

    assert "tdd" in read_yaml(profiles_root, "work")["skills"]
    assert not read_yaml(profiles_root, "other").get("skills")
    for target in ("claude-code", "agents"):
        link = dirs[target] / "tdd"
        assert (link / "SKILL.md").read_text() == "# tdd\n"
    assert recorded(isolated_homes) == sorted(
        str(dirs[t] / "tdd") for t in ("claude-code", "agents")
    )


def test_add_without_profile_and_without_active_profile_fails(run, tmp_path):
    new_profile(run, "work", "claude-code")

    result = run("add", str(local_skill(tmp_path, "tdd")))

    assert result.exit_code == 1
    assert "-p" in result.output


def test_add_rejects_folder_without_skill_md(run, tmp_path, profiles_root):
    new_profile(run, "work", "claude-code")
    folder = tmp_path / "src" / "notaskill"
    folder.mkdir(parents=True)

    result = run("add", str(folder), "-p", "work")

    assert result.exit_code == 1
    assert "SKILL.md" in result.output
    assert not (profiles_root / "work" / "skills" / "notaskill").exists()
    assert not read_yaml(profiles_root, "work")["skills"]


def test_add_refuses_existing_item_and_leaves_it_untouched(
    run, tmp_path, profiles_root
):
    new_profile(run, "work", "claude-code")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    other = tmp_path / "other" / "tdd"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("# replacement\n")

    result = run("add", str(other), "-p", "work")

    assert result.exit_code == 1
    assert "already" in result.output
    skill_md = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    assert skill_md.read_text() == "# tdd\n"


def test_add_rolls_back_when_active_install_is_blocked(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code")
    ok(run("use", "work"))
    foreign = dirs["claude-code"] / "tdd"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# hand-installed\n")

    result = run("add", str(local_skill(tmp_path, "tdd")))

    assert result.exit_code == 1
    assert "not managed by respec" in result.output
    assert (foreign / "SKILL.md").read_text() == "# hand-installed\n"
    assert not (profiles_root / "work" / "skills" / "tdd").exists()
    assert not read_yaml(profiles_root, "work")["skills"]
    assert recorded(isolated_homes) == []


def test_disable_unlinks_from_active_targets_but_keeps_files_and_metadata(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code", "agents")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    ok(run("add", str(local_skill(tmp_path, "debug")), "-p", "work"))
    data = read_yaml(profiles_root, "work")
    data["skills"]["tdd"]["source"] = {"repo": "me/skills", "path": "tdd"}
    write_yaml(profiles_root, "work", data)
    ok(run("use", "work"))
    assert (dirs["claude-code"] / "tdd").exists()

    ok(run("disable", "tdd"))

    entry = read_yaml(profiles_root, "work")["skills"]["tdd"]
    assert entry == {"enabled": False, "source": {"repo": "me/skills", "path": "tdd"}}
    assert (profiles_root / "work" / "skills" / "tdd" / "SKILL.md").exists()
    for target in ("claude-code", "agents"):
        assert not (dirs[target] / "tdd").exists()
        assert not (dirs[target] / "tdd").is_symlink()
        assert (dirs[target] / "debug" / "SKILL.md").read_text() == "# debug\n"
    assert recorded(isolated_homes) == sorted(
        str(dirs[t] / "debug") for t in ("claude-code", "agents")
    )


def test_enable_links_into_active_targets(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    ok(run("disable", "tdd", "-p", "work"))
    ok(run("use", "work"))
    assert not (dirs["claude-code"] / "tdd").exists()

    ok(run("enable", "tdd"))

    assert read_yaml(profiles_root, "work")["skills"]["tdd"]["enabled"] is True
    assert (dirs["claude-code"] / "tdd" / "SKILL.md").read_text() == "# tdd\n"
    assert recorded(isolated_homes) == [str(dirs["claude-code"] / "tdd")]


def test_enable_and_disable_of_inactive_profile_leave_targets_alone(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code")
    new_profile(run, "home", "agents")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    ok(run("add", str(local_skill(tmp_path, "notes")), "-p", "home"))
    ok(run("use", "work"))

    ok(run("disable", "notes", "-p", "home"))

    assert read_yaml(profiles_root, "home")["skills"]["notes"]["enabled"] is False
    assert not dirs["agents"].exists()
    assert (dirs["claude-code"] / "tdd").exists()
    assert recorded(isolated_homes) == [str(dirs["claude-code"] / "tdd")]


def test_remove_deletes_item_and_unlinks_it_from_active_targets(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    ok(run("add", str(local_skill(tmp_path, "debug")), "-p", "work"))
    ok(run("use", "work"))

    ok(run("remove", "tdd"))

    assert "tdd" not in read_yaml(profiles_root, "work")["skills"]
    assert not (profiles_root / "work" / "skills" / "tdd").exists()
    assert not (dirs["claude-code"] / "tdd").is_symlink()
    assert not (dirs["claude-code"] / "tdd").exists()
    assert (dirs["claude-code"] / "debug").exists()
    assert recorded(isolated_homes) == [str(dirs["claude-code"] / "debug")]


def test_enable_rolls_back_when_active_install_is_blocked(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    ok(run("disable", "tdd", "-p", "work"))
    ok(run("use", "work"))
    foreign = dirs["claude-code"] / "tdd"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("# hand-installed\n")

    result = run("enable", "tdd")

    assert result.exit_code == 1
    assert "not managed by respec" in result.output
    assert read_yaml(profiles_root, "work")["skills"]["tdd"]["enabled"] is False
    assert (foreign / "SKILL.md").read_text() == "# hand-installed\n"
    assert recorded(isolated_homes) == []


def test_remove_keeps_item_when_active_refresh_is_blocked(
    run, tmp_path, profiles_root, dirs, isolated_homes
):
    new_profile(run, "work", "claude-code")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    ok(run("add", str(local_skill(tmp_path, "debug")), "-p", "work"))
    ok(run("use", "work"))
    # Break another item so the refresh preflight refuses to run.
    shutil.rmtree(profiles_root / "work" / "skills" / "debug")

    result = run("remove", "tdd")

    assert result.exit_code == 1
    assert "debug" in result.output
    assert set(read_yaml(profiles_root, "work")["skills"]) == {"tdd", "debug"}
    assert (profiles_root / "work" / "skills" / "tdd" / "SKILL.md").exists()
    assert (dirs["claude-code"] / "tdd" / "SKILL.md").exists()


@pytest.mark.parametrize("command", ["remove", "enable", "disable"])
def test_unknown_item_fails_and_changes_nothing(run, tmp_path, profiles_root, command):
    new_profile(run, "work", "claude-code")
    ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work"))
    before = read_yaml(profiles_root, "work")

    result = run(command, "nope", "-p", "work")

    assert result.exit_code == 1
    assert "nope" in result.output
    assert read_yaml(profiles_root, "work") == before


def test_commands_support_json(run, tmp_path, profiles_root, dirs):
    new_profile(run, "work", "claude-code")
    ok(run("use", "work"))
    source = local_skill(tmp_path, "tdd")

    added = json.loads(ok(run("add", str(source), "--json")).output)
    disabled = json.loads(ok(run("disable", "tdd", "--json")).output)
    enabled = json.loads(ok(run("enable", "tdd", "--json")).output)
    removed = json.loads(ok(run("remove", "tdd", "--json")).output)

    link = str(dirs["claude-code"] / "tdd")
    assert added == {
        "profile": "work",
        "skill": "tdd",
        "action": "add",
        "enabled": True,
        "path": str(profiles_root / "work" / "skills" / "tdd"),
        "active": True,
        "linked": [link],
        "unlinked": [],
        "source": {
            "folder": str(source.resolve()),
            "digest": added["source"]["digest"],
        },
        "unresolved": [],
        "warnings": [],
    }
    assert added["source"]["digest"].startswith("sha256:")
    assert disabled["action"] == "disable"
    assert disabled["enabled"] is False
    assert disabled["linked"] == [] and disabled["unlinked"] == [link]
    assert enabled["enabled"] is True
    assert enabled["linked"] == [link] and enabled["unlinked"] == []
    assert removed["action"] == "remove"
    assert removed["linked"] == [] and removed["unlinked"] == [link]


def test_json_reports_no_link_changes_for_inactive_profile(run, tmp_path):
    new_profile(run, "work", "claude-code")

    added = json.loads(
        ok(run("add", str(local_skill(tmp_path, "tdd")), "-p", "work", "--json")).output
    )

    assert added["active"] is False
    assert added["linked"] == [] and added["unlinked"] == []


def test_add_with_a_home_that_cannot_be_found_fails_with_an_error(run):
    new_profile(run, "work", "claude-code")

    result = run("add", "~nosuchuser_zz/skill", "-p", "work")

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "~nosuchuser_zz" in result.output
