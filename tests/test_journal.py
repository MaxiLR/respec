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
        repaired = "b" not in {
            n
            for n, e in profiles.load_profile(respec_home, "work").skills.items()
            if e.enabled
        }
        assert warning["outcome"] == ("finished" if repaired else "rolled-back"), index
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
        assert warning["outcome"] in ("finished", "rolled-back"), index
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


# --- review 1 ------------------------------------------------------------------


def adopt_setup(run, home, respec_home):
    make_profile(respec_home, "work", ["claude-code"], ["tdd"])
    assert run("use", "work").exit_code == 0
    claude = home / ".claude" / "skills"
    for name, text in (("newone", "new content\n"), ("junk", "junk content\n")):
        (claude / name).mkdir()
        (claude / name / "SKILL.md").write_text(text)
    (claude / "tdd").unlink()
    (claude / "tdd").mkdir()
    (claude / "tdd" / "SKILL.md").write_text("edited tdd\n")


def test_adopt_killed_at_every_step_loses_nothing(run, killed, tmp_path, monkeypatch):
    """Real SIGKILLs (no handler runs), then a retry of the same choices."""
    index = 0
    while True:
        index += 1
        home, respec_home = fresh_homes(tmp_path, monkeypatch, f"kill-adopt-{index}")
        adopt_setup(run, home, respec_home)
        args = ("adopt", "--add", "newone", "--add", "tdd", "--remove", "junk")
        if not killed("#", index, *args):
            break
        data = payload(run("recover", "--json"))
        (warning,) = interrupted_warnings(data)
        assert warning["outcome"] in ("finished", "rolled-back")
        for text in ("new content\n", "junk content\n", "edited tdd\n"):
            assert found_with(home.parent, text), (index, text)
        # Nothing left behind blocks the same choices for what still waits.
        choices = {"newone": "--add", "tdd": "--add", "junk": "--remove"}
        state = load_state(respec_home)
        waiting = [e.name for e in unknown.find_unknown(respec_home, state)]
        retry_args = [x for name in waiting for x in (choices[name], name)]
        if retry_args:
            retry = run("adopt", *retry_args)
            assert retry.exit_code == 0, (index, retry.output)
        skills = respec_home / "profiles" / "work" / "skills"
        assert not list(skills.glob(".*.respec-*")), index
        assert (skills / "tdd" / "SKILL.md").read_text() == "edited tdd\n", index
        assert (skills / "newone" / "SKILL.md").read_text() == "new content\n"
        assert found_with(respec_home / "backups", "junk content\n"), index
    assert index > 8


