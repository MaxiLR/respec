import yaml


def test_new_creates_profile_yaml_and_skills_folder(run, isolated_homes):
    result = run("profile", "new", "work", "--target", "claude-code", "-t", "oh-my-pi")

    assert result.exit_code == 0, result.output
    profile_dir = isolated_homes.respec_home / "profiles" / "work"
    assert (profile_dir / "skills").is_dir()
    data = yaml.safe_load((profile_dir / "profile.yaml").read_text())
    assert data == {"targets": ["claude-code", "oh-my-pi"], "skills": {}}


def test_new_without_respec_home_uses_dot_respec_in_home(run, isolated_homes):
    result = run(
        "profile", "new", "solo", "--target", "agents", env={"RESPEC_HOME": None}
    )

    assert result.exit_code == 0, result.output
    expected = isolated_homes.home / ".respec" / "profiles" / "solo" / "profile.yaml"
    assert expected.is_file()
    assert not (isolated_homes.respec_home / "profiles").exists()


def test_new_rejects_unknown_target(run, isolated_homes):
    result = run("profile", "new", "work", "--target", "cursor")

    assert result.exit_code != 0
    assert "unknown target 'cursor'" in result.output
    assert "agents, claude-code, oh-my-pi" in result.output
    assert not (isolated_homes.respec_home / "profiles" / "work").exists()


def test_new_requires_at_least_one_target(run, isolated_homes):
    result = run("profile", "new", "work")

    assert result.exit_code != 0
    assert "--target" in result.output
    assert not (isolated_homes.respec_home / "profiles" / "work").exists()


def test_new_rejects_duplicate_name_and_keeps_existing(run, isolated_homes):
    assert run("profile", "new", "work", "-t", "agents").exit_code == 0
    profile_yaml = isolated_homes.respec_home / "profiles" / "work" / "profile.yaml"
    before = profile_yaml.read_text()

    result = run("profile", "new", "work", "-t", "claude-code")

    assert result.exit_code != 0
    assert "profile 'work' already exists" in result.output
    assert profile_yaml.read_text() == before


def test_new_rejects_path_like_names(run, isolated_homes):
    result = run("profile", "new", "../escape", "-t", "agents")

    assert result.exit_code != 0
    assert "invalid profile name '../escape'" in result.output
    assert not (isolated_homes.respec_home / "escape").exists()


def test_new_rejects_repeated_target(run, isolated_homes):
    result = run("profile", "new", "work", "-t", "agents", "-t", "agents")

    assert result.exit_code != 0
    assert "'agents' is listed more than once" in result.output
