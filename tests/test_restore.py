"""``respec restore``: put takeover backups back and release ownership."""

import json
import os
import shutil
import stat
from datetime import datetime, timezone

import pytest
import yaml

from respec import cli, restore, switch


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


def snapshot(folder):
    """Every entry below folder: kind, permissions, file bytes, link targets.

    Symlinks are recorded by target and never followed.
    """
    if not os.path.lexists(folder):
        return None
    found = {}
    for root, subdirs, files in os.walk(folder):
        for name in subdirs + files:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, folder)
            mode = stat.S_IMODE(os.lstat(path).st_mode)
            if os.path.islink(path):
                found[relative] = ("link", os.readlink(path))
            elif os.path.isdir(path):
                found[relative] = ("dir", mode)
            else:
                with open(path, "rb") as handle:
                    found[relative] = ("file", mode, handle.read())
    return found


def populate(dirs, elsewhere):
    """Pre-respec content: folders, a plain file and a user's own symlink."""
    claude = dirs["claude-code"]
    (claude / "mine" / "refs").mkdir(parents=True)
    (claude / "mine" / "SKILL.md").write_text("my own skill\n")
    (claude / "mine" / "refs" / "a.md").write_text("ref a\n")
    (claude / "notes.txt").write_text("loose file\n")
    (claude / "tool" / "empty").mkdir(parents=True)
    (claude / "tool" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (claude / "tool" / "run.sh").chmod(0o755)
    (claude / "tool" / "data.bin").write_bytes(bytes(range(256)) * 4)
    (claude / "tool" / "secret.txt").write_text("private\n")
    (claude / "tool" / "secret.txt").chmod(0o600)
    elsewhere.mkdir()
    (elsewhere / "SKILL.md").write_text("linked by me\n")
    (claude / "linked").symlink_to(elsewhere, target_is_directory=True)
    agents = dirs["agents"]
    (agents / "shared").mkdir(parents=True)
    (agents / "shared" / "SKILL.md").write_text("agents skill\n")


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def read_state(respec_home):
    return json.loads((respec_home / "state.json").read_text())


@pytest.fixture
def taken_over(run, respec_home, dirs, isolated_homes):
    """Populated claude-code and agents folders taken over by profile a, then
    switched to b (oh-my-pi, whose folder did not exist). Returns the originals."""
    populate(dirs, isolated_homes.home / "elsewhere")
    original = {target: snapshot(folder) for target, folder in dirs.items()}
    make_profile(respec_home, "a", ["claude-code", "agents"], ["tdd", "lint"])
    make_profile(respec_home, "b", ["oh-my-pi", "claude-code"], ["review"])
    ok(run("use", "a"))
    ok(run("use", "b"))
    assert (dirs["oh-my-pi"] / "review").is_symlink()
    return original


def test_restore_returns_every_folder_to_its_takeover_contents_and_releases(
    run, respec_home, dirs, taken_over
):
    ok(run("restore"))

    for target, folder in dirs.items():
        assert snapshot(folder) == taken_over[target], target
    state = read_state(respec_home)
    assert state["active_profile"] is None
    assert state["owned"] == {}
    assert state["installed"] == []
    assert "unmanaged" not in state
    assert (
        ok(run("status", "--json")).stdout
        and json.loads(run("status", "--json").stdout)["folders"] == []
    )


def respec_links(folder, respec_home):
    profiles_root = str(respec_home / "profiles")
    return sorted(
        p.name
        for p in folder.iterdir()
        if p.is_symlink() and os.readlink(p).startswith(profiles_root)
    )


def backup_runs(respec_home):
    return sorted(p.name for p in (respec_home / "backups").iterdir())


def test_list_shows_takeover_backup_with_its_targets(run, respec_home, taken_over):
    listed = json.loads(ok(run("restore", "--list", "--json")).stdout)

    assert len(listed) == 1
    assert listed[0]["targets"] == ["agents", "claude-code"]
    assert sorted(listed[0]["takeover"]) == ["agents", "claude-code"]
    assert listed[0]["path"] == str(respec_home / "backups" / listed[0]["name"])
    human = ok(run("restore", "--list")).stdout
    assert listed[0]["name"] in human and "takeover" in human


def test_restore_named_backup_restores_the_folders_it_holds(
    run, respec_home, dirs, taken_over
):
    name = json.loads(ok(run("restore", "--list", "--json")).stdout)[0]["name"]

    out = json.loads(ok(run("restore", name, "--json")).stdout)

    assert out["backup"] == name
    assert snapshot(dirs["claude-code"]) == taken_over["claude-code"]
    assert snapshot(dirs["agents"]) == taken_over["agents"]
    # oh-my-pi is not in that backup: respec's items are removed, ownership
    # released, and the folder respec created for it is gone with its parents.
    assert not dirs["oh-my-pi"].exists()
    assert not (dirs["oh-my-pi"].parent.parent).exists()
    assert read_state(respec_home)["owned"] == {}


def test_restore_refuses_to_overwrite_an_unknown_entry_and_changes_nothing(
    run, respec_home, dirs, taken_over
):
    (dirs["claude-code"] / "stray").mkdir()
    (dirs["claude-code"] / "stray" / "SKILL.md").write_text("dropped later\n")
    before = {target: snapshot(folder) for target, folder in dirs.items()}
    state_before = read_state(respec_home)

    result = run("restore")

    assert result.exit_code == 1
    assert str(dirs["claude-code"] / "stray") in result.output
    assert "--overwrite" in result.output and "respec adopt" in result.output
    assert {target: snapshot(folder) for target, folder in dirs.items()} == before
    assert read_state(respec_home) == state_before


def test_restore_with_unknown_backup_moves_entry_aside_then_restores_exactly(
    run, respec_home, dirs, taken_over
):
    (dirs["claude-code"] / "stray").mkdir()
    (dirs["claude-code"] / "stray" / "SKILL.md").write_text("dropped later\n")

    ok(run("restore", "--unknown", "remove"))

    assert snapshot(dirs["claude-code"]) == taken_over["claude-code"]
    saved = list((respec_home / "backups").glob("*/claude-code/stray/SKILL.md"))
    assert [p.read_text() for p in saved] == ["dropped later\n"]


def test_pre_existing_entry_that_differs_from_backup_needs_overwrite(
    run, respec_home, dirs, taken_over
):
    # "mine" was left in place during the switch; now someone edits it.
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("edited after\n")

    blocked = run("restore")
    assert blocked.exit_code == 1
    assert (dirs["claude-code"] / "mine" / "SKILL.md").read_text() == "edited after\n"

    ok(run("restore", "--overwrite"))

    assert snapshot(dirs["claude-code"]) == taken_over["claude-code"]
    saved = list((respec_home / "backups").glob("*/claude-code/mine/SKILL.md"))
    contents = sorted(p.read_text() for p in saved)
    assert contents == ["edited after\n", "my own skill\n"]


def test_interactive_restore_asks_add_or_remove_before_overwriting(
    run, respec_home, dirs, taken_over, monkeypatch
):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("edited after\n")

    result = ok(run("restore", input="remove\n"))

    assert "add to profile 'b'" in result.stdout and "keep" not in result.stdout
    assert snapshot(dirs["claude-code"]) == taken_over["claude-code"]
    saved = list((respec_home / "backups").glob("*/claude-code/mine/SKILL.md"))
    assert sorted(p.read_text() for p in saved) == ["edited after\n", "my own skill\n"]


@pytest.fixture
def copy_installed(run, respec_home, dirs, monkeypatch):
    """Profile a installed into a populated claude-code folder as copies."""
    (dirs["claude-code"] / "mine").mkdir(parents=True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("my own skill\n")
    original = snapshot(dirs["claude-code"])
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])

    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    with monkeypatch.context() as patch:
        patch.setattr(os, "symlink", refuse)
        ok(run("use", "a"))
    copy = dirs["claude-code"] / "tdd"
    assert copy.is_dir() and not copy.is_symlink()
    return original


