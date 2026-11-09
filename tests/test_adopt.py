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


# --- detection -------------------------------------------------------------


def test_status_json_reports_foreign_entry_dropped_after_activation(
    run, activated, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    folder = folder_report(status_json(run), "claude-code")

    assert [item["name"] for item in folder["items"]] == ["tdd"]
    assert folder["unknown"] == [
        {
            "name": "foreign",
            "path": str(foreign),
            "kind": "folder",
            "targets": ["claude-code"],
            "replaced": False,
        }
    ]
    assert folder["unmanaged"] == []


def test_status_human_lists_unknown_entries_with_a_hint(run, activated, dirs):
    drop_skill(dirs["claude-code"], "foreign")

    out = ok(run("status")).stdout

    line = next(line for line in out.splitlines() if "foreign" in line)
    assert "unknown" in line
    assert "respec adopt" in out


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


# --- before a switch -------------------------------------------------------


def test_non_interactive_switch_with_unknown_entry_fails_and_changes_nothing(
    run, activated, respec_home, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    result = run("use", "b")

    assert result.exit_code == 1
    assert str(foreign) in result.output
    assert "--unknown" in result.output and "respec adopt" in result.output
    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    assert (dirs["claude-code"] / "tdd").is_symlink()
    assert not (dirs["claude-code"] / "lint").exists()
    assert active_profile(respec_home) == "a"
    assert not (respec_home / "backups").exists()


def test_switch_policy_backup_moves_entry_to_backups_then_switches(
    run, activated, respec_home, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    ok(run("use", "b", "--unknown", "backup"))

    assert not os.path.lexists(foreign)
    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]
    assert backup_files(respec_home) == {
        "claude-code/foreign/SKILL.md": "foreign\n",
        "claude-code/foreign/refs/note.md": "note\n",
    }
    assert active_profile(respec_home) == "b"


def test_switch_policy_add_copies_entry_into_new_profile_and_links_it(
    run, activated, respec_home, dirs
):
    drop_skill(dirs["claude-code"], "foreign")

    ok(run("use", "b", "--unknown", "add"))

    copied = respec_home / "profiles" / "b" / "skills" / "foreign"
    assert (copied / "SKILL.md").read_text() == "foreign\n"
    assert (copied / "refs" / "note.md").read_text() == "note\n"
    assert profile_skills(respec_home, "b")["foreign"] == {"enabled": True}
    link = dirs["claude-code"] / "foreign"
    assert link.is_symlink() and link.resolve() == copied.resolve()
    report = folder_report(status_json(run), "claude-code")
    assert sorted(i["name"] for i in report["items"]) == ["foreign", "lint"]
    assert report["unknown"] == []


def test_switch_policy_keep_leaves_entry_and_stops_asking(
    run, activated, respec_home, dirs
):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    ok(run("use", "b", "--unknown", "keep"))

    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    report = folder_report(status_json(run), "claude-code")
    assert report["unknown"] == []
    assert report["unmanaged"] == [{"name": "foreign", "path": str(foreign)}]
    # Kept entries are not asked about again and never removed by a switch.
    ok(run("use", "a"))
    assert (foreign / "SKILL.md").read_text() == "foreign\n"


def test_interactive_switch_prompts_once_per_entry(
    run, activated, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    first = drop_skill(dirs["claude-code"], "first", "first\n")
    second = drop_skill(dirs["claude-code"], "second", "second\n")

    result = run("use", "b", input="backup\nkeep\n")

    ok(result)
    assert result.output.count("add to profile") == 2
    assert not os.path.lexists(first)
    assert (second / "SKILL.md").read_text() == "second\n"
    assert "first\n" in backup_files(respec_home).values()
    assert active_profile(respec_home) == "b"


def test_add_choice_on_a_file_fails_and_keeps_the_file(
    run, activated, respec_home, dirs
):
    loose = dirs["claude-code"] / "notes.txt"
    loose.write_text("loose\n")

    result = run("use", "b", "--unknown", "add")

    assert result.exit_code == 1
    assert "not a folder" in result.output
    assert loose.read_text() == "loose\n"
    assert active_profile(respec_home) == "a"


# --- a recorded link replaced by something else ---------------------------


def test_replaced_link_is_reported_as_unknown(run, activated, dirs):
    link = dirs["claude-code"] / "tdd"
    link.unlink()
    drop_skill(dirs["claude-code"], "tdd", "hand-made\n")

    folder = folder_report(status_json(run), "claude-code")

    assert folder["items"] == []
    assert [(u["name"], u["replaced"]) for u in folder["unknown"]] == [("tdd", True)]


def test_replaced_link_blocks_switch_cleanly_then_backup_resolves_it(
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

    ok(run("use", "b", "--unknown", "backup"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]
    assert "hand-made\n" in backup_files(respec_home).values()


def test_item_change_is_rolled_back_when_replaced_link_blocks_refresh(
    run, respec_home, dirs
):
    make_profile(respec_home, "a", ["claude-code"], ["tdd", "lint"])
    ok(run("use", "a"))
    (dirs["claude-code"] / "tdd").unlink()
    drop_skill(dirs["claude-code"], "tdd", "hand-made\n")

    result = run("disable", "lint")

    assert result.exit_code == 1
    assert profile_skills(respec_home, "a")["lint"] == {"enabled": True}
    assert active_profile(respec_home) == "a"
    assert (dirs["claude-code"] / "lint").is_symlink()


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

    assert folder["items"] == []
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

    ok(run("use", "b", "--unknown", "backup"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["lint"]
    assert "edited by hand\n" in backup_files(respec_home).values()


def test_unmodified_copy_stays_managed_and_is_replaced_on_switch(
    run, activated_as_copy, dirs
):
    folder = folder_report(status_json(run), "claude-code")
    assert [(i["name"], i["mode"]) for i in folder["items"]] == [("tdd", "copy")]
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


def test_adopt_backup_flag_backs_up_and_removes_only_that_entry(
    run, activated, respec_home, dirs
):
    drop_skill(dirs["claude-code"], "one", "one\n")
    two = drop_skill(dirs["claude-code"], "two", "two\n")

    data = json.loads(ok(run("adopt", "--backup", "one", "--json")).stdout)

    [resolved] = data["resolved"]
    assert resolved["name"] == "one" and resolved["choice"] == "backup"
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

    ok(run("adopt", "--add", "my-name", "-p", "b"))

    assert "my-name" in profile_skills(respec_home, "b")
    copied = respec_home / "profiles" / "b" / "skills" / "my-name"
    assert (copied / "SKILL.md").read_text() == "foreign\n"
    assert not copied.is_symlink()
    assert (elsewhere / "SKILL.md").read_text() == "foreign\n"
    assert not os.path.lexists(dirs["claude-code"] / "my-name")


def test_adopt_keep_flag_records_entry_as_unmanaged(run, activated, dirs):
    foreign = drop_skill(dirs["claude-code"], "foreign")

    ok(run("adopt", "--keep", str(foreign)))

    folder = folder_report(status_json(run), "claude-code")
    assert folder["unknown"] == []
    assert folder["unmanaged"] == [{"name": "foreign", "path": str(foreign)}]


def test_adopt_all_applies_one_choice_to_every_entry(run, activated, respec_home, dirs):
    drop_skill(dirs["claude-code"], "one", "one\n")
    drop_skill(dirs["claude-code"], "two", "two\n")

    ok(run("adopt", "--all", "backup"))

    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == ["tdd"]
    assert {"one\n", "two\n"} <= set(backup_files(respec_home).values())


def test_adopt_unknown_selector_fails_before_changing_anything(run, activated, dirs):
    one = drop_skill(dirs["claude-code"], "one")

    result = run("adopt", "--backup", "one", "--backup", "missing")

    assert result.exit_code == 1
    assert "missing" in result.output
    assert (one / "SKILL.md").exists()


def test_adopt_interactive_prompts_for_each_entry(
    run, activated, respec_home, dirs, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    foreign = drop_skill(dirs["claude-code"], "foreign")

    ok(run("adopt", input="keep\n"))

    assert (foreign / "SKILL.md").exists()
    assert folder_report(status_json(run), "claude-code")["unmanaged"] == [
        {"name": "foreign", "path": str(foreign)}
    ]


def test_status_lists_shared_items_once_whatever_the_profile_target_order(
    run, respec_home, dirs
):
    dirs["agents"].mkdir(parents=True)
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    make_profile(respec_home, "a", ["agents", "claude-code"], ["tdd"])
    ok(run("use", "a"))

    report = status_json(run)

    assert [i["name"] for i in folder_report(report, "claude-code")["items"]] == ["tdd"]
    assert folder_report(report, "agents")["items"] == []
    assert folder_report(report, "agents")["same_as"] == "claude-code"


# --- layer commands share the items refresh path ----------------------------


@pytest.mark.parametrize(
    "command",
    [
        ("layer", "use", "design-principles", "lint"),
        ("layer", "disable", "design-principles"),
    ],
)
def test_layer_change_is_rolled_back_while_an_unknown_entry_waits(
    run, respec_home, dirs, command
):
    make_profile(respec_home, "a", ["claude-code"], ["tdd", "lint"])
    ok(run("use", "a"))
    ok(run("layer", "add-item", "design-principles", "tdd"))
    foreign = drop_skill(dirs["claude-code"], "foreign")
    before = (respec_home / "profiles" / "a" / "profile.yaml").read_text()

    result = run(*command)

    assert result.exit_code == 1
    assert str(foreign) in result.output and "respec adopt" in result.output
    assert (respec_home / "profiles" / "a" / "profile.yaml").read_text() == before
    assert sorted(p.name for p in dirs["claude-code"].iterdir()) == [
        "foreign",
        "lint",
        "tdd",
    ]
    assert active_profile(respec_home) == "a"

    ok(run("adopt", "--keep", "foreign"))
    ok(run(*command))
    assert (foreign / "SKILL.md").read_text() == "foreign\n"
