"""The TUI Sync check: a manual look at the setup and the profiles.

Sync finds unknown entries and edited or replaced copies, exclusive layers
with several enabled skills, and links respec placed that are missing or
broken; it offers the fixes and reports what each one did. Driven headless
through Textual's Pilot against the temporary homes from ``conftest.py``.
"""

import asyncio
import json
import os

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
        assert "kept 'd2'" in log(app)
        assert "disabled 'd1'" in log(app) and "disabled 'd3'" in log(app)
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


def test_broken_link_without_its_profile_folder_offers_disable(
    isolated_homes, respec_home, work, claude_dir
):
    import shutil

    folder = respec_home / "profiles" / "work" / "skills" / "s2"
    shutil.rmtree(folder)

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        links = text_of(app.screen.query_one("#sync-links"))
        assert "s2" in links and "broken" in links
        assert str(folder) in links
        # Re-applying cannot work while the folder is gone, so it is not offered.
        assert not app.screen.query("#sync-relink")
        await pilot.click("#sync-disable-0")
        await pilot.pause()
        assert "Disabled 's2' in profile 'work'" in log(app)
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"s1"}
    assert not os.path.lexists(claude_dir / "s2")


def test_broken_link_to_an_old_profile_path_is_relinked(
    isolated_homes, respec_home, work, claude_dir
):
    link = claude_dir / "s1"
    link.unlink()
    link.symlink_to(respec_home / "profiles" / "renamed" / "skills" / "s1")

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "broken" in text_of(app.screen.query_one("#sync-links"))
        await pilot.click("#sync-relink")
        await pilot.pause()
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert link.resolve() == (respec_home / "profiles" / "work" / "skills" / "s1")


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


# --- shipped and global skills -----------------------------------------------


def make_global(respec_home, *names):
    for name in names:
        folder = respec_home / "global" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# global {name}\n")
    (respec_home / "config.yaml").write_text(
        yaml.safe_dump({"global": {"skills": list(names)}})
    )


@pytest.fixture
def with_everything(respec_home, run):
    """Profile ``work`` (claude-code) with a global skill, shipped skills on."""
    make_global(respec_home, "gnotes")
    make_profile(respec_home, "work", ["claude-code"], {"s1": True})
    ok(run("use", "work"))


@pytest.mark.shipped
def test_clean_use_with_shipped_and_global_skills_is_in_sync(
    isolated_homes, with_everything, claude_dir
):
    from respec import sync

    assert {"respec", "profile-maker", "gnotes", "s1"} <= set(os.listdir(claude_dir))
    report = sync.check(isolated_homes.respec_home, isolated_homes.home)
    assert report.clean, report

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)


@pytest.mark.shipped
@pytest.mark.parametrize("gone", ["respec", "gnotes"])
def test_reapply_puts_back_a_removed_shipped_or_global_link(
    isolated_homes, with_everything, claude_dir, gone
):
    (claude_dir / gone).unlink()

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert "1 link problem" in summary(app)
        assert gone in text_of(app.screen.query_one("#sync-links"))
        await pilot.click("#sync-relink")
        await pilot.pause()
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert (claude_dir / gone).is_symlink()


@pytest.mark.shipped
def test_global_skill_listed_by_hand_but_not_linked_is_found(
    isolated_homes, respec_home, with_everything, claude_dir
):
    (respec_home / "global" / "skills" / "later").mkdir()
    (respec_home / "global" / "skills" / "later" / "SKILL.md").write_text("# l\n")
    (respec_home / "config.yaml").write_text(
        yaml.safe_dump({"global": {"skills": ["gnotes", "later"]}})
    )

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        links = text_of(app.screen.query_one("#sync-links"))
        assert "later" in links and "not linked" in links
        await pilot.click("#sync-relink")
        await pilot.pause()
        assert "All in sync" in summary(app)

    drive(isolated_homes, scenario)

    assert (claude_dir / "later").is_symlink()


@pytest.mark.shipped
@pytest.mark.parametrize("name", ["respec", "gnotes"])
def test_entry_named_like_a_shipped_or_global_skill_can_only_be_removed(
    isolated_homes, with_everything, claude_dir, name
):
    (claude_dir / name).unlink()
    drop_skill(claude_dir, name)

    async def scenario(app, pilot):
        await open_sync(app, pilot)
        assert app.screen.query("#sync-unknown-0-remove")
        assert not app.screen.query("#sync-unknown-0-add")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("a")  # the adopt dialog offers the same
        await pilot.pause()
        assert app.screen.query("#unknown-0-remove")
        assert not app.screen.query("#unknown-0-add")
        await pilot.click("#unknown-0-remove")
        await pilot.click("#apply")
        await pilot.pause()

    drive(isolated_homes, scenario)

    # respec links its own skill there again.
    assert (claude_dir / name).is_symlink()


@pytest.mark.shipped
def test_shipped_and_global_skills_are_marked_in_the_tui(
    isolated_homes, with_everything
):
    async def scenario(app, pilot):
        panel = text_of(app.query_one("#folder-claude-code"))
        lines = {line.split()[1]: line for line in panel.splitlines()[1:]}
        assert "shipped" in lines["respec"] and "global" in lines["gnotes"]
        assert "shipped" not in lines["s1"] and "global" not in lines["s1"]
        await pilot.press("e")
        await pilot.pause()
        lasting = text_of(app.screen.query_one("#lasting .section-intro"))
        assert "respec" in lasting and "gnotes" in lasting

    drive(isolated_homes, scenario)
