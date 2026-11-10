"""respec layer ... and layer rules, against temporary homes."""

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
    return result.output


def linked(folder):
    if not folder.exists():
        return set()
    return {entry.name for entry in folder.iterdir()}


def enabled_items(profiles_root, profile="work"):
    skills = read_yaml(profiles_root, profile)["skills"]
    return {name for name, entry in skills.items() if entry["enabled"]}


@pytest.fixture
def work(run, tmp_path):
    """Active profile 'work' on claude-code with skills a, b, c (all enabled)."""
    ok(run("profile", "new", "work", "-t", "claude-code"))
    ok(run("use", "work"))
    for name in ("a", "b", "c"):
        folder = tmp_path / "src" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
        ok(run("add", str(folder)))


def test_new_profile_lists_builtin_layers_with_descriptions(run):
    ok(run("profile", "new", "work", "-t", "claude-code"))

    layers = json.loads(ok(run("layer", "list", "-p", "work", "--json")).output)

    by_name = {layer["name"]: layer for layer in layers["layers"]}
    assert set(by_name) == {"design-principles", "output-style"}
    design = by_name["design-principles"]
    assert design["exclusive"] is True and design["builtin"] is True
    assert design["active"] is True and design["skills"] == []
    assert "principles" in design["description"]
    assert "component libraries" in design["description"]
    assert "tokens" in design["description"]
    assert by_name["output-style"]["exclusive"] is True
    assert by_name["output-style"]["description"]


def test_layer_use_in_exclusive_layer_keeps_one_item_enabled_and_linked(
    run, work, profiles_root, claude_dir
):
    ok(run("layer", "use", "design-principles", "a"))
    ok(run("layer", "use", "design-principles", "b"))

    data = read_yaml(profiles_root)
    assert data["layers"]["design-principles"]["skills"] == ["a", "b"]
    assert enabled_items(profiles_root) == {"b", "c"}
    assert linked(claude_dir) == {"b", "c"}

    ok(run("layer", "use", "design-principles", "a"))

    assert enabled_items(profiles_root) == {"a", "c"}
    assert linked(claude_dir) == {"a", "c"}


def test_adding_enabled_item_to_exclusive_layer_keeps_current_choice(
    run, work, profiles_root, claude_dir
):
    ok(run("layer", "use", "design-principles", "a"))

    ok(run("layer", "add-skill", "design-principles", "b"))

    assert read_yaml(profiles_root)["layers"]["design-principles"]["skills"] == [
        "a",
        "b",
    ]
    assert enabled_items(profiles_root) == {"a", "c"}
    assert linked(claude_dir) == {"a", "c"}


def test_plain_enable_of_exclusive_member_disables_the_previous_one(
    run, work, profiles_root, claude_dir
):
    ok(run("layer", "use", "design-principles", "a"))
    ok(run("layer", "add-skill", "design-principles", "b"))

    ok(run("enable", "b"))

    assert enabled_items(profiles_root) == {"b", "c"}
    assert linked(claude_dir) == {"b", "c"}


def test_custom_additive_layer_enables_and_disables_as_a_group(
    run, work, profiles_root, claude_dir
):
    ok(
        run(
            "layer",
            "add",
            "review",
            "--additive",
            "--description",
            "Code review helpers",
        )
    )
    ok(run("layer", "add-skill", "review", "a"))
    ok(run("layer", "add-skill", "review", "b"))

    ok(run("layer", "disable", "review"))
    assert enabled_items(profiles_root) == {"c"}
    assert linked(claude_dir) == {"c"}

    ok(run("layer", "enable", "review"))
    assert enabled_items(profiles_root) == {"a", "b", "c"}
    assert linked(claude_dir) == {"a", "b", "c"}

    assert read_yaml(profiles_root)["layers"]["review"] == {
        "exclusive": False,
        "description": "Code review helpers",
        "skills": ["a", "b"],
    }


def test_custom_exclusive_layer_show_and_rm(run, work, profiles_root, claude_dir):
    ok(run("layer", "add", "tone", "--exclusive", "--description", "Writing tone"))
    ok(run("layer", "use", "tone", "a"))
    ok(run("layer", "use", "tone", "b"))

    shown = json.loads(ok(run("layer", "show", "tone", "--json")).output)
    assert shown == {
        "warnings": [],
        "name": "tone",
        "profile": "work",
        "exclusive": True,
        "description": "Writing tone",
        "builtin": False,
        "active": True,
        "skills": [
            {"name": "a", "enabled": False},
            {"name": "b", "enabled": True},
        ],
    }
    assert "Writing tone" in ok(run("layer", "show", "tone")).output

    ok(run("layer", "rm", "tone"))

    assert "tone" not in read_yaml(profiles_root).get("layers", {})
    # Items stay in the profile, unchanged and not moved.
    assert enabled_items(profiles_root) == {"b", "c"}
    assert linked(claude_dir) == {"b", "c"}


