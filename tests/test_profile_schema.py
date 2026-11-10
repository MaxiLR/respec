import textwrap

import pytest


def write_profile_yaml(isolated_homes, text, name="work"):
    folder = isolated_homes.respec_home / "profiles" / name
    folder.mkdir(parents=True)
    path = folder / "profile.yaml"
    path.write_text(textwrap.dedent(text))
    return path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("targets: [cursor]\n", "targets: unknown target 'cursor'"),
        ("skills: {}\n", "'targets' is required"),
        ("targets: claude-code\n", "'targets' must be a list"),
        ("targets: []\n", "at least one target is required"),
        ("- claude-code\n", "top level must be a mapping"),
        (
            "targets: [agents]\nskills:\n  tdd:\n    enabled: 'yes'\n",
            "skills.tdd.enabled must be true or false, got 'yes'",
        ),
        (
            "targets: [agents]\nskills:\n  tdd: {}\n",
            "skills.tdd.enabled is required",
        ),
        (
            "targets: [agents]\nskills:\n  tdd: true\n",
            "skills.tdd must be a mapping",
        ),
        (
            "targets: [agents]\nskills:\n  tdd:\n    enabled: true\n"
            "    source: {path: skills/tdd}\n",
            "skills.tdd.source.repo is required",
        ),
        (
            "targets: [agents]\nskills:\n  tdd:\n    enabled: true\n"
            "    source: {repo: a/b, branch: main}\n",
            "skills.tdd.source: unknown key 'branch'",
        ),
        (
            "targets: [agents]\nskills:\n  tdd:\n    enabled: true\n    pinned: true\n",
            "skills.tdd: unknown key 'pinned'",
        ),
        ("targets: [agents]\ntarget: [agents]\n", "top level: unknown key 'target'"),
        ("targets: [agents\n", "not valid YAML"),
        (
            "targets: [agents]\nskills:\n  ../evil:\n    enabled: true\n",
            "skill name '../evil' is invalid",
        ),
    ],
)
def test_invalid_profile_yaml_is_reported_with_file_and_field(
    run, isolated_homes, text, expected
):
    path = write_profile_yaml(isolated_homes, text)

    result = run("profile", "show", "work")

    assert result.exit_code == 1
    assert str(path) in result.output
    assert expected in result.output
    assert "Traceback" not in result.output


def test_all_problems_are_reported_together(run, isolated_homes):
    write_profile_yaml(
        isolated_homes,
        """\
        targets: [cursor, agents]
        skills:
          a: {enabled: 1}
          b: {enabled: true, source: {repo: ''}}
        """,
    )

    result = run("profile", "show", "work")

    assert result.exit_code == 1
    assert "unknown target 'cursor'" in result.output
    assert "skills.a.enabled must be true or false, got 1" in result.output
    assert "skills.b.source.repo must be a non-empty string" in result.output


def test_missing_profile_yaml_is_reported(run, isolated_homes):
    (isolated_homes.respec_home / "profiles" / "work").mkdir(parents=True)

    result = run("profile", "show", "work")

    assert result.exit_code == 1
    assert "profile.yaml is missing" in result.output


def test_skills_key_is_optional_and_source_fields_are_optional(run, isolated_homes):
    write_profile_yaml(
        isolated_homes,
        """\
        targets: [agents]
        skills:
          tdd:
            enabled: true
            source: {repo: example/skills}
        """,
    )

    result = run("profile", "show", "work", "--json")

    assert result.exit_code == 0, result.output
    assert '"repo": "example/skills"' in result.stdout
