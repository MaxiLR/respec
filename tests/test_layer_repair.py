"""Hand-edited exclusivity conflicts: warn, repair, refuse to switch."""

import json

import pytest
import yaml


@pytest.fixture
def claude_dir(isolated_homes):
    return isolated_homes.home / ".claude" / "skills"


@pytest.fixture
def profiles_root(isolated_homes):
    return isolated_homes.respec_home / "profiles"


def read_yaml(profiles_root, profile="work"):
    return yaml.safe_load((profiles_root / profile / "profile.yaml").read_text())


def write_yaml(profiles_root, data, profile="work"):
    (profiles_root / profile / "profile.yaml").write_text(yaml.safe_dump(data))


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def fails(result):
    assert result.exit_code != 0, result.output
    return result


def linked(folder):
    if not folder.exists():
        return set()
    return {entry.name for entry in folder.iterdir()}


def enabled_skills(profiles_root, profile="work"):
    skills = read_yaml(profiles_root, profile)["skills"]
    return {name for name, entry in skills.items() if entry["enabled"]}


def make_skill(tmp_path, name):
    folder = tmp_path / "src" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"# {name}\n")
    return folder


@pytest.fixture
def work(run, tmp_path):
    """Active profile 'work' on claude-code with skills a, b, c (all enabled)."""
    ok(run("profile", "new", "work", "-t", "claude-code"))
    ok(run("use", "work"))
    for name in ("a", "b", "c"):
        ok(run("add", str(make_skill(tmp_path, name))))


@pytest.fixture
def conflict(work, profiles_root):
    """Hand-edit 'work' so the exclusive design-principles layer enables a and b."""
    data = read_yaml(profiles_root)
    data["layers"] = {"design-principles": {"skills": ["a", "b"]}}
    write_yaml(profiles_root, data)


def assert_names_conflict(text):
    assert "'design-principles'" in text
    assert "(a, b)" in text
    assert "respec layer repair design-principles" in text


# Criterion 1: load warns instead of failing.


@pytest.mark.parametrize(
    "command",
    [
        ("layer", "list"),
        ("layer", "show", "design-principles"),
        ("profile", "show", "work"),
        ("status",),
    ],
)
def test_conflict_loads_and_warns_on_stderr(run, conflict, command):
    result = ok(run(*command))

    assert "warning" in result.stderr
    assert_names_conflict(result.stderr)
    assert "warning" not in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        ("layer", "list"),
        ("layer", "show", "design-principles"),
        ("profile", "show", "work"),
        ("status",),
    ],
)
def test_conflict_json_has_structured_warnings_and_clean_stdout(run, conflict, command):
    result = ok(run(*command, "--json"))

    payload = json.loads(result.stdout)
    assert payload["warnings"] == [
        {
            "profile": "work",
            "layer": "design-principles",
            "skills": ["a", "b"],
            "message": payload["warnings"][0]["message"],
            "fix": "respec layer repair design-principles -p work",
        }
    ]
    assert_names_conflict(payload["warnings"][0]["message"])
    assert "respec layer repair" in result.stderr


def test_json_without_conflict_has_empty_warnings(run, work):
    payload = json.loads(ok(run("layer", "list", "--json")).stdout)

    assert payload["warnings"] == []


def test_profile_list_shows_conflicted_profile_as_valid_with_warning(run, conflict):
    result = ok(run("profile", "list", "--json"))

    payload = json.loads(result.stdout)
    assert [entry["name"] for entry in payload["profiles"]] == ["work"]
    assert "error" not in payload["profiles"][0]
    assert payload["warnings"][0]["layer"] == "design-principles"


# Criterion 2: respec layer repair.


def test_repair_keep_disables_the_others_and_relinks(
    run, conflict, profiles_root, claude_dir
):
    result = ok(run("layer", "repair", "design-principles", "--keep", "b"))

    assert enabled_skills(profiles_root) == {"b", "c"}
    assert linked(claude_dir) == {"b", "c"}
    assert "disabled 'a'" in result.stdout.lower()
    assert "warning" not in result.stderr
    # The conflict is gone: later commands no longer warn.
    assert ok(run("layer", "list")).stderr == ""


