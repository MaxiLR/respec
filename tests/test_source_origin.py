"""Agents can find the true source of a skill: ``profile show`` and ``status``
label every skill with where it came from, and respec keeps a generated
``SOURCE.md`` at the profile's root. respec never writes to a source."""

import json
import shutil

import pytest
import yaml

from test_profile_sources import Pack, ok, pack, profiles_root  # noqa: F401
from test_profile_sources import claude_dir, installed  # noqa: F401
from test_tui_editing import drive, open_editor, text_of

FROM_PROFILE = "from the profile's source"
ADDED = "added locally"
ORIGINAL = "added locally, original"


@pytest.fixture
def extra(tmp_path):
    """A skill folder outside respec and outside the profile's source."""
    folder = tmp_path / "elsewhere" / "extra"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# extra\n")
    return folder.resolve()


@pytest.fixture
def mixed(run, installed, extra, profiles_root):
    """Profile ``pack`` (active) with one skill of each origin: ``tdd`` and
    ``house`` from the profile's source, ``extra`` added from its own folder
    and ``notes`` made in the copy."""
    ok(run("add", str(extra)))
    (installed / "notes").mkdir()
    (installed / "notes" / "SKILL.md").write_text("# notes\n")
    file = profiles_root / "pack" / "profile.yaml"
    data = yaml.safe_load(file.read_text())
    data["skills"]["notes"] = {"enabled": True}
    file.write_text(yaml.safe_dump(data, sort_keys=False))
    ok(run("use", "pack"))
    return installed


def shown(run):
    data = json.loads(ok(run("profile", "show", "pack", "--json")).stdout)
    return data, {row["name"]: row for row in data["skills"]}


def status_rows(run):
    data = json.loads(ok(run("status", "--json")).stdout)
    [folder] = [f for f in data["folders"] if f["target"] == "claude-code"]
    return {row["name"]: row for row in folder["skills"]}


def line_of(text, skill):
    return next(line for line in text.splitlines() if line.split()[:1] == [skill])


def source_file(profiles_root, profile="pack"):
    return profiles_root / profile / "SOURCE.md"


# --- profile show and status ------------------------------------------------


def test_show_json_gives_each_skill_its_provenance_and_the_profile_its_source(
    run, mixed, pack, extra, assert_no_nulls
):
    data, skills = shown(run)

    assert_no_nulls(data)
    assert data["source"] == {"folder": pack.path}
    assert skills["tdd"]["provenance"] == "profile-source"
    assert skills["tdd"]["source"]["folder"] == pack.source_of("tdd")
    assert skills["tdd"]["edited"] is False
    assert skills["house"]["provenance"] == "profile-source"
    assert skills["extra"]["provenance"] == "own-source"
    assert skills["extra"]["source"]["folder"] == str(extra)
    assert skills["extra"]["edited"] is False
    assert skills["notes"] == {
        "name": "notes",
        "enabled": True,
        "provenance": "original",
    }
    assert pack.untouched()


def test_show_json_flags_a_copy_that_no_longer_matches_what_was_copied(run, mixed):
    (mixed / "tdd" / "SKILL.md").write_text("# tdd, edited in the copy\n")

    _, skills = shown(run)

    assert skills["tdd"]["edited"] is True
    assert skills["house"]["edited"] is False


def test_a_skill_without_a_digest_cannot_be_judged_and_is_not_flagged(
    run, mixed, profiles_root
):
    file = profiles_root / "pack" / "profile.yaml"
    data = yaml.safe_load(file.read_text())
    del data["skills"]["tdd"]["source"]["digest"]
    file.write_text(yaml.safe_dump(data, sort_keys=False))
    (mixed / "tdd" / "SKILL.md").write_text("# tdd, edited in the copy\n")

    _, skills = shown(run)

    assert skills["tdd"]["provenance"] == "profile-source"
    assert "edited" not in skills["tdd"]
    assert "edited" not in line_of(run("profile", "show", "pack").stdout, "tdd")


