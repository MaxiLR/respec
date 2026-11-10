"""Interruption safety: every multi-step change is journaled in state.json, and
the next respec command finishes or rolls back a change that was cut short.

Failures are injected at every step boundary through ``journal._fault`` (the
seam :func:`respec.journal.checkpoint` calls), raising an exception that is not
an ``Exception`` so it behaves like a kill: nothing on the way handles it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from respec import journal, profiles, switch, unknown
from respec.state import load_state


class Crash(BaseException):
    """Stands for the process being killed at a step boundary."""


def make_profile(respec_home, name, targets, skills):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill} of {name}\n")
    data = {"targets": targets, "skills": {s: {"enabled": True} for s in skills}}
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def count_points(monkeypatch, action):
    """Run ``action`` once and return the step boundaries it passed."""
    seen: list[str] = []
    monkeypatch.setattr(journal, "_fault", seen.append)
    action()
    monkeypatch.setattr(journal, "_fault", lambda name: None)
    return seen


def crash_at(monkeypatch, index):
    calls: list[str] = []

    def fault(name):
        calls.append(name)
        if len(calls) == index:
            raise Crash(name)

    monkeypatch.setattr(journal, "_fault", fault)


def no_faults(monkeypatch):
    monkeypatch.setattr(journal, "_fault", lambda name: None)


def fresh_homes(tmp_path, monkeypatch, label):
    """New, empty homes for one run of a matrix (the autouse ones stay unused)."""
    home = tmp_path / label / "home"
    respec_home = tmp_path / label / "respec-home"
    home.mkdir(parents=True)
    respec_home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RESPEC_HOME", str(respec_home))
    monkeypatch.setenv("RESPEC_USER_HOME", str(home))
    return home, respec_home


def payload(result, code=0):
    assert result.exit_code == code, result.output
    return json.loads(result.stdout)


def interrupted_warnings(data):
    return [w for w in data["warnings"] if w["type"] == journal.WARNING]


def entries(folder):
    if not folder.exists():
        return []
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def assert_consistent(respec_home, expected, extra=None, everywhere=()):
    """No journal; each owned folder holds exactly the active profile's skills
    (in its targets), ``everywhere`` (shipped skills, while a profile is active)
    and the user's own ``extra`` entries ({target: names}); every record is
    still what respec placed."""
    extra = extra or {}
    state = load_state(respec_home)
    assert state.journal is None
    active = state.active_profile
    assert active in expected, active
    targets = profiles.load_profile(respec_home, active).targets if active else ()
    for target, owned in state.owned.items():
        wanted = list(extra.get(target, []))
        if active is not None:
            wanted += list(everywhere)
            if target in targets:
                wanted += expected[active]
        assert entries(Path(owned.skills_dir)) == sorted(wanted), (target, active)
    for item in state.installed:
        assert unknown.is_managed(respec_home, item), item
    names = sorted(e.name for e in unknown.find_unknown(respec_home, state))
    assert names == sorted(n for t in state.owned for n in extra.get(t, []))


MINE = {"claude-code": ["mine"]}


# --- use ---------------------------------------------------------------------


def two_profiles(respec_home, home):
    make_profile(respec_home, "a", ["claude-code", "agents"], ["tdd", "lint"])
    make_profile(respec_home, "b", ["claude-code", "agents"], ["lint", "docs"])
    mine = home / ".claude" / "skills" / "mine"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine\n")


PROFILES = {"a": ["lint", "tdd"], "b": ["docs", "lint"]}


def test_interrupted_switch_is_journaled_and_reported_by_status(
    run, isolated_homes, monkeypatch
):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    points = count_points(monkeypatch, lambda: switch.use(respec_home, home, "b")) + [
        "end"
    ]
    assert run("use", "a").exit_code == 0
    # Stop right after the first install of the new profile.
    index = next(i for i, name in enumerate(points) if name == "install:start") + 2
    crash_at(monkeypatch, index)

    with pytest.raises(Crash):
        switch.use(respec_home, home, "b")
    no_faults(monkeypatch)

    state = json.loads((respec_home / "state.json").read_text())
    assert state["journal"]["operation"] == "use"
    assert state["journal"]["profile"] == "b"
    assert state["journal"]["previous"] == "a"
    data = payload(run("status", "--json"))
    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "pending"
    assert warning["operation"] == "use"
    assert "switch to profile 'b'" in warning["message"]
    text = run("status")
    assert "switch to profile 'b'" in text.output
    assert "was interrupted" in text.output
    # status only reads: the journal is still there.
    assert load_state(respec_home).journal is not None


@pytest.mark.parametrize("start", [None, "a"])
def test_switch_interrupted_at_every_step_recovers_consistently(
    run, tmp_path, monkeypatch, start
):
    home, respec_home = fresh_homes(tmp_path, monkeypatch, "count")
    two_profiles(respec_home, home)
    if start:
        assert run("use", start).exit_code == 0
    total = len(count_points(monkeypatch, lambda: switch.use(respec_home, home, "b")))
    assert total > 5

    for index in range(1, total + 1):
        home, respec_home = fresh_homes(tmp_path, monkeypatch, f"crash-{index}")
        two_profiles(respec_home, home)
        if start:
            assert run("use", start).exit_code == 0
        crash_at(monkeypatch, index)
        with pytest.raises(Crash):
            switch.use(respec_home, home, "b")
        no_faults(monkeypatch)
        assert load_state(respec_home).journal is not None, index

        data = payload(run("recover", "--json"))

        (warning,) = interrupted_warnings(data)
        assert warning["outcome"] in ("finished", "rolled-back")
        expected = {"b": PROFILES["b"], start: PROFILES.get(start, [])}
        assert_consistent(respec_home, expected, extra=MINE)
        assert data["active_profile"] == load_state(respec_home).active_profile
        # The user's own entry is never lost: in place, and in the backup.
        assert (home / ".claude" / "skills" / "mine" / "SKILL.md").read_text() == (
            "mine\n"
        )


def test_any_changing_command_recovers_first_and_reports_it(
    run, isolated_homes, monkeypatch
):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    make_profile(respec_home, "c", ["claude-code"], ["solo"])
    assert run("use", "a").exit_code == 0
    points = count_points(monkeypatch, lambda: switch.use(respec_home, home, "b"))
    assert run("use", "a").exit_code == 0
    crash_at(monkeypatch, points.index("install:start") + 1)
    with pytest.raises(Crash):
        switch.use(respec_home, home, "b")
    no_faults(monkeypatch)

    result = run("use", "c", "--json")

    data = payload(result)
    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "finished"
    assert warning["operation"] == "use"
    assert data["active_profile"] == "c"
    assert load_state(respec_home).journal is None
    assert entries(home / ".claude" / "skills") == ["mine", "solo"]
    text_run = run("status")
    assert "interrupted" not in text_run.output


def test_recover_rollback_activates_the_previous_profile(
    run, isolated_homes, monkeypatch
):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    points = count_points(monkeypatch, lambda: switch.use(respec_home, home, "b"))
    assert run("use", "a").exit_code == 0
    crash_at(monkeypatch, points.index("install:start") + 1)
    with pytest.raises(Crash):
        switch.use(respec_home, home, "b")
    no_faults(monkeypatch)

    data = payload(run("recover", "--rollback", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "rolled-back"
    assert data["active_profile"] == "a"
    assert_consistent(respec_home, {"a": PROFILES["a"]}, extra=MINE)


def test_recover_without_a_journal_says_so(run):
    data = payload(run("recover", "--json"))
    assert interrupted_warnings(data) == []
    assert data["recovered"] is False
    assert "Nothing to recover" in run("recover").output


def test_a_partial_copy_left_by_an_install_is_set_aside_not_deleted(
    run, isolated_homes, monkeypatch
):
    """When links are refused, skills are copied; a copy cut short is moved to
    a backup run, and the switch is finished."""
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0

    def refuse(*args, **kwargs):
        raise OSError("links refused")

    monkeypatch.setattr(os, "symlink", refuse)
    points = count_points(monkeypatch, lambda: switch.use(respec_home, home, "b"))
    assert run("use", "a").exit_code == 0
    index = points.index("install:start") + 1
    calls: list[str] = []

    def fault(name):
        calls.append(name)
        if len(calls) == index:
            # The copy got as far as an empty folder when the process died.
            raise Crash(name)

    monkeypatch.setattr(journal, "_fault", fault)
    with pytest.raises(Crash):
        switch.use(respec_home, home, "b")
    no_faults(monkeypatch)
    step = load_state(respec_home).journal["pending"]
    half = Path(step["path"])
    half.mkdir(parents=True)
    (half / "partial").write_text("half\n")

    data = payload(run("recover", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "finished"
    (moved,) = warning["set_aside"]
    assert (Path(moved) / "partial").read_text() == "half\n"
    assert_consistent(respec_home, {"b": PROFILES["b"]}, extra=MINE)


@pytest.mark.shipped
def test_killed_switch_is_finished_by_the_next_command(run, isolated_homes):
    """A real kill (os._exit) in the middle of a switch, shipped skills included."""
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    script = (
        "import os, sys\n"
        "from respec import journal\n"
        "seen = []\n"
        "def fault(name):\n"
        "    seen.append(name)\n"
        "    if name == 'install:start' and seen.count(name) == 2:\n"
        "        os._exit(9)\n"
        "journal._fault = fault\n"
        "from respec.cli import app\n"
        "app(['use', 'b'])\n"
    )
    killed = subprocess.run([sys.executable, "-c", script], env=os.environ.copy())
    assert killed.returncode == 9
    assert load_state(respec_home).journal is not None

    data = payload(run("status", "--json"))
    assert interrupted_warnings(data)[0]["outcome"] == "pending"
    data = payload(run("recover", "--json"))

    assert interrupted_warnings(data)[0]["outcome"] == "finished"
    assert_consistent(
        respec_home,
        {"b": PROFILES["b"]},
        extra=MINE,
        everywhere=["profile-maker", "respec"],
    )


# --- matrix helper -------------------------------------------------------------


def every_step(tmp_path, monkeypatch, label, setup, action, check):
    """Crash ``action`` at each of its step boundaries, each time in fresh
    homes prepared by ``setup``, and ``check`` the recovery. Returns how many
    boundaries there were."""
    home, respec_home = fresh_homes(tmp_path, monkeypatch, f"{label}-count")
    context = setup(home, respec_home)
    total = len(count_points(monkeypatch, lambda: action(home, respec_home, context)))
    assert total > 0
    for index in range(1, total + 1):
        home, respec_home = fresh_homes(tmp_path, monkeypatch, f"{label}-{index}")
        context = setup(home, respec_home)
        crash_at(monkeypatch, index)
        with pytest.raises(Crash):
            action(home, respec_home, context)
        no_faults(monkeypatch)
        assert load_state(respec_home).journal is not None, index
        check(home, respec_home, context, index)
    return total


def found_with(root, text):
    return [
        path
        for path in Path(root).rglob("*")
        if path.is_file() and not path.is_symlink() and path.read_text() == text
    ]


# --- restore -------------------------------------------------------------------


def test_restore_interrupted_at_every_step_is_finished(run, tmp_path, monkeypatch):
    from respec import restore

    def setup(home, respec_home):
        two_profiles(respec_home, home)
        assert run("use", "a").exit_code == 0
        stray = home / ".claude" / "skills" / "stray"
        stray.mkdir()
        (stray / "SKILL.md").write_text("stray content\n")

    def action(home, respec_home, context):
        restore.restore(respec_home, home, overwrite=True)

    def check(home, respec_home, context, index):
        data = payload(run("recover", "--json"))
        (warning,) = interrupted_warnings(data)
        assert warning["outcome"] == "finished", index
        state = load_state(respec_home)
        assert state.journal is None and not state.owned and not state.installed
        assert entries(home / ".claude" / "skills") == ["mine"]
        assert not (home / ".agents" / "skills").exists()
        assert found_with(respec_home / "backups", "stray content\n"), index

    assert every_step(tmp_path, monkeypatch, "restore", setup, action, check) > 5


def test_restore_command_finishes_an_interrupted_restore(
    run, isolated_homes, monkeypatch
):
    from respec import restore

    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    crash_at(monkeypatch, 4)
    with pytest.raises(Crash):
        restore.restore(respec_home, home)
    no_faults(monkeypatch)

    data = payload(run("restore", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["operation"] == "restore"
    assert warning["outcome"] == "finished"
    assert entries(home / ".claude" / "skills") == ["mine"]
    assert not load_state(respec_home).owned


def test_a_restore_that_removed_skills_cannot_be_rolled_back(
    run, isolated_homes, monkeypatch
):
    from respec import restore

    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    points = count_points(monkeypatch, lambda: None)
    assert points == []
    calls: list[str] = []

    def fault(name):
        calls.append(name)
        if name == "removed":
            raise Crash(name)

    monkeypatch.setattr(journal, "_fault", fault)
    with pytest.raises(Crash):
        restore.restore(respec_home, home)
    no_faults(monkeypatch)

    data = payload(run("recover", "--rollback", "--json"), code=1)

    assert "cannot be rolled back" in data["error"]
    assert data["recovered"] is False
    assert load_state(respec_home).journal is not None
    assert interrupted_warnings(data)[0]["outcome"] == "pending"


# --- layer repair outside a full refresh ---------------------------------------


def test_layer_repair_links_interrupted_at_every_step(run, tmp_path, monkeypatch):
    from respec import layers

    def setup(home, respec_home):
        make_profile(respec_home, "work", ["claude-code"], ["a", "b", "c"])
        assert run("use", "work").exit_code == 0
        path = respec_home / "profiles" / "work" / "profile.yaml"
        data = yaml.safe_load(path.read_text())
        data["layers"] = {"design-principles": {"skills": ["a", "b"]}}
        path.write_text(yaml.safe_dump(data))
        # A hand-made folder in place of c's link refuses the full refresh,
        # so the repair only changes the links of a and b.
        claude = home / ".claude" / "skills"
        (claude / "c").unlink()
        (claude / "c").mkdir()
        (claude / "c" / "SKILL.md").write_text("hand-made c\n")

    def action(home, respec_home, context):
        layers.repair(respec_home, home, "design-principles", keep="a")

    def check(home, respec_home, context, index):
        data = payload(run("recover", "--json"))
        (warning,) = interrupted_warnings(data)
        assert warning["outcome"] == "finished"
        state = load_state(respec_home)
        assert state.journal is None
        claude = home / ".claude" / "skills"
        assert (claude / "c" / "SKILL.md").read_text() == "hand-made c\n"
        enabled = {
            name
            for name, entry in profiles.load_profile(respec_home, "work").skills.items()
            if entry.enabled
        }
        linked = {i.name for i in state.installed if unknown.is_managed(respec_home, i)}
        assert linked == enabled - {"c"}, index
        assert entries(claude) == sorted(linked | {"c"}), index

    assert every_step(tmp_path, monkeypatch, "repair", setup, action, check) > 3


# --- adopt -----------------------------------------------------------------------


def test_adopt_interrupted_at_every_step_loses_nothing(run, tmp_path, monkeypatch):
    from respec import adopt

    def setup(home, respec_home):
        make_profile(respec_home, "work", ["claude-code"], ["tdd"])
        assert run("use", "work").exit_code == 0
        claude = home / ".claude" / "skills"
        for name, text in (("newone", "new content\n"), ("junk", "junk content\n")):
            (claude / name).mkdir()
            (claude / name / "SKILL.md").write_text(text)
        # An edited copy of the profile's own skill (added: it overwrites the
        # profile's copy, which goes to a backup run first).
        (claude / "tdd").unlink()
        (claude / "tdd").mkdir()
        (claude / "tdd" / "SKILL.md").write_text("edited tdd\n")

    choices = {"newone": "add", "junk": "remove", "tdd": "add"}

    def action(home, respec_home, context):
        adopt.adopt(respec_home, home, lambda entry: choices[entry.name])

    def check(home, respec_home, context, index):
        data = payload(run("recover", "--json"))
        (warning,) = interrupted_warnings(data)
        assert warning["outcome"] == "finished"
        state = load_state(respec_home)
        assert state.journal is None
        waiting = unknown.find_unknown(respec_home, state)
        replaced = {e.path for e in waiting if e.replaced}
        for item in state.installed:
            # A record that no longer holds respec's link is reported as an
            # edited or replaced copy, still waiting for a choice.
            assert unknown.is_managed(respec_home, item) or item.path in replaced
        work = profiles.load_profile(respec_home, "work")
        for skill in work.skills:
            assert (work.path / "skills" / skill / "SKILL.md").is_file(), index
        skills_dir = work.path / "skills"
        assert not list(skills_dir.glob(".*.respec-*")), index
        # Every content is somewhere: in place, in the profile or in a backup.
        root = home.parent
        for text in ("new content\n", "junk content\n", "edited tdd\n"):
            assert found_with(root, text), (index, text)
        assert found_with(root, "# tdd of work\n"), index
        # Whatever is still in the folder is either respec's or unknown.
        assert {e.name for e in waiting} <= {"newone", "junk", "tdd"}, index

    assert every_step(tmp_path, monkeypatch, "adopt", setup, action, check) > 6


# --- links outside a switch ------------------------------------------------------


def test_relink_of_lasting_skills_interrupted_is_finished(run, tmp_path, monkeypatch):
    def setup(home, respec_home):
        make_profile(respec_home, "work", ["claude-code"], ["tdd"])
        folder = respec_home / "global" / "skills" / "shared"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("shared\n")
        config = {"global": {"skills": ["shared"]}}
        (respec_home / "config.yaml").write_text(yaml.safe_dump(config))
        assert run("use", "work").exit_code == 0
        (home / ".claude" / "skills" / "shared").unlink()

    def action(home, respec_home, context):
        switch.relink_lasting(respec_home, home)

    def check(home, respec_home, context, index):
        payload(run("recover", "--json"))
        assert_consistent(respec_home, {"work": ["shared", "tdd"]})

    assert every_step(tmp_path, monkeypatch, "relink", setup, action, check) > 1


# --- TUI -------------------------------------------------------------------------


def drive(respec_home, home, scenario):
    import asyncio

    from respec.tui import RespecApp

    async def main():
        app = RespecApp(respec_home=respec_home, user_home=home)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())


@pytest.fixture
def cut_switch(run, isolated_homes, monkeypatch):
    """Profile 'a' was active when a switch to 'b' was cut short mid-install."""
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    make_profile(respec_home, "c", ["claude-code"], ["solo"])
    assert run("use", "a").exit_code == 0
    points = count_points(monkeypatch, lambda: switch.use(respec_home, home, "b"))
    assert run("use", "a").exit_code == 0
    crash_at(monkeypatch, points.index("install:start") + 1)
    with pytest.raises(Crash):
        switch.use(respec_home, home, "b")
    no_faults(monkeypatch)
    return home, respec_home


def test_tui_refuses_to_switch_while_a_change_waits(cut_switch):
    home, respec_home = cut_switch
    before = (respec_home / "state.json").read_text()

    async def scenario(app, pilot):
        feedback = str(app.query_one("#feedback").render())
        assert "interrupted" in feedback and "Sync" in feedback
        app.activate("c")
        await pilot.pause()
        feedback = str(app.query_one("#feedback").render())
        assert "interrupted" in feedback

    drive(respec_home, home, scenario)
    assert (respec_home / "state.json").read_text() == before


@pytest.mark.parametrize(
    ("button", "active", "outcome"),
    [("#sync-finish", "b", "Finished"), ("#sync-rollback", "a", "Rolled back")],
)
def test_tui_sync_reports_and_resolves_an_interrupted_switch(
    cut_switch, button, active, outcome
):
    home, respec_home = cut_switch

    async def scenario(app, pilot):
        await pilot.press("s")
        await pilot.pause()
        summary = str(app.screen.query_one("#sync-summary").render())
        assert "interrupted" in summary
        message = str(app.screen.query_one("#sync-interrupted").render())
        assert "switch to profile 'b'" in message
        # Nothing else is offered until it is resolved.
        assert not app.screen.query("#sync-relink")
        await pilot.click(button)
        await pilot.pause()
        assert outcome in str(app.screen.query_one("#sync-log").render())
        summary = str(app.screen.query_one("#sync-summary").render())
        assert summary == "Found 1 unknown entry."  # 'mine', the user's own

    drive(respec_home, home, scenario)
    assert_consistent(respec_home, {active: PROFILES[active]}, extra=MINE)


# --- JSON ------------------------------------------------------------------------


def test_refused_use_reports_the_profile_still_active(run, isolated_homes):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    (home / ".claude" / "skills" / "docs").mkdir()

    data = payload(run("use", "b", "--json"), code=1)

    assert data["active_profile"] == "a"
    assert "error" in data


def test_interrupted_warnings_have_no_undocumented_nulls(
    run, cut_switch, assert_no_nulls
):
    assert_no_nulls(payload(run("status", "--json")))
    assert_no_nulls(payload(run("profile", "list", "--json")))
    assert_no_nulls(payload(run("recover", "--json")))
    assert_no_nulls(payload(run("recover", "--json")))


def test_editing_the_profile_being_switched_to_finishes_the_switch_first(
    run, cut_switch
):
    home, respec_home = cut_switch

    data = payload(run("disable", "docs", "-p", "b", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "finished"
    assert_consistent(respec_home, {"b": ["lint"]}, extra=MINE)