def test_repair_without_keep_noninteractive_keeps_first_listed(
    run, conflict, profiles_root, claude_dir
):
    change = json.loads(
        ok(run("layer", "repair", "design-principles", "--json")).stdout
    )

    assert change["action"] == "repair"
    assert change["skill"] == "a"
    assert change["disabled"] == ["b"]
    assert enabled_skills(profiles_root) == {"a", "c"}
    assert linked(claude_dir) == {"a", "c"}


def test_repair_without_keep_in_terminal_prompts_for_the_skill(
    run, conflict, profiles_root, claude_dir, monkeypatch
):
    from respec import cli

    monkeypatch.setattr(cli, "_interactive", lambda: True)

    result = ok(run("layer", "repair", "design-principles", input="b\n"))

    assert "a" in result.stdout and "b" in result.stdout
    assert enabled_skills(profiles_root) == {"b", "c"}
    assert linked(claude_dir) == {"b", "c"}
    assert "disabled 'a'" in result.stdout.lower()


def test_repair_keep_must_be_a_conflicting_skill(run, conflict, profiles_root):
    before = read_yaml(profiles_root)

    result = fails(run("layer", "repair", "design-principles", "--keep", "c"))

    assert "'c'" in result.output
    assert read_yaml(profiles_root) == before


def test_repair_without_conflict_changes_nothing(run, work, profiles_root):
    ok(run("layer", "use", "design-principles", "a"))
    before = read_yaml(profiles_root)

    result = ok(run("layer", "repair", "design-principles"))

    assert "nothing to repair" in result.stdout.lower()
    assert read_yaml(profiles_root) == before


def test_repair_of_named_inactive_profile_does_not_touch_targets(
    run, tmp_path, profiles_root, claude_dir
):
    ok(run("profile", "new", "home", "-t", "claude-code"))
    for name in ("x", "y"):
        ok(run("add", str(make_skill(tmp_path, name)), "-p", "home"))
    data = read_yaml(profiles_root, "home")
    data["layers"] = {"design-principles": {"skills": ["x", "y"]}}
    write_yaml(profiles_root, data, "home")

    ok(run("layer", "repair", "design-principles", "--keep", "y", "-p", "home"))

    assert enabled_skills(profiles_root, "home") == {"y"}
    assert not claude_dir.exists()


def test_repair_refused_by_switch_preflight_leaves_profile_unchanged(
    run, conflict, profiles_root, claude_dir
):
    (claude_dir / "stray").mkdir()  # an unknown entry blocks the refresh
    before = read_yaml(profiles_root)

    result = fails(run("layer", "repair", "design-principles", "--keep", "b"))

    assert "not managed by respec" in result.output
    assert read_yaml(profiles_root) == before
    assert linked(claude_dir) == {"a", "b", "c", "stray"}


# Criterion 3: respec use refuses an unrepaired conflict.


def test_use_refuses_conflicted_profile_and_changes_nothing(
    run, tmp_path, conflict, profiles_root, claude_dir, isolated_homes
):
    ok(run("profile", "new", "home", "-t", "claude-code"))
    ok(run("add", str(make_skill(tmp_path, "x")), "-p", "home"))
    ok(run("use", "home"))
    state_file = isolated_homes.respec_home / "state.json"
    state_before = state_file.read_text()
    profile_before = read_yaml(profiles_root)

    result = fails(run("use", "work"))

    assert_names_conflict(result.output)
    assert linked(claude_dir) == {"x"}
    assert state_file.read_text() == state_before
    assert read_yaml(profiles_root) == profile_before


def test_use_works_after_repair(run, tmp_path, conflict, claude_dir):
    ok(run("profile", "new", "home", "-t", "claude-code"))
    ok(run("use", "home"))
    ok(run("layer", "repair", "design-principles", "-p", "work"))

    ok(run("use", "work"))

    assert linked(claude_dir) == {"a", "c"}


# Criterion 4: the layer key is ``skills:``.


def test_layer_writes_use_the_skills_key(run, work, profiles_root):
    ok(run("layer", "use", "design-principles", "a"))

    layer = read_yaml(profiles_root)["layers"]["design-principles"]

    assert layer == {"skills": ["a"]}


def test_legacy_items_key_is_read_and_rewritten_as_skills(run, work, profiles_root):
    data = read_yaml(profiles_root)
    data["layers"] = {
        "review": {"exclusive": False, "description": "Review", "items": ["a"]}
    }
    write_yaml(profiles_root, data)

    shown = json.loads(ok(run("layer", "show", "review", "--json")).stdout)
    assert [skill["name"] for skill in shown["skills"]] == ["a"]

    ok(run("layer", "add-skill", "review", "b"))

    review = read_yaml(profiles_root)["layers"]["review"]
    assert review["skills"] == ["a", "b"]
    assert "items" not in review


