"""The Textual TUI: profile list, switching, status panel and the adopt dialog.

Driven headless through Textual's Pilot against the temporary homes from
``conftest.py``; outcomes are checked on disk and through ``respec status``.
"""

import asyncio
import json

import pytest
import yaml

SIZE = (120, 40)


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


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def status_json(run):
    return json.loads(ok(run("status", "--json")).stdout)


def text_of(widget):
    return str(widget.render())


def make_app(isolated_homes):
    from respec.tui import RespecApp

    return RespecApp(
        respec_home=isolated_homes.respec_home, user_home=isolated_homes.home
    )


def drive(isolated_homes, scenario):
    """Run ``scenario(app, pilot)`` against a headless app."""

    async def main():
        app = make_app(isolated_homes)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())


@pytest.fixture
def two_profiles(respec_home, run):
    make_profile(respec_home, "alpha", ["claude-code", "agents"], ["a1", "a2"])
    make_profile(respec_home, "beta", ["oh-my-pi"], ["b1"])
    ok(run("use", "alpha"))


# --- opening the TUI ------------------------------------------------------


@pytest.mark.parametrize("args", [[], ["tui"]])
def test_respec_without_command_or_tui_opens_the_tui(args, run, monkeypatch):
    from respec.tui import RespecApp

    opened = []
    monkeypatch.setattr(RespecApp, "run", lambda self, **kwargs: opened.append(self))

    ok(run(*args))

    assert len(opened) == 1


def test_help_still_lists_commands(run):
    result = ok(run("--help"))
    assert "use" in result.stdout and "tui" in result.stdout


# --- profile list and status panel ----------------------------------------


def test_profile_list_marks_the_active_profile(isolated_homes, two_profiles):
    async def scenario(app, pilot):
        alpha = text_of(app.query_one("#profile-alpha .profile-name"))
        beta = text_of(app.query_one("#profile-beta .profile-name"))
        assert "●" in alpha and "active" in alpha
        assert "●" not in beta and "active" not in beta
        assert "claude-code, agents" in text_of(
            app.query_one("#profile-alpha .profile-meta")
        )

    drive(isolated_homes, scenario)


def test_status_panel_shows_each_target_folder_and_its_items(
    isolated_homes, two_profiles, dirs
):
    async def scenario(app, pilot):
        claude = text_of(app.query_one("#folder-claude-code"))
        agents = text_of(app.query_one("#folder-agents"))
        for panel, target in ((claude, "claude-code"), (agents, "agents")):
            assert str(dirs[target]) in panel
            assert "a1" in panel and "a2" in panel
        assert "alpha" in text_of(app.query_one("#active"))

    drive(isolated_homes, scenario)


def test_empty_home_shows_how_to_start(isolated_homes):
    async def scenario(app, pilot):
        assert "respec profile new" in text_of(app.query_one("#profiles-empty"))
        assert "No active profile" in text_of(app.query_one("#active"))

    drive(isolated_homes, scenario)


# --- activating -----------------------------------------------------------


def test_keyboard_activation_switches_profile(isolated_homes, two_profiles, dirs, run):
    async def scenario(app, pilot):
        app.query_one("#profiles").focus()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert "●" in text_of(app.query_one("#profile-beta .profile-name"))
        assert "beta" in text_of(app.query_one("#feedback"))
        assert "b1" in text_of(app.query_one("#folder-oh-my-pi"))

    drive(isolated_homes, scenario)

    assert status_json(run)["active_profile"] == "beta"
    assert (dirs["oh-my-pi"] / "b1").is_symlink()
    assert not (dirs["claude-code"] / "a1").exists()
    assert not (dirs["agents"] / "a1").exists()


def test_mouse_click_selects_then_activate_button_switches(
    isolated_homes, two_profiles, dirs, run
):
    async def scenario(app, pilot):
        await pilot.click("#profile-beta")
        await pilot.pause()
        # A click only selects; nothing switches yet.
        assert "●" not in text_of(app.query_one("#profile-beta .profile-name"))
        await pilot.click("#activate")
        await pilot.pause()

    drive(isolated_homes, scenario)

    assert status_json(run)["active_profile"] == "beta"
    assert (dirs["oh-my-pi"] / "b1").is_symlink()
    assert not (dirs["claude-code"] / "a1").exists()


