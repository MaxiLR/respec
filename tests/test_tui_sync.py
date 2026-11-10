"""The TUI Sync check: a manual look at the setup and the profiles.

Sync finds unknown entries and edited or replaced copies, exclusive layers
with several enabled skills, and links respec placed that are missing or
broken; it offers the fixes and reports what each one did. Driven headless
through Textual's Pilot against the temporary homes from ``conftest.py``.
"""

import asyncio
import json

import pytest
import yaml

SIZE = (120, 40)


@pytest.fixture
def respec_home(isolated_homes):
    return isolated_homes.respec_home


@pytest.fixture
def claude_dir(isolated_homes):
    return isolated_homes.home / ".claude" / "skills"


def make_profile(respec_home, name, targets, skills, layers=None):
    """``skills`` maps skill name to enabled."""
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill}\n")
    write_yaml(respec_home, name, targets, skills, layers)
    return folder


def write_yaml(respec_home, name, targets, skills, layers=None):
    data = {
        "targets": targets,
        "skills": {skill: {"enabled": on} for skill, on in skills.items()},
    }
    if layers:
        data["layers"] = layers
    path = respec_home / "profiles" / name / "profile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def read_yaml(respec_home, name):
    path = respec_home / "profiles" / name / "profile.yaml"
    return yaml.safe_load(path.read_text())


def enabled(respec_home, name):
    skills = read_yaml(respec_home, name)["skills"]
    return {skill for skill, entry in skills.items() if entry["enabled"]}


def drop_skill(folder, name):
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text("foreign\n")
    return folder / name


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def status_json(run):
    return json.loads(ok(run("status", "--json")).stdout)


def text_of(widget):
    return str(widget.render())


def drive(isolated_homes, scenario):
    from respec.tui import RespecApp

    async def main():
        app = RespecApp(
            respec_home=isolated_homes.respec_home, user_home=isolated_homes.home
        )
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())


async def open_sync(app, pilot, key=True):
    if key:
        await pilot.press("s")
    else:
        await pilot.click("#sync")
    await pilot.pause()
    assert app.screen.query("#sync-summary")


def summary(app):
    return text_of(app.screen.query_one("#sync-summary"))


def log(app):
    return text_of(app.screen.query_one("#sync-log"))


@pytest.fixture
def work(respec_home, run):
    make_profile(respec_home, "work", ["claude-code"], {"s1": True, "s2": True})
    ok(run("use", "work"))


def test_sync_button_is_visible_with_an_icon(isolated_homes):
    async def scenario(app, pilot):
        label = str(app.query_one("#sync").label)
        assert "⟳" in label and "Sync" in label

    drive(isolated_homes, scenario)


def test_nothing_found_says_all_in_sync(isolated_homes, work):
    async def scenario(app, pilot):
        await open_sync(app, pilot, key=False)
        assert "All in sync" in summary(app)
        await pilot.press("escape")
        await pilot.pause()
        assert app.query("#profiles")

    drive(isolated_homes, scenario)


def test_sync_without_any_profile_or_folder_is_in_sync(isolated_homes):
    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)


def test_sync_does_not_watch_the_folders_by_itself(isolated_homes, work, claude_dir):
    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "All in sync" in summary(app)
        drop_skill(claude_dir, "late")
        await pilot.pause(0.3)
        assert "All in sync" in summary(app)
        # Only a manual check sees it.
        await pilot.click("#sync-recheck")
        await pilot.pause()
        assert "1 unknown" in summary(app)

    drive(isolated_homes, scenario)


# --- unknown entries -------------------------------------------------------


def test_unknown_entry_added_to_the_active_profile_through_sync(
    isolated_homes, respec_home, work, claude_dir, run
):
    stray = drop_skill(claude_dir, "stray")

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "1 unknown" in summary(app)
        row = app.screen.query_one("#sync-unknown-0")
        assert str(stray) in text_of(row.query_one(".unknown-path"))
        assert "work" in str(app.screen.query_one("#sync-unknown-0-add").label)
        await pilot.click("#sync-unknown-0-add")
        await pilot.click("#sync-resolve")
        await pilot.pause()
        assert f"Added {stray} to profile 'work'" in log(app)
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert "stray" in enabled(respec_home, "work")
    assert (claude_dir / "stray").is_symlink()
    claude = status_json(run)["folders"][0]
    assert claude["unknown"] == []


def test_unknown_entry_removed_through_sync_is_backed_up_and_reported(
    isolated_homes, respec_home, work, claude_dir
):
    stray = drop_skill(claude_dir, "stray")

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        app.screen.query_one("#sync-unknown-0-choice").focus()
        await pilot.press("right", "enter")  # keyboard: pick remove
        await pilot.pause()
        await pilot.click("#sync-resolve")
        await pilot.pause()
        backups = list((respec_home / "backups").glob("*/claude-code/stray"))
        assert len(backups) == 1
        assert f"Backed up {stray} to {backups[0]} and removed it" in log(app)

    drive(isolated_homes, scenario)

    assert not stray.exists()
    assert "stray" not in read_yaml(respec_home, "work")["skills"]