def test_builtin_layer_cannot_be_removed_but_can_be_turned_off(
    run, work, profiles_root, claude_dir
):
    assert "built-in" in fails(run("layer", "rm", "design-principles"))

    ok(run("layer", "use", "design-principles", "a"))
    ok(run("layer", "add-skill", "design-principles", "b"))
    ok(run("layer", "off", "design-principles"))

    assert read_yaml(profiles_root)["layers"]["design-principles"]["active"] is False
    # With the layer off, exclusivity lapses: both members can be enabled.
    ok(run("enable", "b"))
    assert enabled_items(profiles_root) == {"a", "b", "c"}
    assert linked(claude_dir) == {"a", "b", "c"}

    # Turning it back on while two members are enabled is refused.
    output = fails(run("layer", "on", "design-principles"))
    assert "a" in output and "b" in output
    assert read_yaml(profiles_root)["layers"]["design-principles"]["active"] is False

    ok(run("disable", "a"))
    ok(run("layer", "on", "design-principles"))
    assert "active" not in read_yaml(profiles_root)["layers"]["design-principles"]


def test_output_style_layer_accepts_no_skills(run, work, profiles_root):
    before = read_yaml(profiles_root)

    for command in ("use", "add-skill"):
        output = fails(run("layer", command, "output-style", "a"))
        assert "output styles are not supported yet" in output

    assert read_yaml(profiles_root) == before


def test_layers_never_change_install_locations(run, work, claude_dir, tmp_path):
    ok(run("layer", "add", "review", "--additive", "--description", "Review"))
    ok(run("layer", "add-skill", "review", "a"))
    ok(run("layer", "use", "design-principles", "b"))

    for name in ("a", "b", "c"):
        entry = claude_dir / name
        assert entry.is_symlink()
        assert entry.parent == claude_dir
    assert not any(
        path.name in ("review", "design-principles") for path in claude_dir.iterdir()
    )


def test_removing_an_item_drops_it_from_its_layer(run, work, profiles_root):
    ok(run("layer", "use", "design-principles", "a"))

    ok(run("remove", "a"))

    shown = json.loads(ok(run("layer", "show", "design-principles", "--json")).output)
    assert shown["skills"] == []
    assert "a" not in read_yaml(profiles_root)["skills"]


def test_schema_rejects_bad_layers(run, work, profiles_root):
    data = read_yaml(profiles_root)
    data["layers"] = {
        "design-principles": {"items": ["a", "b"], "exclusive": False},
        "output-style": {"items": ["c"]},
        "review": {"exclusive": "yes", "items": ["zzz"]},
        "tone": {"description": "x"},
        "more": {"exclusive": False, "description": "More", "items": ["a"]},
    }
    write_yaml(profiles_root, data)

    output = fails(run("layer", "list"))

    assert "layers.design-principles: unknown key 'exclusive'" in output
    assert "layers.design-principles" in output and "exclusive" in output
    assert "output-style" in output and "accepts no skills" in output
    assert "layers.review.exclusive must be true or false" in output
    assert "layers.review.description is required" in output
    assert "'zzz'" in output
    assert "layers.tone.exclusive is required" in output
    assert "'a' is listed in more than one layer" in output


def test_switch_refused_when_preflight_blocks_leaves_profile_unchanged(
    run, work, profiles_root, claude_dir
):
    ok(run("layer", "add", "review", "--additive", "--description", "Review"))
    ok(run("layer", "add-skill", "review", "a"))
    ok(run("layer", "disable", "review"))
    (claude_dir / "a").mkdir()  # an unmanaged entry occupies a's install path
    before = read_yaml(profiles_root)

    output = fails(run("layer", "enable", "review"))

    assert "not managed by respec" in output
    assert read_yaml(profiles_root) == before


def test_layer_commands_target_named_profile_without_touching_targets(
    run, tmp_path, profiles_root, claude_dir
):
    ok(run("profile", "new", "home", "-t", "claude-code"))
    folder = tmp_path / "src" / "x"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# x\n")
    ok(run("add", str(folder), "-p", "home"))

    change = json.loads(
        ok(run("layer", "use", "design-principles", "x", "-p", "home", "--json")).output
    )

    assert change["profile"] == "home" and change["active"] is False
    assert read_yaml(profiles_root, "home")["layers"]["design-principles"][
        "skills"
    ] == ["x"]
    assert not claude_dir.exists()