def test_activate_button_is_disabled_for_the_active_profile(
    isolated_homes, two_profiles
):
    async def scenario(app, pilot):
        await pilot.click("#profile-alpha")
        await pilot.pause()
        assert app.query_one("#activate").disabled
        await pilot.click("#profile-beta")
        await pilot.pause()
        assert not app.query_one("#activate").disabled

    drive(isolated_homes, scenario)


def test_failed_switch_reports_error_and_changes_nothing(
    isolated_homes, respec_home, two_profiles, run
):
    (respec_home / "profiles" / "beta" / "profile.yaml").write_text("targets: [nope]\n")

    async def scenario(app, pilot):
        assert "invalid" in text_of(app.query_one("#profile-beta .profile-meta"))
        await pilot.click("#profile-beta")
        await pilot.click("#activate")
        await pilot.pause()
        assert "error" in text_of(app.query_one("#feedback")).lower()

    drive(isolated_homes, scenario)

    assert status_json(run)["active_profile"] == "alpha"


# --- unknown entries ------------------------------------------------------


def drop_skill(folder, name):
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text("foreign\n")
    return folder / name


def test_unknown_entry_opens_dialog_and_backup_choice_switches(
    isolated_homes, respec_home, two_profiles, dirs, run
):
    foreign = drop_skill(dirs["claude-code"], "stray")

    async def scenario(app, pilot):
        await pilot.click("#profile-beta")
        await pilot.click("#activate")
        await pilot.pause()
        dialog = app.screen
        assert "stray" in text_of(dialog.query_one("#unknown-0 .unknown-path"))
        assert dialog.query_one("#apply").disabled
        await pilot.click("#unknown-0-backup")
        await pilot.pause()
        assert not dialog.query_one("#apply").disabled
        await pilot.click("#apply")
        await pilot.pause()
        assert "beta" in text_of(app.query_one("#feedback"))

    drive(isolated_homes, scenario)

    assert status_json(run)["active_profile"] == "beta"
    assert not foreign.exists()
    backups = list((respec_home / "backups").glob("*/claude-code/stray/SKILL.md"))
    assert [path.read_text() for path in backups] == ["foreign\n"]


def test_cancelling_the_unknown_dialog_leaves_everything(
    isolated_homes, two_profiles, dirs, run
):
    foreign = drop_skill(dirs["claude-code"], "stray")

    async def scenario(app, pilot):
        await pilot.click("#profile-beta")
        await pilot.click("#activate")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert "cancel" in text_of(app.query_one("#feedback")).lower()

    drive(isolated_homes, scenario)

    report = status_json(run)
    assert report["active_profile"] == "alpha"
    assert (foreign / "SKILL.md").read_text() == "foreign\n"
    assert (dirs["claude-code"] / "a1").is_symlink()


def test_add_choice_adds_entry_to_the_profile_being_activated(
    isolated_homes, respec_home, two_profiles, dirs, run
):
    drop_skill(dirs["agents"], "stray")

    async def scenario(app, pilot):
        app.query_one("#profiles").focus()
        await pilot.press("down", "enter")
        await pilot.pause()
        await pilot.click("#unknown-0-add")
        await pilot.click("#apply")
        await pilot.pause()

    drive(isolated_homes, scenario)

    assert status_json(run)["active_profile"] == "beta"
    added = respec_home / "profiles" / "beta" / "skills" / "stray" / "SKILL.md"
    assert added.read_text() == "foreign\n"
    assert (dirs["oh-my-pi"] / "stray").is_symlink()
    assert not (dirs["agents"] / "stray").exists()


def test_status_panel_flags_unknown_and_adopt_key_keeps_it(
    isolated_homes, two_profiles, dirs, run
):
    drop_skill(dirs["claude-code"], "stray")

    async def scenario(app, pilot):
        assert "unknown" in text_of(app.query_one("#folder-claude-code"))
        await pilot.press("a")
        await pilot.pause()
        await pilot.click("#unknown-0-keep")
        await pilot.click("#apply")
        await pilot.pause()
        panel = text_of(app.query_one("#folder-claude-code"))
        assert "kept" in panel and "unknown" not in panel

    drive(isolated_homes, scenario)

    report = status_json(run)
    claude = next(f for f in report["folders"] if f["target"] == "claude-code")
    assert claude["unknown"] == []
    assert [entry["name"] for entry in claude["unmanaged"]] == ["stray"]
    assert (dirs["claude-code"] / "stray").is_dir()