def test_unmodified_copy_is_removed_by_restore(run, dirs, copy_installed):
    ok(run("restore"))

    assert snapshot(dirs["claude-code"]) == copy_installed


def test_edited_copy_is_never_deleted_silently(run, respec_home, dirs, copy_installed):
    edited = dirs["claude-code"] / "tdd" / "SKILL.md"
    edited.write_text("edited by hand\n")

    blocked = run("restore")

    assert blocked.exit_code == 1
    assert str(dirs["claude-code"] / "tdd") in blocked.output
    assert edited.read_text() == "edited by hand\n"

    ok(run("restore", "--unknown", "remove"))

    assert snapshot(dirs["claude-code"]) == copy_installed
    saved = list((respec_home / "backups").glob("*/claude-code/tdd/SKILL.md"))
    assert [p.read_text() for p in saved] == ["edited by hand\n"]


@pytest.fixture
def shared_folder(run, respec_home, dirs):
    """~/.claude/skills links to ~/.agents/skills; agents is taken over first,
    claude-code later, so its takeover backup holds respec's own links."""
    (dirs["agents"] / "mine").mkdir(parents=True)
    (dirs["agents"] / "mine" / "SKILL.md").write_text("my own skill\n")
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    original = snapshot(dirs["agents"])
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_profile(respec_home, "b", ["claude-code"], ["lint"])
    ok(run("use", "a"))
    ok(run("use", "b"))
    runs = backup_runs(respec_home)
    assert len(runs) == 2
    later = respec_home / "backups" / runs[1] / "claude-code"
    assert (later / "tdd").is_symlink()  # the integration finding
    return original, runs


