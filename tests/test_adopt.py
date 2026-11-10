"""Unknown entries in owned folders: detection, the switch prompt and adopt."""

import json
import os
import shutil

import pytest
import yaml

from respec import cli


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


def drop_skill(folder, name, body="foreign\n"):
    """What another installer does: put a skill folder into a target folder."""
    (folder / name / "refs").mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(body)
    (folder / name / "refs" / "note.md").write_text("note\n")
    return folder / name


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def status_json(run):
    return json.loads(ok(run("status", "--json")).stdout)


def folder_report(report, target):
    return next(f for f in report["folders"] if f["target"] == target)


def profile_skills(respec_home, name):
    data = yaml.safe_load(
        (respec_home / "profiles" / name / "profile.yaml").read_text()
    )
    return data.get("skills") or {}


def active_profile(respec_home):
    return json.loads((respec_home / "state.json").read_text())["active_profile"]


def backup_files(respec_home):
    """Every file below backups/<run>/, as path inside its run -> content."""
    root = respec_home / "backups"
    found = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            run_dir, *inside = path.relative_to(root).parts
            found["/".join(inside)] = path.read_text()
    return found


@pytest.fixture
def activated(run, respec_home, dirs):
    """Profile a (claude-code) is active; profile b (claude-code) waits."""
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    make_profile(respec_home, "b", ["claude-code"], ["lint"])
    ok(run("use", "a"))


def deactivate(respec_home):
    """Leave the folders owned but no profile active (as after a failed switch)."""
    path = respec_home / "state.json"
    state = json.loads(path.read_text())
    state["active_profile"] = None
    path.write_text(json.dumps(state))


# --- detection -------------------------------------------------------------


def test_status_json_reports_foreign_entry_dropped_after_activation(
    run, activated, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    folder = folder_report(status_json(run), "claude-code")

    assert [item["name"] for item in folder["skills"]] == ["tdd"]
    assert folder["unknown"] == [
        {
            "name": "foreign",
            "path": str(foreign),
            "kind": "folder",
            "targets": ["claude-code"],
            "replaced": False,
        }
    ]
    assert "unmanaged" not in folder


def test_status_human_lists_unknown_entries_with_a_hint(run, activated, dirs):
    drop_skill(dirs["claude-code"], "foreign")

    out = ok(run("status")).stdout

    line = next(line for line in out.splitlines() if "foreign" in line)
    assert "unknown" in line
    assert "respec adopt" in out
    assert "keep" not in out


def test_hidden_files_are_not_reported(run, activated, dirs):
    (dirs["claude-code"] / ".DS_Store").write_text("")

    assert folder_report(status_json(run), "claude-code")["unknown"] == []


def test_status_shows_alias_for_targets_sharing_one_real_folder(run, respec_home, dirs):
    dirs["agents"].mkdir(parents=True)
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    make_profile(respec_home, "a", ["claude-code", "agents"], ["tdd"])
    ok(run("use", "a"))
    drop_skill(dirs["agents"], "foreign")

    report = status_json(run)

    claude = folder_report(report, "claude-code")
    agents = folder_report(report, "agents")
    assert claude["same_as"] is None
    assert agents["same_as"] == "claude-code"
    assert [u["name"] for u in claude["unknown"]] == ["foreign"]
    assert claude["unknown"][0]["targets"] == ["claude-code", "agents"]
    assert agents["unknown"] == []
    out = ok(run("status")).stdout
    assert "same folder as claude-code" in out


def test_entries_once_kept_unmanaged_are_unknown_again_and_the_record_is_pruned(
    run, activated, respec_home, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")
    path = respec_home / "state.json"
    state = json.loads(path.read_text())
    state["unmanaged"] = [str(foreign), str(dirs["claude-code"] / "gone")]
    path.write_text(json.dumps(state))

    folder = folder_report(status_json(run), "claude-code")
    assert [u["path"] for u in folder["unknown"]] == [str(foreign)]

    ok(run("adopt", "--remove", "foreign"))

    assert "unmanaged" not in json.loads(path.read_text())
    assert not os.path.lexists(foreign)
    assert "foreign\n" in backup_files(respec_home).values()


def test_dot_ds_store_inside_an_installed_copy_does_not_mark_it_edited(
    run, activated_as_copy, dirs
):
    (activated_as_copy / ".DS_Store").write_bytes(b"\0\1finder")

    folder = folder_report(status_json(run), "claude-code")

    assert [(i["name"], i["mode"]) for i in folder["skills"]] == [("tdd", "copy")]
    assert folder["unknown"] == []


# --- exactly two choices: add or remove ----------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("adopt", "--keep", "foreign"),
        ("adopt", "--backup", "foreign"),
        ("adopt", "--all", "keep"),
        ("use", "b", "--unknown", "keep"),
        ("use", "b", "--unknown", "backup"),
        ("restore", "--unknown", "keep"),
    ],
)
def test_keep_and_other_old_choices_are_rejected(run, activated, dirs, args):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = run(*args)

    assert result.exit_code == 2
    assert (foreign / "SKILL.md").read_text() == "foreign\n"