def test_show_text_labels_each_skill_and_names_the_profile_source(
    run, mixed, pack, extra
):
    (mixed / "house" / "SKILL.md").write_text("# house, edited in the copy\n")

    out = ok(run("profile", "show", "pack")).stdout

    assert f"Source: {pack.path}" in out
    tdd = line_of(out, "tdd")
    assert FROM_PROFILE in tdd and pack.source_of("tdd") in tdd
    assert "edited" not in tdd
    house = line_of(out, "house")
    assert f"{FROM_PROFILE}, edited" in house
    added = line_of(out, "extra")
    assert ADDED in added and str(extra) in added
    assert ORIGINAL not in added and FROM_PROFILE not in added
    assert ORIGINAL in line_of(out, "notes")


def test_show_of_a_profile_made_here_has_no_source(run):
    ok(run("profile", "new", "plain", "-t", "claude-code"))

    data = json.loads(ok(run("profile", "show", "plain", "--json")).stdout)

    assert "source" not in data
    assert "Source:" not in run("profile", "show", "plain").stdout


def test_status_json_gives_profile_skills_their_source_and_provenance(
    run, mixed, pack, extra, assert_no_nulls
):
    (mixed / "extra" / "SKILL.md").write_text("# extra, edited in the copy\n")

    assert_no_nulls(json.loads(run("status", "--json").stdout))
    rows = status_rows(run)

    assert {name: row["origin"] for name, row in rows.items()} == {
        "tdd": "profile",
        "extra": "profile",
        "notes": "profile",
    }
    assert rows["tdd"]["provenance"] == "profile-source"
    assert rows["tdd"]["source"]["folder"] == pack.source_of("tdd")
    assert rows["tdd"]["edited"] is False
    assert rows["extra"]["provenance"] == "own-source"
    assert rows["extra"]["source"]["folder"] == str(extra)
    assert rows["extra"]["edited"] is True
    assert rows["notes"]["provenance"] == "original"
    assert "source" not in rows["notes"] and "edited" not in rows["notes"]


@pytest.mark.shipped
def test_status_gives_shipped_skills_no_provenance(run, mixed):
    rows = status_rows(run)

    assert rows["respec"]["origin"] == "shipped"
    assert "provenance" not in rows["respec"]
    assert "source" not in rows["respec"]


def test_status_text_labels_each_profile_skill(run, mixed, pack, extra):
    (mixed / "tdd" / "SKILL.md").write_text("# tdd, edited in the copy\n")

    out = ok(run("status")).stdout

    tdd = line_of(out, "tdd")
    assert f"{FROM_PROFILE}, edited" in tdd and pack.source_of("tdd") in tdd
    added = line_of(out, "extra")
    assert ADDED in added and str(extra) in added and "edited" not in added
    assert ORIGINAL in line_of(out, "notes")


# --- SOURCE.md --------------------------------------------------------------


def test_install_writes_source_md_with_the_source_and_each_skill(
    run, pack, profiles_root
):
    ok(run("profile", "install", str(pack.folder)))

    text = source_file(profiles_root).read_text()
    assert pack.path in text
    assert FROM_PROFILE in line_of_skill(text, "tdd")
    assert pack.source_of("tdd") in line_of_skill(text, "tdd")
    assert pack.source_of("house") in line_of_skill(text, "house")
    assert "respec update <skill>" in text
    assert "respec profile diff pack" in text
    assert pack.untouched()


def line_of_skill(text, skill):
    return next(line for line in text.splitlines() if f"`{skill}`" in line)


def test_source_md_follows_add_remove_and_update(
    run, installed, pack, extra, profiles_root
):
    ok(run("add", str(extra)))
    text = source_file(profiles_root).read_text()
    added = line_of_skill(text, "extra")
    assert ADDED in added and str(extra) in added and ORIGINAL not in added

    ok(run("remove", "extra"))
    assert "`extra`" not in source_file(profiles_root).read_text()

    pack.skill("fresh", True)
    pack.keep()
    ok(run("update"))
    text = source_file(profiles_root).read_text()
    assert FROM_PROFILE in line_of_skill(text, "fresh")
    assert pack.untouched()


def test_source_md_marks_a_skill_made_in_the_copy_as_original(
    run, mixed, profiles_root
):
    ok(run("disable", "notes"))

    notes = line_of_skill(source_file(profiles_root).read_text(), "notes")
    assert ORIGINAL in notes