def test_default_restore_of_shared_folder_uses_its_first_takeover(
    run, respec_home, dirs, shared_folder
):
    original, _ = shared_folder

    ok(run("restore"))

    assert snapshot(dirs["agents"]) == original
    assert dirs["claude-code"].is_symlink()


def test_restoring_a_backup_holding_respec_links_does_not_recreate_them(
    run, respec_home, dirs, shared_folder
):
    original, runs = shared_folder

    out = json.loads(ok(run("restore", runs[1], "--json")).stdout)

    skipped = str(respec_home / "backups" / runs[1] / "claude-code" / "tdd")
    assert out["skipped"] == [skipped]
    assert respec_links(dirs["agents"], respec_home) == []
    assert snapshot(dirs["agents"]) == original
    assert read_state(respec_home)["installed"] == []


def test_failed_restore_keeps_state_true_to_disk_and_can_be_rerun(
    run, respec_home, dirs, taken_over
):
    # An unreadable file in the backup makes putting "mine" back fail.
    shutil.rmtree(dirs["claude-code"] / "mine")
    backed_up = next((respec_home / "backups").glob("*/claude-code/mine/SKILL.md"))
    backed_up.chmod(0)
    try:
        failed = run("restore")
    finally:
        backed_up.chmod(0o644)

    assert failed.exit_code == 1
    assert "mine" in failed.output and "respec restore" in failed.output
    assert not os.path.lexists(dirs["claude-code"] / "mine")
    state = read_state(respec_home)
    assert state["active_profile"] is None
    assert state["installed"] == []
    assert sorted(state["owned"]) == ["agents", "claude-code", "oh-my-pi"]
    for folder in dirs.values():
        if folder.is_dir():
            assert respec_links(folder, respec_home) == []

    ok(run("restore"))

    for target, folder in dirs.items():
        assert snapshot(folder) == taken_over[target], target
    assert read_state(respec_home)["owned"] == {}


