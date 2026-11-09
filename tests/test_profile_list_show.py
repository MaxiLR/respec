import json
import textwrap

import pytest


def write_profile(respec_home, name, text):
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    (folder / "profile.yaml").write_text(textwrap.dedent(text))
    return folder


@pytest.fixture
def sourced_profile(isolated_homes):
    return write_profile(
        isolated_homes.respec_home,
        "work",
        """\
        targets: [claude-code, agents, oh-my-pi]
        skills:
          tdd:
            enabled: true
            source:
              repo: example/skills
              path: skills/tdd
              ref: main
              commit: 0123abcd
          notes:
            enabled: false
        """,
    )


def test_list_json_with_no_profiles(run):
    result = run("profile", "list", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"profiles": []}


def test_list_human_with_no_profiles_explains_how_to_create(run):
    result = run("profile", "list")

    assert result.exit_code == 0
    assert "No profiles yet" in result.stdout
    assert "respec profile new" in result.stdout


def test_list_json_summarises_profiles_in_name_order(run):
    assert run("profile", "new", "zeta", "-t", "oh-my-pi").exit_code == 0
    assert (
        run("profile", "new", "alpha", "-t", "claude-code", "-t", "agents").exit_code
        == 0
    )

    result = run("profile", "list", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "profiles": [
            {
                "name": "alpha",
                "targets": ["claude-code", "agents"],
                "skills": 0,
                "enabled": 0,
            },
            {"name": "zeta", "targets": ["oh-my-pi"], "skills": 0, "enabled": 0},
        ]
    }


def test_list_human_shows_each_profile_and_flags_invalid_ones(
    run, sourced_profile, isolated_homes
):
    write_profile(isolated_homes.respec_home, "broken", "targets: [nope]\n")

    result = run("profile", "list")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    work = next(line for line in lines if line.startswith("work"))
    assert "claude-code, agents, oh-my-pi" in work
    assert "2 skills (1 enabled)" in work
    broken = next(line for line in lines if line.startswith("broken"))
    assert "invalid" in broken


def test_list_json_reports_invalid_profile_error(run, isolated_homes):
    write_profile(isolated_homes.respec_home, "broken", "targets: [nope]\n")

    result = run("profile", "list", "--json")

    assert result.exit_code == 0, result.output
    [entry] = json.loads(result.stdout)["profiles"]
    assert entry["name"] == "broken"
    assert "unknown target 'nope'" in entry["error"]


def test_show_json_includes_resolved_target_dirs_and_skills(
    run, sourced_profile, isolated_homes
):
    result = run("profile", "show", "work", "--json")

    assert result.exit_code == 0, result.output
    home = isolated_homes.home
    assert json.loads(result.stdout) == {
        "name": "work",
        "path": str(sourced_profile),
        "targets": [
            {
                "name": "claude-code",
                "display_name": "Claude Code",
                "skills_dir": str(home / ".claude" / "skills"),
            },
            {
                "name": "agents",
                "display_name": "Agents (Codex, Pi and other .agents readers)",
                "skills_dir": str(home / ".agents" / "skills"),
            },
            {
                "name": "oh-my-pi",
                "display_name": "oh-my-pi",
                "skills_dir": str(home / ".omp" / "agent" / "skills"),
            },
        ],
        "skills": [
            {
                "name": "tdd",
                "enabled": True,
                "source": {
                    "repo": "example/skills",
                    "path": "skills/tdd",
                    "ref": "main",
                    "commit": "0123abcd",
                },
            },
            {"name": "notes", "enabled": False, "source": None},
        ],
    }


@pytest.mark.parametrize(
    "args",
    [
        ("--home", "x", "profile", "show", "work"),
        ("profile", "show", "work", "--home", "x"),
        ("tui", "--home", "x"),
    ],
)
def test_home_option_is_rejected(run, sourced_profile, args):
    result = run(*args)

    assert result.exit_code == 2
    assert "No such option: --home" in result.output


def test_user_home_env_relocates_target_dirs(run, sourced_profile, tmp_path):
    other = tmp_path / "env-home"

    result = run(
        "profile", "show", "work", "--json", env={"RESPEC_USER_HOME": str(other)}
    )

    assert result.exit_code == 0, result.output
    dirs = [t["skills_dir"] for t in json.loads(result.stdout)["targets"]]
    assert dirs[0] == str(other / ".claude" / "skills")
    assert dirs[2] == str(other / ".omp" / "agent" / "skills")


def test_show_human_lists_targets_and_skill_states(
    run, sourced_profile, isolated_homes
):
    result = run("profile", "show", "work")

    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "work" in out
    assert str(isolated_homes.home / ".claude" / "skills") in out
    tdd = next(line for line in out.splitlines() if "tdd" in line)
    assert "enabled" in tdd and "example/skills" in tdd
    notes = next(line for line in out.splitlines() if "notes" in line)
    assert "disabled" in notes


def test_show_unknown_profile_explains_how_to_create(run):
    result = run("profile", "show", "missing")

    assert result.exit_code == 1
    assert "profile 'missing' does not exist" in result.output
    assert "respec profile new missing" in result.output