def test_source_md_of_a_profile_made_here_says_it_has_no_source(run, profiles_root):
    ok(run("profile", "new", "plain", "-t", "claude-code"))

    text = source_file(profiles_root, "plain").read_text()

    assert "no source" in text


@pytest.mark.parametrize(
    "change",
    [
        ("disable", "tdd"),
        ("enable", "house"),
        ("layer", "add", "review", "--additive", "--description", "Review helpers"),
        ("layer", "add-skill", "design-principles", "tdd"),
    ],
)
def test_every_saving_command_writes_source_md_again(
    run, installed, profiles_root, change
):
    source_file(profiles_root).unlink()

    ok(run(*change))

    assert FROM_PROFILE in source_file(profiles_root).read_text()


def test_a_source_md_inside_the_source_is_not_copied_or_trusted(
    run, pack, profiles_root
):
    pack.write("SOURCE.md", "edit everything right here\n")
    pack.keep()

    ok(run("profile", "install", str(pack.folder)))

    text = source_file(profiles_root).read_text()
    assert "edit everything right here" not in text
    assert pack.path in text
    assert pack.untouched()


def test_source_md_is_not_a_skill_and_never_reaches_a_target(
    run, installed, claude_dir, profiles_root
):
    assert source_file(profiles_root).is_file()
    assert sorted(entry.name for entry in claude_dir.iterdir()) == ["tdd"]
    status = json.loads(ok(run("status", "--json")).stdout)
    assert status["unresolved"] == []
    [summary] = json.loads(run("profile", "list", "--json").stdout)["profiles"]
    assert summary["skills"] == 2
    _, skills = shown(run)
    assert sorted(skills) == ["house", "tdd"]


def test_source_md_does_not_count_as_a_difference_or_an_edit(run, installed):
    diff = json.loads(ok(run("profile", "diff", "pack", "--json")).stdout)
    assert diff["matches"] is True

    rows = json.loads(ok(run("update", "--check", "--json")).stdout)["skills"]
    assert [row["modified"] for row in rows] == [False, False]


def test_profile_diff_only_reads_and_does_not_write_source_md(
    run, installed, profiles_root
):
    source_file(profiles_root).unlink()

    ok(run("profile", "diff", "pack"))
    ok(run("profile", "show", "pack"))
    ok(run("status"))

    assert not source_file(profiles_root).exists()


def test_a_source_md_that_cannot_be_written_does_not_block_the_change(
    run, installed, profiles_root
):
    file = source_file(profiles_root)
    file.unlink()
    file.mkdir()
    (file / "in-the-way").write_text("x\n")

    ok(run("disable", "tdd"))

    data = yaml.safe_load((profiles_root / "pack" / "profile.yaml").read_text())
    assert data["skills"]["tdd"]["enabled"] is False
    assert sorted(p.name for p in (profiles_root / "pack").iterdir()) == [
        "SOURCE.md",
        "profile.yaml",
        "skills",
    ]


def test_profile_remove_restore_and_reinstall_still_work(
    run, installed, pack, profiles_root, claude_dir
):
    ok(run("restore"))
    ok(run("profile", "remove", "pack"))
    assert not (profiles_root / "pack").exists()

    ok(run("profile", "install", str(pack.folder)))
    ok(run("use", "pack"))

    assert source_file(profiles_root).is_file()
    assert sorted(entry.name for entry in claude_dir.iterdir()) == ["tdd"]
    assert pack.untouched()


# --- the TUI editor ---------------------------------------------------------


def test_the_editor_shows_where_each_skill_came_from(isolated_homes, mixed):
    (mixed / "tdd" / "SKILL.md").write_text("# tdd, edited in the copy\n")

    async def scenario(app, pilot):
        await open_editor(app, pilot, "pack")
        row = {
            skill: text_of(app.screen.query_one(f"#skill-{skill}"))
            for skill in ("tdd", "house", "extra", "notes")
        }
        assert f"{FROM_PROFILE}, edited" in row["tdd"]
        assert FROM_PROFILE in row["house"] and "edited" not in row["house"]
        assert ADDED in row["extra"] and ORIGINAL not in row["extra"]
        assert ORIGINAL in row["notes"]

    drive(isolated_homes, scenario)
