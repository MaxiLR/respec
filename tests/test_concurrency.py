"""Two respec processes at once: one changes skills, the other is told so."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest
import yaml

from respec import state as respec_state

# The plain CLI in a child process (without respec's shipped skills).
CLI_SCRIPT = """
import os, sys
from respec import global_skills
if os.environ.get("RESPEC_TEST_NO_SHIPPED"):
    global_skills.shipped_names = lambda: ()
from respec.cli import app
app(sys.argv[1:])
"""

TARGETS = ("claude-code", "agents", "oh-my-pi")


def make_profile(respec_home, name, skills):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill} of {name}\n")
    data = {
        "targets": list(TARGETS),
        "skills": {skill: {"enabled": True} for skill in skills},
    }
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


@pytest.fixture
def homes(isolated_homes):
    make_profile(isolated_homes.respec_home, "a", [f"a{i}" for i in range(20)])
    make_profile(isolated_homes.respec_home, "b", [f"b{i}" for i in range(20)])
    return isolated_homes


@pytest.fixture
def folders(isolated_homes):
    home = isolated_homes.home
    return [
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        home / ".omp" / "agent" / "skills",
    ]


def child_env():
    env = os.environ.copy()
    env["RESPEC_TEST_NO_SHIPPED"] = "1"
    return env


def cli(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-c", CLI_SCRIPT, *args],
        env=child_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def entries(folder):
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def assert_consistent(respec_home, folders, profile):
    """The profile's skills, and nothing else, in every folder and in state."""
    data = json.loads((respec_home / "state.json").read_text())
    assert data["active_profile"] == profile
    assert "journal" not in data
    expected = [f"{profile}{i}" for i in range(20)]
    for folder in folders:
        assert sorted(entries(folder)) == sorted(expected), folder
    recorded = sorted(item["path"] for item in data["installed"])
    assert recorded == sorted(str(f / name) for f in folders for name in expected)


def test_a_second_use_while_one_runs_fails_cleanly_and_the_first_wins(
    homes, folders, holder
):
    first = holder("use:begin", "use", "a")

    second = cli("use", "b")

    assert second.returncode == 1
    assert "Traceback" not in second.stderr
    assert "another respec" in second.stderr.lower()
    code, out, err = first.finish()
    assert code == 0, out + err
    assert "Traceback" not in err
    assert_consistent(homes.respec_home, folders, "a")


def test_a_refused_use_with_json_gives_an_error_and_changes_nothing(
    homes, folders, holder
):
    first = holder("use:begin", "use", "a")
    before = (homes.respec_home / "state.json").read_text()

    second = cli("use", "b", "--json")

    assert second.returncode == 1
    data = json.loads(second.stdout)
    assert "another respec" in data["error"].lower()
    assert data["warnings"] == []
    assert (homes.respec_home / "state.json").read_text() == before
    assert first.finish()[0] == 0
    assert_consistent(homes.respec_home, folders, "a")


def test_status_while_a_change_runs_does_not_call_it_interrupted(homes, holder):
    holder("use:begin", "use", "a")

    shown = cli("status", "--json")
    text = cli("status")

    assert shown.returncode == 0, shown.stderr
    types = [warning["type"] for warning in json.loads(shown.stdout)["warnings"]]
    assert "interrupted-operation" not in types
    assert text.returncode == 0, text.stderr
    assert "interrupted" not in (text.stdout + text.stderr).lower()


def test_read_only_commands_run_while_a_change_runs(homes, holder):
    holder("use:begin", "use", "a")

    for args in (("profile", "list"), ("profile", "show", "b"), ("layer", "list")):
        done = cli(*args, "-p", "b") if args[0] == "layer" else cli(*args)
        assert done.returncode == 0, (args, done.stderr)
        assert "another respec" not in done.stderr.lower()