def test_overwrite_backup_run_never_reuses_a_run_from_the_same_second(
    respec_home, isolated_homes, dirs
):
    moment = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
    (dirs["claude-code"] / "mine").mkdir(parents=True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("my own skill\n")
    original = snapshot(dirs["claude-code"])
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    home = isolated_homes.home
    switch.use(respec_home, home, "a", now=lambda: moment)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("edited after\n")

    result = restore.restore(respec_home, home, overwrite=True, now=lambda: moment)

    assert snapshot(dirs["claude-code"]) == original
    assert backup_runs(respec_home) == ["20261109T120000Z", "20261109T120000Z-2"]
    aside = respec_home / "backups" / "20261109T120000Z-2" / "claude-code" / "mine"
    assert result.set_aside[0].backup == str(aside)
    assert (aside / "SKILL.md").read_text() == "edited after\n"


def test_restore_without_ownership_or_backup_name_fails(run):
    result = run("restore")

    assert result.exit_code == 1
    assert "nothing to restore" in result.output


def test_restoring_a_backup_holding_respec_copies_does_not_recreate_them(
    run, respec_home, dirs, monkeypatch
):
    (dirs["agents"] / "mine").mkdir(parents=True)
    (dirs["agents"] / "mine" / "SKILL.md").write_text("my own skill\n")
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    original = snapshot(dirs["agents"])
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_profile(respec_home, "b", ["claude-code"], ["lint"])

    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    with monkeypatch.context() as patch:
        patch.setattr(os, "symlink", refuse)
        ok(run("use", "a"))
        ok(run("use", "b"))
    later = backup_runs(respec_home)[1]
    assert (respec_home / "backups" / later / "claude-code" / "tdd").is_dir()

    out = ok(run("restore", later)).stdout

    assert (
        "Skipped " + str(respec_home / "backups" / later / "claude-code" / "tdd") in out
    )

    assert snapshot(dirs["agents"]) == original


def test_original_later_adopted_into_a_profile_comes_back(run, respec_home, dirs):
    (dirs["claude-code"] / "mine").mkdir(parents=True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("my own skill\n")
    original = snapshot(dirs["claude-code"])
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    ok(run("use", "a"))
    ok(run("adopt", "--add", "mine"))
    assert (dirs["claude-code"] / "mine").is_symlink()

    ok(run("restore"))

    assert snapshot(dirs["claude-code"]) == original


def test_after_release_a_later_backup_still_leaves_respec_copies_out(
    run, respec_home, dirs, monkeypatch
):
    (dirs["agents"] / "mine").mkdir(parents=True)
    (dirs["agents"] / "mine" / "SKILL.md").write_text("my own skill\n")
    dirs["claude-code"].parent.mkdir(parents=True)
    dirs["claude-code"].symlink_to(dirs["agents"], target_is_directory=True)
    original = snapshot(dirs["agents"])
    make_profile(respec_home, "a", ["agents"], ["tdd"])
    make_profile(respec_home, "b", ["claude-code"], ["lint"])

    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    with monkeypatch.context() as patch:
        patch.setattr(os, "symlink", refuse)
        ok(run("use", "a"))
        ok(run("use", "b"))
    first, later = backup_runs(respec_home)
    ok(run("restore"))
    assert read_state(respec_home)["owned"] == {}

    ok(run("restore", later))

    assert snapshot(dirs["agents"]) == original


def test_named_pre_respec_run_from_an_earlier_ownership_cycle_restores_exactly(
    run, respec_home, dirs
):
    (dirs["claude-code"] / "mine").mkdir(parents=True)
    (dirs["claude-code"] / "mine" / "SKILL.md").write_text("my own skill\n")
    original = snapshot(dirs["claude-code"])
    make_profile(respec_home, "a", ["claude-code"], ["tdd"])
    ok(run("use", "a"))
    ok(run("adopt", "--add", "mine"))
    ok(run("restore"))
    assert snapshot(dirs["claude-code"]) == original
    shutil.rmtree(dirs["claude-code"] / "mine")
    ok(run("use", "a"))  # second ownership cycle, a new takeover run
    first = backup_runs(respec_home)[0]

    ok(run("restore", first))

    assert snapshot(dirs["claude-code"]) == original


def test_pre_existing_entry_with_changed_permissions_is_not_identical(
    run, dirs, taken_over
):
    (dirs["claude-code"] / "tool" / "run.sh").chmod(0o600)

    blocked = run("restore")

    assert blocked.exit_code == 1
    assert str(dirs["claude-code"] / "tool") in blocked.output
    ok(run("restore", "--overwrite"))
    assert snapshot(dirs["claude-code"]) == taken_over["claude-code"]


def test_restore_puts_back_modes_binary_content_and_empty_folders(
    run, dirs, taken_over
):
    shutil.rmtree(dirs["claude-code"] / "tool")

    ok(run("restore"))

    assert snapshot(dirs["claude-code"]) == taken_over["claude-code"]
    tool = dirs["claude-code"] / "tool"
    assert stat.S_IMODE((tool / "run.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((tool / "secret.txt").stat().st_mode) == 0o600
    assert (tool / "data.bin").read_bytes() == bytes(range(256)) * 4
    assert (tool / "empty").is_dir()


def test_unknown_entries_are_removed_and_hidden_leftovers_reported(
    run, respec_home, dirs, taken_over
):
    (dirs["claude-code"] / "stray").mkdir()
    (dirs["claude-code"] / "stray" / "SKILL.md").write_text("dropped later\n")
    (dirs["claude-code"] / ".hidden").write_text("x\n")

    out = json.loads(ok(run("restore", "--unknown", "remove", "--json")).stdout)

    assert out["left"] == [str(dirs["claude-code"] / ".hidden")]
    assert not os.path.lexists(dirs["claude-code"] / "stray")
    saved = list((respec_home / "backups").glob("*/claude-code/stray/SKILL.md"))
    assert [p.read_text() for p in saved] == ["dropped later\n"]


def test_hidden_leftover_is_named_in_human_output(run, dirs, taken_over):
    (dirs["claude-code"] / ".hidden").write_text("x\n")

    out = ok(run("restore")).stdout

    assert any(
        line.startswith("Left ") and ".hidden" in line and "not in the backup" in line
        for line in out.splitlines()
    )