def test_edited_copy_is_listed_as_an_edited_or_replaced_copy(
    isolated_homes, respec_home, work, claude_dir
):
    (claude_dir / "s1").unlink()
    drop_skill(claude_dir, "s1")

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        meta = text_of(app.screen.query_one("#sync-unknown-0 .unknown-meta"))
        assert "edited or replaced copy" in meta

    drive(isolated_homes, scenario)


def test_add_with_a_layer_conflict_is_refused_and_changes_nothing(
    isolated_homes, respec_home, run, claude_dir
):
    skills = {"d1": True, "d2": False}
    layers = {"design-principles": {"skills": ["d1", "d2"]}}
    make_profile(respec_home, "work", ["claude-code"], skills, layers)
    ok(run("use", "work"))
    write_yaml(respec_home, "work", ["claude-code"], {"d1": True, "d2": True}, layers)
    stray = drop_skill(claude_dir, "stray")

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        await pilot.click("#sync-unknown-0-add")
        await pilot.click("#sync-resolve")
        await pilot.pause()
        assert "cannot adopt into profile 'work'" in log(app)
        assert "1 unknown" in summary(app)

    drive(isolated_homes, scenario)

    assert (stray / "SKILL.md").read_text() == "foreign\n"
    assert "stray" not in read_yaml(respec_home, "work")["skills"]


# --- layer conflicts -------------------------------------------------------


@pytest.fixture
def conflicted(respec_home, run):
    skills = {"d1": True, "d2": False, "d3": False}
    layers = {"design-principles": {"skills": ["d1", "d2", "d3"]}}
    make_profile(respec_home, "work", ["claude-code"], skills, layers)
    make_profile(respec_home, "other", ["agents"], {"o1": True})
    ok(run("use", "work"))
    write_yaml(
        respec_home,
        "work",
        ["claude-code"],
        {"d1": True, "d2": True, "d3": True},
        layers,
    )


def test_layer_conflict_is_listed_and_repaired_keeping_the_chosen_skill(
    isolated_homes, respec_home, conflicted, claude_dir
):
    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "1 layer conflict" in summary(app)
        row = text_of(app.screen.query_one("#sync-conflict-0 .conflict-text"))
        assert "design-principles" in row and "work" in row
        await pilot.click("#sync-conflict-0-keep-1")
        await pilot.click("#sync-conflict-0-repair")
        await pilot.pause()
        assert "Repaired layer 'design-principles'" in log(app)
        assert "kept 'd2'" in log(app) and "disabled 'd1', 'd3'" in log(app)
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"d2"}


def test_conflict_in_an_inactive_profile_is_found_too(
    isolated_homes, respec_home, conflicted
):
    write_yaml(
        respec_home,
        "other",
        ["agents"],
        {"o1": True, "o2": True},
        {"design-principles": {"skills": ["o1", "o2"]}},
    )
    for skill in ("o2",):
        (respec_home / "profiles" / "other" / "skills" / skill).mkdir()

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "2 layer conflicts" in summary(app)
        texts = [text_of(w) for w in app.screen.query(".conflict-text")]
        assert any("'other'" in text for text in texts)

    drive(isolated_homes, scenario)


# --- links -----------------------------------------------------------------


def test_missing_link_is_found_and_relinked(
    isolated_homes, respec_home, work, claude_dir
):
    (claude_dir / "s1").unlink()

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "1 link problem" in summary(app)
        assert "s1" in text_of(app.screen.query_one("#sync-links"))
        assert "missing" in text_of(app.screen.query_one("#sync-links"))
        await pilot.click("#sync-relink")
        await pilot.pause()
        assert "Re-applied profile 'work'" in log(app)
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert (claude_dir / "s1").is_symlink()


def test_broken_link_is_found(isolated_homes, respec_home, work, claude_dir):
    import shutil

    shutil.rmtree(respec_home / "profiles" / "work" / "skills" / "s2")

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        links = text_of(app.screen.query_one("#sync-links"))
        assert "s2" in links and "broken" in links

    drive(isolated_homes, scenario)


def test_skill_enabled_by_hand_but_not_linked_is_found(
    isolated_homes, respec_home, run, claude_dir
):
    make_profile(respec_home, "work", ["claude-code"], {"s1": True, "s2": False})
    ok(run("use", "work"))
    write_yaml(respec_home, "work", ["claude-code"], {"s1": True, "s2": True})

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        links = text_of(app.screen.query_one("#sync-links"))
        assert "s2" in links and "not linked" in links
        await pilot.click("#sync-relink")
        await pilot.pause()

    drive(isolated_homes, scenario)

    assert (claude_dir / "s2").is_symlink()