def test_recover_is_refused_while_the_change_it_would_recover_runs(
    homes, folders, holder
):
    first = holder("use:begin", "use", "a")

    recovered = cli("recover", "--json")

    assert recovered.returncode == 1
    assert "another respec" in json.loads(recovered.stdout)["error"].lower()
    assert first.finish()[0] == 0
    assert_consistent(homes.respec_home, folders, "a")


def test_a_kill_while_running_leaves_no_lock_behind(homes, folders, killed):
    assert killed("use:begin", 1, "use", "a")

    started = time.monotonic()
    done = cli("use", "b")

    assert done.returncode == 0, done.stderr
    assert time.monotonic() - started < 10
    assert_consistent(homes.respec_home, folders, "b")


def test_racing_switches_never_crash_and_leave_one_profile_whole(homes, folders):
    for round_ in range(4):
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", CLI_SCRIPT, "use", name],
                env=child_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for name in ("b", "a")
        ]
        results = [(p.wait(timeout=60), *p.communicate()) for p in processes]
        for code, _, err in results:
            assert "Traceback" not in err, err
            assert code == 0 or "another respec" in err.lower(), err
        assert any(code == 0 for code, _, _ in results)
        active = json.loads((homes.respec_home / "state.json").read_text())
        assert_consistent(homes.respec_home, folders, active["active_profile"])


def test_state_saves_from_several_threads_never_collide(isolated_homes):
    errors = []

    def save(index):
        try:
            for _ in range(30):
                respec_state.save_state(
                    isolated_homes.respec_home,
                    respec_state.State(active_profile=f"p{index}"),
                )
        except Exception as error:  # noqa: BLE001 - collected for the assert
            errors.append(error)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    loaded = respec_state.load_state(isolated_homes.respec_home)
    assert loaded.active_profile in {f"p{i}" for i in range(6)}
    leftovers = [
        p.name for p in isolated_homes.respec_home.iterdir() if p.name != "state.json"
    ]
    assert leftovers == []


def test_a_change_that_ends_while_status_reads_is_not_called_interrupted(
    homes, holder, monkeypatch
):
    from respec import journal

    first = holder("use:begin", "use", "a")
    real_load = journal.load_state

    def load_then_let_the_change_end(respec_home):
        state = real_load(respec_home)
        if first.process.poll() is None:
            assert first.finish()[0] == 0
        return state

    monkeypatch.setattr(journal, "load_state", load_then_let_the_change_end)

    assert journal.pending(homes.respec_home) is None
    first.finish()


def test_a_change_from_another_thread_waits_its_turn_like_another_process(
    homes, folders, run, monkeypatch
):
    from respec import lock

    monkeypatch.setattr(lock, "WAIT", 0.1)
    taken, done = threading.Event(), threading.Event()

    def other_thread():
        with lock.exclusive(homes.respec_home):
            taken.set()
            done.wait(30)

    thread = threading.Thread(target=other_thread)
    thread.start()
    try:
        assert taken.wait(30)
        refused = run("use", "a")
    finally:
        done.set()
        thread.join()

    assert refused.exit_code == 1
    assert "another respec is running" in refused.stderr
    assert not (homes.respec_home / "state.json").exists()
    assert run("use", "a").exit_code == 0


def test_temporary_state_files_of_a_killed_writer_are_cleaned_up(homes, folders):
    stale = homes.respec_home / ".state.json.99999.deadbeef.tmp"
    stale.write_text("{")

    done = cli("use", "a")

    assert done.returncode == 0, done.stderr
    assert not stale.exists()
    assert_consistent(homes.respec_home, folders, "a")


def test_temporary_state_files_stay_while_a_change_runs(homes, holder):
    first = holder("use:begin", "use", "a")
    temporary = homes.respec_home / ".state.json.4242.cafe.tmp"
    temporary.write_text("{")

    assert cli("status").returncode == 0
    assert cli("profile", "list").returncode == 0

    assert temporary.exists()
    assert first.finish()[0] == 0
