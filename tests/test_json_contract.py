"""One JSON vocabulary across use, adopt, restore, status and the change commands.

- ``resolved``: the add or remove choices a command applied;
- ``unresolved``: unknown entries that still need a decision;
- ``backups``, ``warnings`` (typed objects) and, on failure, ``error``.

A failed run prints the same keys as a successful one, plus ``error``. Fields
that never hold a value in a payload (a symlink's digest, a default restore's
backup name) are left out instead of being given as null.
"""

import json

import pytest
import yaml


@pytest.fixture
def respec_home(isolated_homes):
    return isolated_homes.respec_home


@pytest.fixture
def claude_dir(isolated_homes):
    return isolated_homes.home / ".claude" / "skills"


def make_profile(respec_home, name, targets, skills):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill}\n")
    data = {"targets": targets, "skills": {s: {"enabled": True} for s in skills}}
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def drop_skill(folder, name, body="foreign\n"):
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(body)
    return folder / name


def payload(result, code=0):
    assert result.exit_code == code, result.output
    return json.loads(result.stdout)


@pytest.fixture
def work(run, respec_home, claude_dir):
    """Active profile 'work' (claude-code, skill 'tdd') with an unknown 'stray'."""
    make_profile(respec_home, "work", ["claude-code"], ["tdd"])
    make_profile(respec_home, "other", ["claude-code"], ["lint"])
    assert run("use", "work").exit_code == 0
    return drop_skill(claude_dir, "stray")


def unresolved_paths(data):
    return [entry["path"] for entry in data["unresolved"]]


def test_use_lists_remaining_entries_under_unresolved_not_warnings(run, work):
    data = payload(run("use", "other", "--json"))

    assert set(data) == {
        "active_profile",
        "previous_profile",
        "backups",
        "removed",
        "installed",
        "resolved",
        "linked",
        "unresolved",
        "warnings",
    }
    assert unresolved_paths(data) == [str(work)]
    assert data["unresolved"][0] == {
        "name": "stray",
        "path": str(work),
        "kind": "folder",
        "targets": ["claude-code"],
        "replaced": False,
    }
    assert data["warnings"] == []


def test_use_leaves_out_the_digest_of_symlinked_installs(run, work):
    data = payload(run("use", "other", "--json"))

    [installed] = data["installed"]
    assert installed["mode"] == "symlink"
    assert "digest" not in installed


def test_use_failure_lists_the_blocking_entry_as_unresolved(run, work, claude_dir):
    blocking = drop_skill(claude_dir, "lint")

    data = payload(run("use", "other", "--json"), code=1)

    assert "error" in data
    assert str(blocking) in unresolved_paths(data)
    assert str(work) in unresolved_paths(data)


def test_adopt_success_and_failure_carry_the_same_keys(run, work):
    failed = payload(run("adopt", "--add", "nosuch", "--json"), code=1)
    done = payload(run("adopt", "--remove", "stray", "--json"))

    assert set(done) == {"resolved", "linked", "unresolved", "warnings"}
    assert set(failed) == set(done) | {"error"}
    assert unresolved_paths(failed) == [str(work)]
    assert [r["path"] for r in done["resolved"]] == [str(work)]
    assert done["unresolved"] == []


def test_adopt_lists_entries_left_alone_under_unresolved(run, work, claude_dir):
    other = drop_skill(claude_dir, "zzz")

    data = payload(run("adopt", "--remove", "stray", "--json"))

    assert unresolved_paths(data) == [str(other)]
    assert "unknown" not in data


RESTORE_KEYS = {
    "restored",
    "removed",
    "overwritten",
    "resolved",
    "released",
    "skipped",
    "left",
    "unresolved",
    "warnings",
}


def test_restore_reports_applied_choices_under_resolved(run, work, isolated_homes):
    # The folder did not exist at takeover, so 'stray' is in the way.
    data = payload(run("restore", "--unknown", "remove", "--json"))

    assert set(data) == RESTORE_KEYS
    assert [r["path"] for r in data["resolved"]] == [str(work)]
    assert data["resolved"][0]["choice"] == "remove"
    assert data["unresolved"] == []


def test_restore_failure_carries_the_success_keys_and_the_blocking_entries(run, work):
    data = payload(run("restore", "--json"), code=1)

    assert set(data) == RESTORE_KEYS | {"error"}
    assert unresolved_paths(data) == [str(work)]
    assert data["resolved"] == []


def test_restore_names_the_backup_only_when_one_was_given(run, work):
    default = payload(run("restore", "--overwrite", "--json"))

    assert "backup" not in default


def test_status_lists_unknown_entries_under_unresolved(run, work):
    data = payload(run("status", "--json"))

    assert unresolved_paths(data) == [str(work)]
    assert all("unknown" not in folder for folder in data["folders"])


@pytest.mark.parametrize(
    "command",
    [
        ("disable", "tdd"),
        ("layer", "add", "x", "--additive", "-d", "X"),
    ],
)
def test_change_commands_list_unknown_entries_under_unresolved(run, work, command):
    data = payload(run(*command, "--json"))

    assert unresolved_paths(data) == [str(work)]
    assert data["warnings"] == []


# No command prints an undocumented null, on success or failure.


def test_no_undocumented_nulls_in_any_local_command(
    run, work, respec_home, claude_dir, tmp_path, assert_no_nulls
):
    source = tmp_path / "src" / "extra"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# extra\n")
    drop_skill(claude_dir, "zzz")
    commands = [
        ("profile", "new", "third", "-t", "agents"),
        ("profile", "list"),
        ("profile", "show", "work"),
        ("status",),
        ("add", str(source)),
        ("disable", "extra"),
        ("enable", "extra"),
        ("remove", "extra"),
        ("layer", "add", "lay", "--exclusive", "-d", "L"),
        ("layer", "list"),
        ("layer", "show", "lay"),
        ("layer", "use", "lay", "tdd"),
        ("layer", "remove-skill", "lay", "tdd"),
        ("layer", "repair", "lay"),
        ("layer", "off", "lay"),
        ("layer", "rm", "lay"),
        ("adopt",),
        ("adopt", "--add", "stray"),
        ("adopt", "--remove", "zzz"),
        ("use", "other"),
        ("update",),
        ("update", "--check"),
        ("restore", "--list"),
    ]
    for command in commands:
        assert_no_nulls(payload(run(*command, "--json")))


def test_no_undocumented_nulls_in_failures_or_restore(
    run, work, claude_dir, assert_no_nulls
):
    blocking = drop_skill(claude_dir, "lint")
    assert_no_nulls(payload(run("use", "other", "--json"), code=1))
    assert_no_nulls(payload(run("adopt", "--add", "nosuch", "--json"), code=1))
    assert_no_nulls(payload(run("restore", "--json"), code=1))
    assert blocking.exists()
    assert_no_nulls(payload(run("restore", "--unknown", "remove", "--json")))