def test_layer_with_both_skills_and_items_is_an_error(run, work, profiles_root):
    data = read_yaml(profiles_root)
    data["layers"] = {"design-principles": {"skills": ["a"], "items": ["b"]}}
    write_yaml(profiles_root, data)

    result = fails(run("layer", "list"))

    assert "layers.design-principles" in result.output
    assert "'skills'" in result.output and "'items'" in result.output


def test_validation_messages_name_the_skills_key(run, work, profiles_root):
    data = read_yaml(profiles_root)
    data["layers"] = {
        "design-principles": {"skills": ["zzz"]},
        "review": {"exclusive": False, "description": "R", "skills": "a"},
    }
    write_yaml(profiles_root, data)

    result = fails(run("layer", "list"))

    assert "layers.design-principles.skills: 'zzz' is not a skill" in result.output
    assert "layers.review.skills must be a list" in result.output


# Review round 1 regressions.


def test_repair_fixes_an_inactive_exclusive_layer_that_layer_on_refuses(
    run, work, profiles_root, claude_dir
):
    ok(run("layer", "off", "design-principles"))
    ok(run("layer", "add-skill", "design-principles", "a"))
    ok(run("layer", "add-skill", "design-principles", "b"))
    refused = fails(run("layer", "on", "design-principles"))
    assert "respec layer repair design-principles" in refused.output

    result = ok(run("layer", "repair", "design-principles", "--keep", "b"))

    assert "disabled 'a'" in result.stdout.lower()
    assert enabled_skills(profiles_root) == {"b", "c"}
    assert linked(claude_dir) == {"b", "c"}
    ok(run("layer", "on", "design-principles"))


def test_repair_of_additive_layer_says_nothing_to_repair_accurately(
    run, work, profiles_root
):
    ok(run("layer", "add", "review", "--additive", "-d", "Review"))
    ok(run("layer", "add-skill", "review", "a"))
    ok(run("layer", "add-skill", "review", "b"))
    before = read_yaml(profiles_root)

    result = ok(run("layer", "repair", "review"))

    assert "additive" in result.stdout
    assert read_yaml(profiles_root) == before


@pytest.mark.parametrize(
    "command",
    [
        ("disable", "a"),
        ("layer", "off", "design-principles"),
        ("layer", "use", "design-principles", "b"),
    ],
)
def test_resolving_the_conflict_another_way_leaves_no_stale_warning(
    run, conflict, command
):
    result = ok(run(*command, "--json"))

    assert json.loads(result.stdout)["warnings"] == []
    assert "warning" not in result.stderr


def test_refused_change_restores_legacy_file_bytes(run, work, profiles_root):
    data = read_yaml(profiles_root)
    data["layers"] = {
        "review": {"exclusive": False, "description": "Review", "items": ["a"]}
    }
    write_yaml(profiles_root, data)
    file = profiles_root / "work" / "profile.yaml"
    original = file.read_bytes()
    claude_dir = profiles_root.parent.parent / "home" / ".claude" / "skills"
    (claude_dir / "stray").mkdir()  # an unknown entry blocks the refresh

    fails(run("layer", "add-skill", "review", "b"))
    assert file.read_bytes() == original

    fails(run("disable", "a"))
    assert file.read_bytes() == original


def test_layer_use_json_lists_the_skill_it_disabled(run, work):
    ok(run("layer", "use", "design-principles", "a"))
    ok(run("layer", "add-skill", "design-principles", "b"))

    change = json.loads(
        ok(run("layer", "use", "design-principles", "b", "--json")).stdout
    )

    assert change["disabled"] == ["a"]


def test_restoring_an_edited_copy_writes_the_copy_not_the_loaded_bytes(
    work, profiles_root, isolated_homes
):
    import dataclasses

    from respec import profiles

    loaded = profiles.load_profile(isolated_homes.respec_home, "work")
    copy = dataclasses.replace(loaded, targets=["agents"])

    profiles.restore_profile(copy)

    assert read_yaml(profiles_root)["targets"] == ["agents"]
