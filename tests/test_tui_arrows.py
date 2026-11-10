"""Arrow-key navigation in the TUI: the arrows move between controls.

Driven headless through Textual's Pilot against the temporary homes from
``conftest.py``.
"""

import asyncio

import pytest
import yaml

SIZE = (120, 40)


def make_profile(respec_home, name, targets, skills, layers=None):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill}\n")
    data = {
        "targets": targets,
        "skills": {skill: {"enabled": skill != "d2"} for skill in skills},
    }
    if layers:
        data["layers"] = layers
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


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


def focused_id(app):
    return app.focused.id if app.focused is not None else None


@pytest.fixture
def two_profiles(isolated_homes, run):
    home = isolated_homes.respec_home
    make_profile(home, "alpha", ["claude-code"], ["a1"])
    make_profile(home, "beta", ["claude-code"], ["b1"])
    assert run("use", "alpha").exit_code == 0


def test_right_and_left_move_between_the_profile_list_and_the_buttons(
    isolated_homes, two_profiles
):
    async def scenario(app, pilot):
        assert focused_id(app) == "profiles"
        # Activate is skipped: the highlighted profile is already active.
        await pilot.press("right")
        assert focused_id(app) == "edit"
        await pilot.press("right")
        assert focused_id(app) == "new"
        await pilot.press("left", "left")
        assert focused_id(app) == "profiles"

    drive(isolated_homes, scenario)


def test_down_and_up_move_between_buttons(isolated_homes, two_profiles):
    async def scenario(app, pilot):
        app.query_one("#edit").focus()
        await pilot.pause()
        await pilot.press("down")
        assert focused_id(app) == "new"
        await pilot.press("up")
        assert focused_id(app) == "edit"

    drive(isolated_homes, scenario)


def test_down_past_the_last_profile_leaves_the_list_and_up_returns(
    isolated_homes, two_profiles
):
    async def scenario(app, pilot):
        profiles = app.query_one("#profiles")
        assert profiles.index == 0
        await pilot.press("down")
        assert focused_id(app) == "profiles" and profiles.index == 1
        await pilot.press("down")
        assert focused_id(app) == "activate"
        await pilot.press("up")
        assert focused_id(app) == "profiles" and profiles.index == 1

    drive(isolated_homes, scenario)


def test_arrows_move_between_fields_of_a_dialog(isolated_homes, two_profiles):
    async def scenario(app, pilot):
        await pilot.press("n")
        await pilot.pause()
        assert focused_id(app) == "new-name"
        await pilot.press("down")
        first_target = app.focused
        assert type(first_target).__name__ == "Checkbox"
        await pilot.press("space", "up")
        assert focused_id(app) == "new-name"
        assert first_target.value is True

    drive(isolated_homes, scenario)


def test_arrows_leave_a_choice_group_at_its_ends(isolated_homes, run):
    make_profile(
        isolated_homes.respec_home,
        "work",
        ["claude-code"],
        ["d1", "d2", "plain"],
        layers={"design-principles": {"skills": ["d1", "d2"]}},
    )
    run("use", "work")

    async def scenario(app, pilot):
        await pilot.press("e")
        await pilot.pause()
        radios = app.screen.query_one("#layer-design-principles")
        radios.focus()
        await pilot.pause()
        # Three choices (d1, d2, None): two presses reach the last one.
        await pilot.press("down", "down")
        assert app.focused is radios
        await pilot.press("down")
        assert app.focused is not radios
        after = app.focused
        await pilot.press("up")
        assert app.focused is radios
        await pilot.press("up", "up", "up")
        assert app.focused is not radios and app.focused is not after

    drive(isolated_homes, scenario)

    data = yaml.safe_load(
        (isolated_homes.respec_home / "profiles" / "work" / "profile.yaml").read_text()
    )
    enabled = {name for name, meta in data["skills"].items() if meta["enabled"]}
    # Moving through the choices selects nothing.
    assert enabled == {"d1", "plain"}