def test_staging_folders_of_a_cut_overwrite_are_set_aside_not_left_blocking(
    run, isolated_homes
):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    adopt_setup(run, home, respec_home)
    # As if killed inside the overwrite while the staged copy was being made.
    from respec import adopt

    staged = respec_home / "profiles" / "work" / "skills" / f".tdd{adopt.STAGED}"
    state = load_state(respec_home)
    state.journal = {
        "operation": "adopt",
        "started_at": "2026-11-10T00:00:00+00:00",
        "profile": "work",
        "pending": {
            "step": "adopt",
            "choice": "add",
            "stage": "copy",
            "path": str(home / ".claude" / "skills" / "tdd"),
            "name": "tdd",
            "profile": "work",
            "overwrite": True,
        },
    }
    from respec.state import save_state

    save_state(respec_home, state)
    staged.mkdir()
    (staged / "SKILL.md").write_text("half")

    data = payload(run("recover", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "rolled-back"
    (moved,) = warning["set_aside"]
    assert (Path(moved) / "SKILL.md").read_text() == "half"
    assert not staged.exists()
    assert run("adopt", "--add", "tdd").exit_code == 0


def test_a_repair_cut_before_saving_profile_yaml_says_rolled_back(
    run, isolated_homes, monkeypatch
):
    from respec import layers

    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    make_profile(respec_home, "work", ["claude-code"], ["a", "b", "c"])
    assert run("use", "work").exit_code == 0
    path = respec_home / "profiles" / "work" / "profile.yaml"
    data = yaml.safe_load(path.read_text())
    data["layers"] = {"design-principles": {"skills": ["a", "b"]}}
    path.write_text(yaml.safe_dump(data))
    (home / ".claude" / "skills" / "c").unlink()
    (home / ".claude" / "skills" / "c").mkdir()
    crash_at(monkeypatch, 1)  # links:begin
    with pytest.raises(Crash):
        layers.repair(respec_home, home, "design-principles", keep="a")
    no_faults(monkeypatch)

    data = payload(run("recover", "--rollback", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "rolled-back"
    assert "had not been changed" in warning["message"]
    assert "finished" not in warning["message"].lower()


def test_a_disable_killed_after_saving_profile_yaml_is_put_in_line(
    run, killed, isolated_homes
):
    respec_home = isolated_homes.respec_home
    make_profile(respec_home, "work", ["claude-code"], ["tdd", "lint"])
    assert run("use", "work").exit_code == 0

    assert killed("after-save-profile", 1, "disable", "lint")
    data = payload(run("status", "--json"))
    assert interrupted_warnings(data)[0]["outcome"] == "pending"
    data = payload(run("recover", "--json"))

    assert interrupted_warnings(data)[0]["outcome"] == "finished"
    assert_consistent(respec_home, {"work": ["tdd"]})


@pytest.mark.shipped
def test_a_switch_cut_while_refreshing_shipped_skills_heals_them(
    run, killed, isolated_homes
):
    from respec import global_skills

    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    shipped = global_skills.shipped_dir(respec_home) / "respec"
    (shipped / "SKILL.md").write_text("outdated\n")
    # Simulate the kill inside refresh_shipped: the old copy is gone and the
    # staged one is half made, while the switch is still in 'prepare'.
    import shutil

    shutil.rmtree(shipped)
    (shipped.parent / ".respec.new").mkdir()
    state = load_state(respec_home)
    state.journal = {
        "operation": "use",
        "started_at": "2026-11-10T00:00:00+00:00",
        "profile": "b",
        "previous": "a",
        "phase": "prepare",
    }
    from respec.state import save_state

    save_state(respec_home, state)

    payload(run("recover", "--json"))

    assert (shipped / "SKILL.md").is_file()
    assert "outdated" not in (shipped / "SKILL.md").read_text()
    link = home / ".claude" / "skills" / "respec"
    assert (link / "SKILL.md").is_file()


def test_restore_of_another_backup_waits_for_the_interrupted_one(
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
    other = next((respec_home / "backups").iterdir()).name

    result = run("restore", other)

    assert result.exit_code == 1
    assert "interrupted restore" in result.output
    assert load_state(respec_home).journal is not None


def test_an_unknown_journal_can_be_discarded_with_rollback(run, isolated_homes):
    respec_home = isolated_homes.respec_home
    from respec.state import State, save_state

    save_state(
        respec_home,
        State(journal={"operation": "teleport", "started_at": "then"}),
    )

    refused = run("recover", "--json")
    assert refused.exit_code == 1
    assert "--rollback" in json.loads(refused.stdout)["error"]

    data = payload(run("recover", "--rollback", "--json"))

    assert interrupted_warnings(data)[0]["outcome"] == "rolled-back"
    assert load_state(respec_home).journal is None
    assert payload(run("status", "--json"))["warnings"] == []


# --- review 2 ------------------------------------------------------------------


def test_a_journal_without_its_profile_can_be_discarded_with_rollback(
    run, isolated_homes
):
    from respec.state import State, save_state

    respec_home = isolated_homes.respec_home
    save_state(respec_home, State(journal={"operation": "update", "started_at": "x"}))

    refused = run("recover", "--json")
    assert refused.exit_code == 1
    assert "--rollback" in json.loads(refused.stdout)["error"]

    data = payload(run("recover", "--rollback", "--json"))

    assert interrupted_warnings(data)[0]["outcome"] == "rolled-back"
    assert "None" not in interrupted_warnings(data)[0]["message"]
    assert load_state(respec_home).journal is None


def test_remove_killed_after_saving_profile_yaml_is_finished(
    run, killed, isolated_homes
):
    respec_home = isolated_homes.respec_home
    make_profile(respec_home, "work", ["claude-code"], ["tdd", "lint"])
    assert run("use", "work").exit_code == 0

    assert killed("after-save-profile", 1, "remove", "lint")
    data = payload(run("status", "--json"))
    assert interrupted_warnings(data)[0]["outcome"] == "pending"
    data = payload(run("recover", "--json"))

    assert interrupted_warnings(data)[0]["outcome"] == "finished"
    assert not (respec_home / "profiles" / "work" / "skills" / "lint").exists()
    assert_consistent(respec_home, {"work": ["tdd"]})


def test_local_add_killed_mid_copy_leaves_no_partial_copy(
    run, killed, isolated_homes, tmp_path
):
    respec_home = isolated_homes.respec_home
    make_profile(respec_home, "work", ["claude-code"], ["tdd"])
    assert run("use", "work").exit_code == 0
    source = tmp_path / "src" / "fresh"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("fresh\n")

    assert killed("note:created", 1, "add", str(source))
    data = payload(run("recover", "--json"))

    assert interrupted_warnings(data)[0]["outcome"] == "rolled-back"
    assert not (respec_home / "profiles" / "work" / "skills" / "fresh").exists()
    assert (source / "SKILL.md").read_text() == "fresh\n"
    assert run("add", str(source)).exit_code == 0


# --- review 3 ------------------------------------------------------------------


def full_flushes_of_a_switch(run, monkeypatch, tmp_path, count):
    from respec import state as state_module

    home, respec_home = fresh_homes(tmp_path, monkeypatch, f"flush-{count}")
    skills = [f"s{number}" for number in range(count)]
    targets = ["claude-code", "agents", "oh-my-pi"]
    make_profile(respec_home, "a", targets, skills)
    make_profile(respec_home, "b", targets, [f"t{number}" for number in range(count)])
    assert run("use", "a").exit_code == 0
    calls: list[int] = []
    real = state_module._flush_to_disk

    def counting(descriptor):
        calls.append(descriptor)
        real(descriptor)

    monkeypatch.setattr(state_module, "_flush_to_disk", counting)
    assert run("use", "b").exit_code == 0
    monkeypatch.setattr(state_module, "_flush_to_disk", real)
    return len(calls)


def test_a_switch_flushes_to_disk_a_fixed_number_of_times(run, monkeypatch, tmp_path):
    """Full flushes (F_FULLFSYNC on macOS) only at the journal's boundaries:
    their number does not grow with the skills a switch changes."""
    few = full_flushes_of_a_switch(run, monkeypatch, tmp_path, 2)
    many = full_flushes_of_a_switch(run, monkeypatch, tmp_path, 20)

    assert many == few
    # The begin, the phase change and the end of the switch are flushed.
    assert 3 <= many <= 8, many


def test_remove_from_another_profile_killed_names_no_active_links(
    run, killed, isolated_homes
):
    respec_home = isolated_homes.respec_home
    make_profile(respec_home, "work", ["claude-code"], ["tdd"])
    make_profile(respec_home, "spare", ["claude-code"], ["lint", "docs"])
    assert run("use", "work").exit_code == 0

    assert killed("after-save-profile", 1, "remove", "lint", "-p", "spare")
    data = payload(run("recover", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "finished"
    assert "not the active profile" in warning["message"]
    assert not (respec_home / "profiles" / "spare" / "skills" / "lint").exists()
    assert_consistent(respec_home, {"work": ["tdd"]})


# --- review 4 ------------------------------------------------------------------


@pytest.mark.parametrize("damage", ["", '{"version": 1, "own'])
def test_an_empty_or_corrupt_state_file_is_rebuilt_by_recover(
    run, isolated_homes, damage
):
    """After a power loss state.json may be empty or cut off. Every command
    then points at 'respec recover', which keeps the damaged file in a backup
    and rebuilds the record from what is on disk; nothing is deleted."""
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    claude = home / ".claude" / "skills"
    before = entries(claude)
    (respec_home / "state.json").write_text(damage)

    blocked = run("status")
    assert blocked.exit_code == 1
    assert "respec recover" in blocked.output

    data = payload(run("recover", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["operation"] == "state"
    assert warning["outcome"] == "rebuilt"
    kept = list((respec_home / "backups").glob("*/state.json"))
    assert len(kept) == 1 and kept[0].read_text() == damage
    assert entries(claude) == before  # nothing deleted
    state = load_state(respec_home)
    assert state.active_profile is None
    # respec's own links are recognised again; the user's entry stays unknown.
    assert {i.name for i in state.installed} >= set(PROFILES["a"])
    assert [e.name for e in unknown.find_unknown(respec_home, state)] == ["mine"]
    assert run("use", "b").exit_code == 0
    assert_consistent(respec_home, {"b": PROFILES["b"]}, extra=MINE)


# --- review 5 ------------------------------------------------------------------


def corrupt_and_rebuild(run, respec_home):
    (respec_home / "state.json").write_text("")
    data = payload(run("recover", "--json"))
    assert interrupted_warnings(data)[0]["outcome"] == "rebuilt"


def drop_takeover_records(respec_home):
    """As a home whose takeovers predate the takeover log."""
    (respec_home / "takeovers.json").unlink()


def test_bare_restore_after_a_rebuild_without_takeover_records_refuses(
    run, isolated_homes
):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    drop_takeover_records(respec_home)
    corrupt_and_rebuild(run, respec_home)
    claude, agents = home / ".claude" / "skills", home / ".agents" / "skills"
    before = (entries(claude), entries(agents))

    result = run("restore")

    assert result.exit_code == 1
    assert "restore --list" in result.output
    assert "from nothing" not in result.output
    assert (entries(claude), entries(agents)) == before
    assert (claude / "mine" / "SKILL.md").read_text() == "mine\n"


def test_a_rebuild_finds_the_takeover_backups_again(run, isolated_homes):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    corrupt_and_rebuild(run, respec_home)

    listed = json.loads(run("restore", "--list", "--json").stdout)
    assert [b["takeover"] for b in listed] == [["claude-code"]]  # agents was made
    result = run("restore")

    assert result.exit_code == 0, result.output
    assert entries(home / ".claude" / "skills") == ["mine"]
    assert not (home / ".agents" / "skills").exists()  # respec created it
    assert load_state(respec_home).owned == {}


def test_a_state_file_from_a_newer_respec_is_not_rebuilt(run, isolated_homes):
    respec_home = isolated_homes.respec_home
    newer = '{"version": 99, "active_profile": null, "owned": {}, "installed": []}'
    (respec_home / "state.json").write_text(newer)

    status = run("status")
    recover = run("recover")

    for result in (status, recover):
        assert result.exit_code == 1
        assert "newer" in result.output
        assert "respec recover" not in result.output
    assert (respec_home / "state.json").read_text() == newer
    assert not (respec_home / "backups").exists()


def test_recover_note_names_what_kept_the_profile_from_activating(run, cut_switch):
    home, respec_home = cut_switch
    blocker = home / ".agents" / "skills" / "docs"
    blocker.mkdir(parents=True, exist_ok=True)
    (blocker / "SKILL.md").write_text("in the way\n")

    data = payload(run("recover", "--json"))

    (warning,) = interrupted_warnings(data)
    assert warning["outcome"] == "rolled-back"
    assert str(blocker) in warning["message"]
    assert "respec adopt" in warning["message"]


# --- review 6 ------------------------------------------------------------------


def test_folders_that_did_not_exist_are_released_after_a_rebuild(run, isolated_homes):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    make_profile(respec_home, "a", ["claude-code", "agents"], ["tdd"])
    assert run("use", "a").exit_code == 0  # nothing existed: no backup run
    corrupt_and_rebuild(run, respec_home)

    result = run("restore")

    assert result.exit_code == 0, result.output
    assert not (home / ".claude").exists()
    assert not (home / ".agents").exists()
    assert load_state(respec_home).owned == {}


def test_release_only_removes_only_what_respec_can_verify(run, isolated_homes):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    drop_takeover_records(respec_home)
    corrupt_and_rebuild(run, respec_home)
    claude = home / ".claude" / "skills"
    refused = run("restore")
    assert refused.exit_code == 1 and "--release-only" in refused.output

    data = payload(run("restore", "--release-only", "--json"))

    assert entries(claude) == ["mine"]  # respec's links gone, the user's kept
    assert (claude / "mine" / "SKILL.md").read_text() == "mine\n"
    assert (home / ".agents" / "skills").is_dir()  # not recorded as created
    assert sorted(Path(p).name for p in data["removed"]) == sorted(PROFILES["a"] * 2)
    assert data["restored"] == {}
    assert load_state(respec_home).owned == {}
    assert (respec_home / "backups").is_dir()  # the takeover run stays


def test_an_empty_manifest_does_not_stop_a_restore(run, isolated_homes):
    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    (run_dir,) = (respec_home / "backups").iterdir()
    (run_dir / "manifest.json").write_text("")

    data = payload(run("restore", "--json"))

    assert entries(home / ".claude" / "skills") == ["mine"]
    (warning,) = [w for w in data["warnings"] if w["type"] == "unreadable-manifest"]
    assert warning["path"] == str(run_dir / "manifest.json")


def test_a_released_takeover_is_not_reused_by_a_rebuild(run, isolated_homes):
    import shutil

    home, respec_home = isolated_homes.home, isolated_homes.respec_home
    two_profiles(respec_home, home)
    assert run("use", "a").exit_code == 0
    assert run("restore").exit_code == 0  # 'mine' is back; respec let go
    shutil.rmtree(home / ".claude")  # the user removes it all
    assert run("use", "a").exit_code == 0  # taken over again, nothing existed
    corrupt_and_rebuild(run, respec_home)

    result = run("restore")

    assert result.exit_code == 0, result.output
    assert not (home / ".claude").exists()  # 'mine' does not come back