@pytest.mark.parametrize("command", [("adopt",), ("use",), ("restore",)])
def test_help_offers_only_add_and_remove(run, command):
    out = run(*command, "--help").output

    assert "add" in out and "remove" in out
    assert "keep" not in out.lower() and "unmanaged" not in out.lower()


# --- only entries in the way block ----------------------------------------


def test_unknown_entry_elsewhere_warns_but_does_not_block_a_switch(
    run, activated, respec_home, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = ok(run("use", "b"))

    assert active_profile(respec_home) == "b"
    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == [
        "foreign",
        "lint",
    ]
    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    assert str(foreign) in result.stderr and "respec adopt" in result.stderr
    assert "warning" in result.stderr.lower()
    assert str(foreign) not in result.stdout


def test_switch_json_lists_unknown_entries_as_warnings(run, activated, dirs):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    data = json.loads(ok(run("use", "b", "--json")).stdout)

    [warning] = data["warnings"]
    assert warning["path"] == str(foreign)
    assert warning["replaced"] is False
    assert "respec adopt" in warning["message"]


@pytest.mark.parametrize(
    "command",
    [
        ("disable", "tdd"),
        ("enable", "tdd"),
        ("layer", "use", "design-principles", "tdd"),
        ("layer", "disable", "design-principles"),
        ("layer", "off", "design-principles"),
    ],
)
def test_unknown_entry_elsewhere_warns_but_does_not_block_profile_edits(
    run, activated, respec_home, dirs, command
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = ok(run(*command))

    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    assert str(foreign) in result.stderr and "respec adopt" in result.stderr
    assert "cannot" not in result.output and "--unknown" not in result.output
    data = json.loads(ok(run(*command, "--json")).stdout)
    assert [w["path"] for w in data["warnings"]] == [str(foreign)]


def test_add_and_remove_of_a_skill_warn_but_are_not_blocked(
    run, activated, respec_home, dirs, tmp_path
):
    foreign = drop_skill(dirs["claude-code"], "foreign")
    source = drop_skill(tmp_path / "src", "extra", "extra\n")

    added = ok(run("add", str(source)))
    removed = ok(run("remove", "extra"))

    for result in (added, removed):
        assert str(foreign) in result.stderr
    assert "extra" not in profile_skills(respec_home, "a")


def test_no_warning_without_unknown_entries(run, activated):
    result = ok(run("use", "b"))

    assert result.stderr == ""
    assert json.loads(ok(run("use", "a", "--json")).stdout)["warnings"] == []


def test_entry_at_an_install_path_blocks_the_switch_and_changes_nothing(
    run, activated, respec_home, dirs
):
    in_the_way = drop_skill(dirs["claude-code"], "lint")

    result = run("use", "b")

    assert result.exit_code == 1
    assert str(in_the_way) in result.output
    assert "--unknown" in result.output and "respec adopt" in result.output
    assert "keep" not in result.output
    assert (in_the_way / "SKILL.md").read_text() == "foreign\n"
    assert (dirs["claude-code"] / "tdd").is_symlink()
    assert active_profile(respec_home) == "a"
    assert not (respec_home / "backups").exists()


def test_switch_policy_remove_backs_up_the_entry_in_the_way_then_switches(
    run, activated, respec_home, dirs
):
    in_the_way = drop_skill(dirs["claude-code"], "lint")

    ok(run("use", "b", "--unknown", "remove"))

    assert in_the_way.is_symlink()
    assert (in_the_way / "SKILL.md").read_text() == "# lint from b\n"
    assert backup_files(respec_home) == {
        "claude-code/lint/SKILL.md": "foreign\n",
        "claude-code/lint/refs/note.md": "note\n",
    }
    assert active_profile(respec_home) == "b"


def test_switch_policy_add_goes_to_the_profile_being_switched_away_from(
    run, activated, respec_home, dirs
):
    drop_skill(dirs["claude-code"], "lint")

    ok(run("use", "b", "--unknown", "add"))

    copied = respec_home / "profiles" / "a" / "skills" / "lint"
    assert (copied / "SKILL.md").read_text() == "foreign\n"
    assert (copied / "refs" / "note.md").read_text() == "note\n"
    assert profile_skills(respec_home, "a")["lint"] == {"enabled": True}
    assert (
        respec_home / "profiles" / "b" / "skills" / "lint" / "SKILL.md"
    ).read_text() == ("# lint from b\n")
    link = dirs["claude-code"] / "lint"
    assert link.is_symlink()
    assert (link / "SKILL.md").read_text() == "# lint from b\n"
    assert active_profile(respec_home) == "b"


def test_switch_policy_add_without_an_active_profile_fails_before_any_change(
    run, activated, respec_home, dirs
):
    deactivate(respec_home)
    in_the_way = drop_skill(dirs["claude-code"], "lint")

    result = run("use", "b", "--unknown", "add")

    assert result.exit_code == 1
    assert "no profile is active" in result.output and "remove" in result.output
    assert (in_the_way / "SKILL.md").read_text() == "foreign\n"
    assert not (respec_home / "backups").exists()


def test_interactive_switch_prompts_once_per_entry_in_the_way(
    run, activated, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    make_profile(respec_home, "c", ["claude-code"], ["first", "second"])
    first = drop_skill(dirs["claude-code"], "first", "first\n")
    drop_skill(dirs["claude-code"], "second", "second\n")
    elsewhere = drop_skill(dirs["claude-code"], "elsewhere")

    result = run("use", "c", input="remove\nadd\n")

    ok(result)
    assert result.stdout.count("add to profile 'a'") == 2
    assert "keep" not in result.stdout
    assert first.is_symlink()
    assert "first\n" in backup_files(respec_home).values()
    added = respec_home / "profiles" / "a" / "skills" / "second" / "SKILL.md"
    assert added.read_text() == "second\n"
    assert (elsewhere / "SKILL.md").read_text() == "foreign\n"
    assert str(elsewhere) in result.stderr
    assert active_profile(respec_home) == "c"


def test_interactive_prompt_without_an_active_profile_offers_only_remove(
    run, activated, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    deactivate(respec_home)
    in_the_way = drop_skill(dirs["claude-code"], "lint")

    result = run("use", "b", input="add\nremove\n")

    ok(result)
    assert "add to profile" not in result.stdout
    assert "please answer: remove" in result.stdout
    assert in_the_way.is_symlink()
    assert "foreign\n" in backup_files(respec_home).values()


def test_add_choice_on_a_file_fails_and_keeps_the_file(
    run, activated, respec_home, dirs
):
    loose = dirs["claude-code"] / "lint"
    loose.write_text("loose\n")

    result = run("use", "b", "--unknown", "add")

    assert result.exit_code == 1
    assert "not a folder" in result.output
    assert loose.read_text() == "loose\n"
    assert active_profile(respec_home) == "a"


# --- first takeover ----------------------------------------------------------


def test_first_takeover_without_terminal_backs_up_and_warns(run, respec_home, dirs):
    old = drop_skill(dirs["claude-code"], "old", "old\n")
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])

    result = ok(run("use", "a"))

    assert (old / "SKILL.md").read_text() == "old\n"
    assert backup_files(respec_home)["claude-code/old/SKILL.md"] == "old\n"
    assert str(old) in result.stderr and "respec adopt" in result.stderr


def test_first_takeover_on_a_terminal_asks_about_existing_entries_right_away(
    run, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    old = drop_skill(dirs["claude-code"], "old", "old\n")
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])

    result = run("use", "a", input="remove\n")

    ok(result)
    assert str(old) in result.stdout
    assert "add to profile 'a'" in result.stdout  # the profile being activated
    assert not os.path.lexists(old)
    runs = sorted((respec_home / "backups").iterdir())
    assert len(runs) == 2  # the takeover backup and the removed entry
    assert (runs[0] / "claude-code" / "old" / "SKILL.md").read_text() == "old\n"
    assert result.stderr == ""
    assert active_profile(respec_home) == "a"


def test_first_takeover_of_a_new_target_adds_to_the_profile_being_left(
    run, activated, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    make_profile(respec_home, "c", ["claude-code", "agents"], ["lint"])
    drop_skill(dirs["agents"], "old", "old\n")

    ok(run("use", "c", input="add\n"))

    copied = respec_home / "profiles" / "a" / "skills" / "old" / "SKILL.md"
    assert copied.read_text() == "old\n"
    assert not os.path.lexists(dirs["agents"] / "old")
    assert active_profile(respec_home) == "c"


# --- a recorded link replaced by something else ---------------------------


def test_replaced_link_is_reported_as_unknown(run, activated, dirs):
    link = dirs["claude-code"] / "tdd"
    link.unlink()
    drop_skill(dirs["claude-code"], "tdd", "hand-made\n")

    folder = folder_report(status_json(run), "claude-code")

    assert folder["skills"] == []
    assert [(u["name"], u["replaced"]) for u in folder["unknown"]] == [("tdd", True)]


def test_replaced_link_blocks_switch_cleanly_then_remove_resolves_it(
    run, activated, respec_home, dirs
):
    link = dirs["claude-code"] / "tdd"
    link.unlink()
    drop_skill(dirs["claude-code"], "tdd", "hand-made\n")

    blocked = run("use", "b")

    assert blocked.exit_code == 1
    assert "not managed by respec" in blocked.output
    assert active_profile(respec_home) == "a"
    assert (link / "SKILL.md").read_text() == "hand-made\n"

    ok(run("use", "b", "--unknown", "remove"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]
    assert "hand-made\n" in backup_files(respec_home).values()


def test_item_change_blocked_by_a_replaced_link_says_so_accurately(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["claude-code"], ["tdd", "lint"])
    ok(run("use", "a"))
    (dirs["claude-code"] / "tdd").unlink()
    drop_skill(dirs["claude-code"], "tdd", "hand-made\n")

    result = run("disable", "lint")

    assert result.exit_code == 1
    assert str(dirs["claude-code"] / "tdd") in result.output
    assert "respec adopt" in result.output and "left unchanged" in result.output
    assert "cannot switch" not in result.output and "--unknown" not in result.output
    assert profile_skills(respec_home, "a")["lint"] == {"enabled": True}
    assert active_profile(respec_home) == "a"
    assert (dirs["claude-code"] / "lint").is_symlink()


def test_adding_a_replaced_link_back_overwrites_the_profile_copy(
    run, activated, respec_home, dirs
):
    link = dirs["claude-code"] / "tdd"
    link.unlink()
    drop_skill(dirs["claude-code"], "tdd", "hand-made\n")

    ok(run("adopt", "--add", "tdd"))

    profile_copy = respec_home / "profiles" / "a" / "skills" / "tdd"
    assert (profile_copy / "SKILL.md").read_text() == "hand-made\n"
    assert (profile_copy / "refs" / "note.md").read_text() == "note\n"
    assert profile_skills(respec_home, "a")["tdd"] == {"enabled": True}
    assert link.is_symlink() and (link / "SKILL.md").read_text() == "hand-made\n"
    assert folder_report(status_json(run), "claude-code")["unknown"] == []


# --- a recorded copy replaced or edited by something else -----------------


@pytest.fixture
def activated_as_copy(run, respec_home, dirs, monkeypatch):
    """Like ``activated``, but symlinks fail so tdd is installed as a copy."""
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    make_profile(respec_home, "b", ["claude-code"], ["lint"])

    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    with monkeypatch.context() as patch:
        patch.setattr(os, "symlink", refuse)
        ok(run("use", "a"))
    copy = dirs["claude-code"] / "tdd"
    assert copy.is_dir() and not copy.is_symlink()
    return copy


def test_replaced_copy_is_reported_as_unknown_not_as_managed(
    run, activated_as_copy, dirs
):
    shutil.rmtree(activated_as_copy)
    drop_skill(dirs["claude-code"], "tdd", "FOREIGN TOOL CONTENT\n")

    folder = folder_report(status_json(run), "claude-code")

    assert folder["skills"] == []
    assert [(u["name"], u["replaced"]) for u in folder["unknown"]] == [("tdd", True)]


def test_replaced_copy_blocks_switch_and_is_not_deleted(
    run, activated_as_copy, respec_home, dirs
):
    shutil.rmtree(activated_as_copy)
    drop_skill(dirs["claude-code"], "tdd", "FOREIGN TOOL CONTENT\n")

    blocked = run("use", "b")

    assert blocked.exit_code == 1
    assert str(activated_as_copy) in blocked.output
    assert (activated_as_copy / "SKILL.md").read_text() == "FOREIGN TOOL CONTENT\n"
    assert active_profile(respec_home) == "a"


def test_edited_copy_is_backed_up_before_the_switch_removes_it(
    run, activated_as_copy, respec_home, dirs
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    ok(run("use", "b", "--unknown", "remove"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]
    assert "edited by hand\n" in backup_files(respec_home).values()


def test_adding_an_edited_copy_back_overwrites_the_active_profile_copy(
    run, activated_as_copy, respec_home, dirs
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    data = json.loads(ok(run("adopt", "--add", "tdd", "--json")).stdout)

    [resolved] = data["resolved"]
    assert resolved["choice"] == "add" and resolved["profile"] == "a"
    profile_copy = respec_home / "profiles" / "a" / "skills" / "tdd" / "SKILL.md"
    assert profile_copy.read_text() == "edited by hand\n"
    assert profile_skills(respec_home, "a")["tdd"] == {"enabled": True}
    assert (dirs["claude-code"] / "tdd" / "SKILL.md").read_text() == "edited by hand\n"
    folder = folder_report(status_json(run), "claude-code")
    assert [i["name"] for i in folder["skills"]] == ["tdd"]
    assert folder["unknown"] == []


def test_switch_add_of_an_edited_copy_keeps_the_edit_in_the_profile_left(
    run, activated_as_copy, respec_home, dirs
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    ok(run("use", "b", "--unknown", "add"))

    profile_copy = respec_home / "profiles" / "a" / "skills" / "tdd" / "SKILL.md"
    assert profile_copy.read_text() == "edited by hand\n"
    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]
    assert active_profile(respec_home) == "b"


def test_unmodified_copy_stays_managed_and_is_replaced_on_switch(
    run, activated_as_copy, dirs
):
    folder = folder_report(status_json(run), "claude-code")
    assert [(i["name"], i["mode"]) for i in folder["skills"]] == [("tdd", "copy")]
    assert folder["unknown"] == []

    ok(run("use", "b"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]


# --- respec adopt -----------------------------------------------------------


def test_adopt_json_without_choices_lists_entries_and_changes_nothing(
    run, activated, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    data = json.loads(ok(run("adopt", "--json")).stdout)

    assert data["resolved"] == []
    assert [entry["path"] for entry in data["unknown"]] == [str(foreign)]
    assert (foreign / "SKILL.md").read_text() == "foreign\n"


def test_adopt_remove_flag_backs_up_and_removes_only_that_entry(
    run, activated, respec_home, dirs
):
    drop_skill(dirs["claude-code"], "one", "one\n")
    two = drop_skill(dirs["claude-code"], "two", "two\n")

    data = json.loads(ok(run("adopt", "--remove", "one", "--json")).stdout)

    [resolved] = data["resolved"]
    assert resolved["name"] == "one" and resolved["choice"] == "remove"
    assert open(os.path.join(resolved["backup"], "SKILL.md")).read() == "one\n"
    assert not os.path.lexists(dirs["claude-code"] / "one")
    assert [entry["path"] for entry in data["unknown"]] == [str(two)]


def test_adopt_add_into_active_profile_links_it_at_once(
    run, activated, respec_home, dirs
):
    drop_skill(dirs["claude-code"], "foreign")

    ok(run("adopt", "--add", "foreign"))

    assert profile_skills(respec_home, "a")["foreign"] == {"enabled": True}
    link = dirs["claude-code"] / "foreign"
    assert link.is_symlink()
    assert (link / "SKILL.md").read_text() == "foreign\n"
    assert active_profile(respec_home) == "a"
    assert folder_report(status_json(run), "claude-code")["unknown"] == []


def test_adopt_add_of_a_symlinked_entry_keeps_the_entry_name(
    run, activated, respec_home, dirs, tmp_path
):
    elsewhere = drop_skill(tmp_path / "checkout", "upstream-name")
    (dirs["claude-code"] / "my-name").symlink_to(elsewhere, target_is_directory=True)

    ok(run("adopt", "--add", "my-name"))

    assert "my-name" in profile_skills(respec_home, "a")
    copied = respec_home / "profiles" / "a" / "skills" / "my-name"
    assert (copied / "SKILL.md").read_text() == "foreign\n"
    assert not copied.is_symlink()
    assert (elsewhere / "SKILL.md").read_text() == "foreign\n"
    assert (dirs["claude-code"] / "my-name").resolve() == copied.resolve()


def test_adopt_add_without_an_active_profile_fails_and_remove_still_works(
    run, activated, respec_home, dirs
):
    deactivate(respec_home)
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = run("adopt", "--add", "foreign")

    assert result.exit_code == 1
    assert "no active profile" in result.output and "remove" in result.output
    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    ok(run("adopt", "--remove", "foreign"))
    assert not os.path.lexists(foreign)


def test_adopt_all_applies_one_choice_to_every_entry(run, activated, respec_home, dirs):
    drop_skill(dirs["claude-code"], "one", "one\n")
    drop_skill(dirs["claude-code"], "two", "two\n")

    ok(run("adopt", "--all", "remove"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["tdd"]
    assert {"one\n", "two\n"} <= set(backup_files(respec_home).values())


def test_adopt_unknown_selector_fails_before_changing_anything(run, activated, dirs):
    one = drop_skill(dirs["claude-code"], "one")

    result = run("adopt", "--remove", "one", "--remove", "missing")

    assert result.exit_code == 1
    assert "missing" in result.output
    assert (one / "SKILL.md").exists()


def test_adopt_interactive_prompts_for_each_entry(
    run, activated, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = ok(run("adopt", input="keep\nremove\n"))

    assert "please answer one of: add, remove" in result.stdout
    assert not os.path.lexists(foreign)
    assert "foreign\n" in backup_files(respec_home).values()


def test_status_lists_shared_items_once_whatever_the_profile_target_order(
    run, respec_home, dirs
):
    dirs["agents"].mkdir(parents=True)
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    make_profile(respec_home, "a", ["agents", "claude-code"], ["tdd"])
    ok(run("use", "a"))

    report = status_json(run)

    assert [i["name"] for i in folder_report(report, "claude-code")["skills"]] == [
        "tdd"
    ]
    assert folder_report(report, "agents")["skills"] == []
    assert folder_report(report, "agents")["same_as"] == "claude-code"


# --- the core API the TUI and later a sync action share --------------------


def test_unresolved_returns_unknown_entries_and_edited_copies(
    run, activated_as_copy, respec_home, dirs
):
    from respec import adopt

    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")
    foreign = drop_skill(dirs["claude-code"], "foreign")

    found = adopt.unresolved(respec_home)

    assert sorted((e.path, e.replaced) for e in found) == [
        (str(foreign), False),
        (str(activated_as_copy), True),
    ]
    assert adopt.choices("a") == ("add", "remove")
    assert adopt.choices(None) == ("remove",)


# --- fix round 1: partial results are always reported ------------------------


def test_very_first_takeover_adds_to_the_profile_being_activated(
    run, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    old = drop_skill(dirs["claude-code"], "old", "old\n")
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])

    result = ok(run("use", "a", input="add\n"))

    copied = respec_home / "profiles" / "a" / "skills" / "old"
    assert (copied / "SKILL.md").read_text() == "old\n"
    assert profile_skills(respec_home, "a")["old"] == {"enabled": True}
    assert old.is_symlink() and old.resolve() == copied.resolve()
    assert f"Added {old} to profile 'a'" in result.stdout
    assert result.stderr == ""


def test_adopt_add_while_an_edited_copy_waits_reports_and_links_the_add(
    run, activated_as_copy, respec_home, dirs
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = ok(run("adopt", "--add", "foreign"))

    assert f"Added {foreign} to profile 'a'" in result.stdout
    assert "cannot switch" not in result.output
    assert foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    assert (activated_as_copy / "SKILL.md").read_text() == "edited by hand\n"
    folder = folder_report(status_json(run), "claude-code")
    assert "foreign" in [i["name"] for i in folder["skills"]]
    assert [u["name"] for u in folder["unknown"]] == ["tdd"]


def test_adopt_add_json_while_an_edited_copy_waits_lists_the_link(
    run, activated_as_copy, dirs
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")
    foreign = drop_skill(dirs["claude-code"], "foreign")

    data = json.loads(ok(run("adopt", "--add", "foreign", "--json")).stdout)

    assert [r["name"] for r in data["resolved"]] == ["foreign"]
    assert data["linked"] == [str(foreign)]
    assert [u["name"] for u in data["unknown"]] == ["tdd"]


@pytest.mark.parametrize("as_json", [False, True])
def test_adopt_failing_part_way_reports_what_was_already_done(
    run, activated, respec_home, dirs, as_json
):
    first = drop_skill(dirs["claude-code"], "a-first", "first\n")
    (dirs["claude-code"] / "b-loose").write_text("loose\n")

    args = ["adopt", "--remove", "a-first", "--add", "b-loose"]
    result = run(*args, *(["--json"] if as_json else []))

    assert result.exit_code == 1
    assert not os.path.lexists(first)
    [backup] = [p for p in (respec_home / "backups").rglob("a-first") if p.is_dir()]
    if as_json:
        data = json.loads(result.stdout)
        [done] = data["resolved"]
        assert done["name"] == "a-first" and done["backup"] == str(backup)
        assert "not a folder" in data["error"]
    else:
        assert f"Backed up {first} to {backup} and removed it" in result.stdout
        assert "not a folder" in result.output
    assert (dirs["claude-code"] / "b-loose").read_text() == "loose\n"


@pytest.fixture
def takeover_with_clash(run, activated, respec_home, dirs, monkeypatch):
    """a (claude-code, tdd) is active; c also targets agents, which holds an
    entry ``aa`` and an entry ``tdd`` that clashes with a's own tdd."""
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    make_profile(respec_home, "c", ["claude-code", "agents"], ["lint"])
    aa = drop_skill(dirs["agents"], "aa", "aa\n")
    drop_skill(dirs["agents"], "tdd", "other tdd\n")
    return aa


def test_failed_takeover_choice_still_reports_the_switch_and_what_was_done(
    run, takeover_with_clash, respec_home, dirs
):
    aa = takeover_with_clash

    result = run("use", "c", input="remove\nadd\n")

    assert result.exit_code == 1
    assert active_profile(respec_home) == "c"
    assert "Switched to profile 'c'" in result.stdout
    assert "Backed up agents folder to" in result.stdout
    line = next(
        x for x in result.stdout.splitlines() if x.startswith(f"Backed up {aa}")
    )
    backup = line.removeprefix(f"Backed up {aa} to ").removesuffix(" and removed it")
    assert open(os.path.join(backup, "SKILL.md")).read() == "aa\n"
    assert not os.path.lexists(aa)
    assert "already has a skill 'tdd'" in result.output
    assert str(dirs["agents"] / "tdd") in result.stderr
    assert "respec adopt" in result.stderr


def test_interrupted_takeover_prompt_reports_and_leaves_the_rest_unknown(
    run, takeover_with_clash, respec_home, dirs
):
    aa = takeover_with_clash

    result = run("use", "c", input="remove\n")  # then the input ends

    assert result.exit_code == 0, result.output
    assert active_profile(respec_home) == "c"
    assert "Switched to profile 'c'" in result.stdout
    assert f"Backed up {aa} to " in result.stdout
    assert (dirs["agents"] / "tdd" / "SKILL.md").read_text() == "other tdd\n"
    assert "interrupted" in result.stderr.lower()
    assert str(dirs["agents"] / "tdd") in result.stderr
    assert "respec adopt" in result.stderr


def test_overwriting_add_backs_up_the_profile_previous_copy(
    run, activated_as_copy, respec_home
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    data = json.loads(ok(run("adopt", "--add", "tdd", "--json")).stdout)

    [resolved] = data["resolved"]
    saved = resolved["replaced_copy"]
    assert open(os.path.join(saved, "SKILL.md")).read() == "# tdd from a\n"


def test_failed_link_after_an_overwriting_add_puts_both_copies_back(
    run, activated_as_copy, respec_home, monkeypatch
):
    from respec import switch

    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")
    yaml_file = respec_home / "profiles" / "a" / "profile.yaml"
    yaml_before = yaml_file.read_bytes()

    def refuse(*args, **kwargs):
        raise switch.SwitchBlocked("linking refused for the test")

    monkeypatch.setattr(switch, "link_skills", refuse)

    result = run("adopt", "--add", "tdd")

    assert result.exit_code == 1
    assert "refused for the test" in result.output
    assert (activated_as_copy / "SKILL.md").read_text() == "edited by hand\n"
    profile_copy = respec_home / "profiles" / "a" / "skills" / "tdd" / "SKILL.md"
    assert profile_copy.read_text() == "# tdd from a\n"
    assert yaml_file.read_bytes() == yaml_before


# --- fix round 2 -------------------------------------------------------------


@pytest.fixture
def two_in_the_way(run, activated, respec_home, dirs, monkeypatch):
    """Profile c installs first and second, where hand-made folders sit."""
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    make_profile(respec_home, "c", ["claude-code"], ["first", "second"])
    first = drop_skill(dirs["claude-code"], "first", "first\n")
    second = drop_skill(dirs["claude-code"], "second", "second\n")
    return first, second


def test_abort_at_a_second_switch_prompt_reports_a_removal_and_its_backup(
    run, two_in_the_way, respec_home
):
    first, second = two_in_the_way

    result = run("use", "c", input="remove\n")  # the input ends at "second"

    assert result.exit_code == 1
    assert active_profile(respec_home) == "a"
    line = next(
        x for x in result.stdout.splitlines() if x.startswith(f"Backed up {first}")
    )
    backup = line.removeprefix(f"Backed up {first} to ").removesuffix(" and removed it")
    assert open(os.path.join(backup, "SKILL.md")).read() == "first\n"
    assert "interrupted" in result.stderr and "did not happen" in result.stderr
    assert str(second) in result.stderr and "respec adopt" in result.stderr
    assert (second / "SKILL.md").read_text() == "second\n"


def test_abort_at_a_second_switch_prompt_reports_and_links_an_add(
    run, two_in_the_way, respec_home
):
    first, second = two_in_the_way

    result = run("use", "c", input="add\n")

    assert result.exit_code == 1
    assert f"Added {first} to profile 'a'" in result.stdout
    copied = respec_home / "profiles" / "a" / "skills" / "first"
    assert (copied / "SKILL.md").read_text() == "first\n"
    assert first.is_symlink() and first.resolve() == copied.resolve()
    assert active_profile(respec_home) == "a"
    assert "interrupted" in result.stderr


def test_overwriting_add_says_the_previous_copy_was_replaced_and_where_it_went(
    run, activated_as_copy, respec_home
):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    result = ok(run("adopt", "--add", "tdd"))

    [saved] = [
        p for p in (respec_home / "backups").rglob("tdd") if "profiles" in p.parts
    ]
    assert "Replaced" in result.stdout and "'tdd'" in result.stdout
    assert str(saved) in result.stdout
    assert (saved / "SKILL.md").read_text() == "# tdd from a\n"


def test_overwrite_cleans_up_only_redundant_leftover_staging_folders(
    run, activated_as_copy, respec_home
):
    skills = respec_home / "profiles" / "a" / "skills"
    (skills / "other").mkdir()
    (skills / "other" / "SKILL.md").write_text("other\n")
    # A staged copy identical to the live folder holds nothing new.
    shutil.copytree(skills / "other", skills / ".other.respec-new")
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    ok(run("adopt", "--add", "tdd"))

    assert sorted(p.name for p in skills.iterdir()) == ["other", "tdd"]


def test_add_clash_points_to_remove_with_a_backup_not_respec_remove(
    run, activated, respec_home, dirs
):
    ok(run("disable", "tdd"))
    clash = drop_skill(dirs["claude-code"], "tdd", "someone else's tdd\n")

    result = run("adopt", "--add", "tdd")

    assert result.exit_code == 1
    assert "already has a skill 'tdd'" in result.output
    assert "respec remove" not in result.output
    assert "--remove" in result.output and "backed up" in result.output
    assert (clash / "SKILL.md").read_text() == "someone else's tdd\n"


def test_block_without_an_active_profile_does_not_offer_add(
    run, activated, respec_home, dirs
):
    deactivate(respec_home)
    drop_skill(dirs["claude-code"], "lint")

    result = run("use", "b")

    assert result.exit_code == 1
    assert "add each to the active profile" not in result.output
    assert "no profile is active" in result.output.lower()
    assert "--unknown add" not in result.output


def test_unknown_add_without_an_active_profile_explains_the_takeover_case(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])

    result = run("use", "a", "--unknown", "add")

    assert result.exit_code == 1
    assert "no profile is active" in result.output
    assert "profile being activated" in result.output


# --- fix round 3 -------------------------------------------------------------


def test_leftover_whose_live_folder_is_gone_is_restored_not_deleted(
    run, activated_as_copy, respec_home
):
    skills = respec_home / "profiles" / "a" / "skills"
    (skills / ".other.respec-old").mkdir()
    (skills / ".other.respec-old" / "SKILL.md").write_text("only copy\n")
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    ok(run("adopt", "--add", "tdd"))

    assert (skills / "other" / "SKILL.md").read_text() == "only copy\n"
    assert not (skills / ".other.respec-old").exists()


def test_leftover_that_may_be_the_only_copy_is_kept_and_reported(
    run, activated_as_copy, respec_home
):
    skills = respec_home / "profiles" / "a" / "skills"
    (skills / "other").mkdir()
    (skills / "other" / "SKILL.md").write_text("live\n")
    (skills / ".other.respec-old").mkdir()
    (skills / ".other.respec-old" / "SKILL.md").write_text("only copy\n")
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    result = ok(run("adopt", "--add", "tdd"))

    leftover = skills / ".other.respec-old"
    assert (leftover / "SKILL.md").read_text() == "only copy\n"
    assert str(leftover) in result.output


@pytest.fixture
def takeover_then_clash(run, respec_home, dirs, monkeypatch):
    """a (claude-code: tdd, lint disabled) is active. b (claude-code, agents:
    first, lint) is in the way of hand-made first and lint; agents holds
    foreign and is taken over by the switch."""
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    make_profile(respec_home, "a", ["claude-code"], ["tdd", "lint"])
    ok(run("use", "a"))
    ok(run("disable", "lint"))
    make_profile(respec_home, "b", ["claude-code", "agents"], ["first", "lint"])
    first = drop_skill(dirs["claude-code"], "first", "first\n")
    drop_skill(dirs["claude-code"], "lint", "hand lint\n")
    foreign = drop_skill(dirs["agents"], "foreign", "foreign\n")
    return first, foreign


def takeover_backup(respec_home):
    [folder] = [p for p in (respec_home / "backups").glob("*/agents") if p.is_dir()]
    assert (folder / "foreign" / "SKILL.md").read_text() == "foreign\n"
    return folder


def test_failed_switch_reports_the_takeover_backup_and_warns(
    run, takeover_then_clash, respec_home, dirs
):
    first, foreign = takeover_then_clash

    result = run("use", "b", input="remove\nadd\n")

    assert result.exit_code == 1
    assert "already has a skill 'lint'" in result.output
    assert f"Backed up agents folder to {takeover_backup(respec_home)}" in (
        result.stdout
    )
    assert f"Backed up {first} to " in result.stdout
    assert str(foreign) in result.stderr and "respec adopt" in result.stderr
    assert active_profile(respec_home) == "a"


def test_failed_switch_json_has_backups_resolved_warnings_and_error(
    run, takeover_then_clash, respec_home, dirs
):
    first, foreign = takeover_then_clash

    result = run("use", "b", "--unknown", "add", "--json")

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["backups"] == {"agents": str(takeover_backup(respec_home))}
    assert [r["name"] for r in data["resolved"]] == ["first"]
    assert "already has a skill 'lint'" in data["error"]
    paths = [w["path"] for w in data["warnings"] if w["type"] == "unknown-entry"]
    assert str(foreign) in paths
    # first went into the still-active profile a and is linked again.
    assert first.is_symlink()
    assert (first / "SKILL.md").read_text() == "first\n"


def test_aborted_switch_reports_the_takeover_backup(
    run, takeover_then_clash, respec_home
):
    result = run("use", "b", input="remove\n")

    assert result.exit_code == 1
    assert f"Backed up agents folder to {takeover_backup(respec_home)}" in (
        result.stdout
    )
    assert "did not happen" in result.stderr


def test_aborted_switch_with_a_failing_relink_still_reports_everything(
    run, takeover_then_clash, respec_home, monkeypatch
):
    from respec import switch

    first, _ = takeover_then_clash

    def fail(*args, **kwargs):
        raise switch.SwitchBlocked("linking refused for the test")

    monkeypatch.setattr(switch, "link_skills", fail)

    result = run("use", "b", input="add\n")

    assert result.exit_code == 1
    assert "linking refused for the test" in result.stderr
    assert f"Added {first} to profile 'a'" in result.stdout
    assert f"Backed up agents folder to {takeover_backup(respec_home)}" in (
        result.stdout
    )


def test_replaced_wording_names_the_skill_and_profile_plainly(run, activated_as_copy):
    (activated_as_copy / "SKILL.md").write_text("edited by hand\n")

    result = ok(run("adopt", "--add", "tdd"))

    assert "Replaced the copy of 'tdd' in profile 'a'" in result.stdout
