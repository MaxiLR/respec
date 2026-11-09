"""Git sources: add from a repo, update checks and updates, profile install.

Every repository is a local bare repository reached over ``file://``. Git runs
with a temporary HOME and no global or system config, and the ``owner/repo``
shorthand resolves through ``RESPEC_GIT_BASE_URL`` so no test touches GitHub.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def isolated_git(isolated_homes, tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.invalid")
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    monkeypatch.setenv("RESPEC_GIT_BASE_URL", remotes.as_uri())
    return remotes


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


class Upstream:
    """A working clone that pushes to a bare repository under ``remotes``."""

    def __init__(self, remotes: Path, tmp_path: Path, slug: str):
        self.bare = remotes / slug
        self.bare.mkdir(parents=True)
        git(self.bare, "init", "-q", "--bare", "-b", "main")
        self.work = tmp_path / "work" / slug
        self.work.mkdir(parents=True)
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "remote", "add", "origin", self.bare.as_uri())
        self.url = self.bare.as_uri()

    def write(self, relative: str, text: str) -> None:
        file = self.work / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def commit(self, message: str = "change", branch: str = "main") -> str:
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", f"HEAD:{branch}")
        return git(self.work, "rev-parse", "HEAD")


@pytest.fixture
def upstream(isolated_git, tmp_path):
    def make(slug: str) -> Upstream:
        return Upstream(isolated_git, tmp_path, slug)

    return make


@pytest.fixture
def profiles_root(isolated_homes):
    return isolated_homes.respec_home / "profiles"


@pytest.fixture
def claude_dir(isolated_homes):
    return isolated_homes.home / ".claude" / "skills"


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def fails(result):
    assert result.exit_code == 1, result.output
    return result


def read_yaml(profiles_root, profile):
    return yaml.safe_load((profiles_root / profile / "profile.yaml").read_text())


def new_profile(run, name="work", target="claude-code"):
    ok(run("profile", "new", name, "--target", target))


# --- add -------------------------------------------------------------------


def test_add_shorthand_with_path_records_source(run, upstream, profiles_root):
    repo = upstream("acme/skills")
    repo.write("skills/tdd/SKILL.md", "# tdd v1\n")
    repo.write("skills/tdd/refs/a.txt", "a\n")
    repo.write("skills/other/SKILL.md", "# other\n")
    commit = repo.commit()
    new_profile(run)

    ok(run("add", "acme/skills#skills/tdd", "-p", "work"))

    folder = profiles_root / "work" / "skills" / "tdd"
    assert (folder / "SKILL.md").read_text() == "# tdd v1\n"
    assert (folder / "refs" / "a.txt").read_text() == "a\n"
    assert not (folder / ".git").exists()
    assert not (profiles_root / "work" / "skills" / "other").exists()
    entry = read_yaml(profiles_root, "work")["skills"]["tdd"]
    assert entry["enabled"] is True
    source = entry["source"]
    assert source["repo"] == "acme/skills"
    assert source["path"] == "skills/tdd"
    assert source["commit"] == commit


def test_add_git_url_of_single_skill_repo_names_item_after_repo(
    run, upstream, profiles_root
):
    repo = upstream("acme/review-skill")
    repo.write("SKILL.md", "# review\n")
    commit = repo.commit()
    new_profile(run)

    ok(run("add", repo.url, "-p", "work"))

    folder = profiles_root / "work" / "skills" / "review-skill"
    assert (folder / "SKILL.md").read_text() == "# review\n"
    source = read_yaml(profiles_root, "work")["skills"]["review-skill"]["source"]
    assert source["repo"] == repo.url
    assert source["commit"] == commit
    assert "path" not in source


def test_add_repo_with_several_skills_adds_each_with_its_own_path(
    run, upstream, profiles_root
):
    repo = upstream("acme/pack")
    repo.write("skills/one/SKILL.md", "# one\n")
    repo.write("skills/two/SKILL.md", "# two\n")
    repo.write("README.md", "pack\n")
    commit = repo.commit()
    new_profile(run)

    result = ok(run("add", "acme/pack", "-p", "work", "--json"))

    data = json.loads(result.output)
    assert sorted(data["items"]) == ["one", "two"]
    skills = read_yaml(profiles_root, "work")["skills"]
    one = skills["one"]["source"]
    assert (one["repo"], one["path"], one["commit"]) == (
        "acme/pack",
        "skills/one",
        commit,
    )
    assert skills["two"]["source"]["path"] == "skills/two"
    assert (profiles_root / "work" / "skills" / "two" / "SKILL.md").exists()


def test_add_with_ref_records_ref_and_fetches_that_branch(run, upstream, profiles_root):
    repo = upstream("acme/skills")
    repo.write("SKILL.md", "# main\n")
    repo.commit()
    repo.write("SKILL.md", "# beta\n")
    beta = repo.commit(branch="beta")
    new_profile(run)

    ok(run("add", "acme/skills", "--ref", "beta", "-p", "work"))

    assert (profiles_root / "work" / "skills" / "skills" / "SKILL.md").read_text() == (
        "# beta\n"
    )
    source = read_yaml(profiles_root, "work")["skills"]["skills"]["source"]
    assert source["ref"] == "beta"
    assert source["commit"] == beta


def test_add_into_active_profile_links_item(run, upstream, claude_dir):
    repo = upstream("acme/tdd")
    repo.write("SKILL.md", "# tdd\n")
    repo.commit()
    new_profile(run)
    ok(run("use", "work"))

    ok(run("add", "acme/tdd"))

    assert (claude_dir / "tdd" / "SKILL.md").read_text() == "# tdd\n"


def test_add_missing_repo_fails_cleanly(run, profiles_root):
    new_profile(run)

    result = fails(run("add", "acme/missing", "-p", "work"))

    assert "acme/missing" in result.output
    assert read_yaml(profiles_root, "work")["skills"] == {}
    assert list((profiles_root / "work" / "skills").iterdir()) == []


def test_add_path_without_skill_fails_and_adds_nothing(run, upstream, profiles_root):
    repo = upstream("acme/empty")
    repo.write("docs/readme.md", "nothing\n")
    repo.commit()
    new_profile(run)

    result = fails(run("add", "acme/empty#docs", "-p", "work"))

    assert "SKILL.md" in result.output
    assert read_yaml(profiles_root, "work")["skills"] == {}


def test_add_of_existing_item_name_adds_none_of_the_skills(
    run, upstream, profiles_root, tmp_path
):
    local = tmp_path / "local" / "two"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text("# mine\n")
    repo = upstream("acme/pack")
    repo.write("skills/one/SKILL.md", "# one\n")
    repo.write("skills/two/SKILL.md", "# two\n")
    repo.commit()
    new_profile(run)
    ok(run("add", str(local), "-p", "work"))

    fails(run("add", "acme/pack", "-p", "work"))

    assert list(read_yaml(profiles_root, "work")["skills"]) == ["two"]
    assert not (profiles_root / "work" / "skills" / "one").exists()
    assert (profiles_root / "work" / "skills" / "two" / "SKILL.md").read_text() == (
        "# mine\n"
    )


# --- update ----------------------------------------------------------------


@pytest.fixture
def sourced(run, upstream, tmp_path):
    """Profile 'work' with sourced items 'tdd' and 'lint' and a local item."""
    repo = upstream("acme/skills")
    repo.write("tdd/SKILL.md", "# tdd v1\n")
    repo.write("lint/SKILL.md", "# lint v1\n")
    first = repo.commit()
    local = tmp_path / "local" / "mine"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text("# mine\n")
    new_profile(run)
    ok(run("add", "acme/skills#tdd", "-p", "work"))
    ok(run("add", "acme/skills#lint", "-p", "work"))
    ok(run("add", str(local), "-p", "work"))
    repo.first = first
    return repo


def check(run, *extra):
    result = ok(run("update", "--check", "-p", "work", "--json", *extra))
    return {row["item"]: row for row in json.loads(result.output)["items"]}


def test_check_reports_up_to_date_items(run, sourced):
    rows = check(run)

    assert set(rows) == {"tdd", "lint"}
    assert rows["tdd"]["update_available"] is False
    assert rows["tdd"]["current"] == sourced.first


def test_check_reports_newer_upstream_commit_without_changing_anything(
    run, sourced, profiles_root
):
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    second = sourced.commit()
    before = (profiles_root / "work" / "profile.yaml").read_text()

    rows = check(run)

    assert rows["tdd"]["update_available"] is True
    assert rows["tdd"]["latest"] == second
    # Both items come from the same repository and branch, so both see it.
    assert rows["lint"]["update_available"] is True
    assert (profiles_root / "work" / "profile.yaml").read_text() == before
    tdd = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    assert tdd.read_text() == "# tdd v1\n"


def test_check_human_output_names_items_with_updates(run, sourced):
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    result = ok(run("update", "--check", "-p", "work"))

    assert "tdd" in result.output
    assert "mine" not in result.output


def test_update_item_applies_and_records_new_commit(run, sourced, profiles_root):
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.write("tdd/extra.md", "extra\n")
    sourced.write("lint/SKILL.md", "# lint v2\n")
    second = sourced.commit()

    ok(run("update", "tdd", "-p", "work"))

    folder = profiles_root / "work" / "skills"
    assert (folder / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert (folder / "tdd" / "extra.md").read_text() == "extra\n"
    assert (folder / "lint" / "SKILL.md").read_text() == "# lint v1\n"
    skills = read_yaml(profiles_root, "work")["skills"]
    assert skills["tdd"]["source"]["commit"] == second
    assert skills["lint"]["source"]["commit"] == sourced.first
    assert check(run)["tdd"]["update_available"] is False


def test_update_removes_files_deleted_upstream(run, sourced, profiles_root):
    sourced.write("tdd/old.md", "old\n")
    sourced.commit()
    ok(run("update", "tdd", "-p", "work"))
    (sourced.work / "tdd" / "old.md").unlink()
    sourced.commit()

    ok(run("update", "tdd", "-p", "work"))

    assert not (profiles_root / "work" / "skills" / "tdd" / "old.md").exists()


def test_update_all_changes_sourced_items_but_never_local_ones(
    run, sourced, profiles_root
):
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.write("lint/SKILL.md", "# lint v2\n")
    sourced.commit()
    mine = profiles_root / "work" / "skills" / "mine"
    before_mine = (mine / "SKILL.md").read_text()

    ok(run("update", "-p", "work"))

    skills = profiles_root / "work" / "skills"
    assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert (skills / "lint" / "SKILL.md").read_text() == "# lint v2\n"
    assert (mine / "SKILL.md").read_text() == before_mine
    assert "source" not in read_yaml(profiles_root, "work")["skills"]["mine"]


def test_update_of_item_without_source_is_refused(run, sourced, profiles_root):
    result = fails(run("update", "mine", "-p", "work"))

    assert "no source" in result.output


def test_update_refreshes_links_of_active_profile(
    run, sourced, claude_dir, isolated_homes
):
    ok(run("use", "work"))
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    ok(run("update", "tdd"))

    assert (claude_dir / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    state = json.loads((isolated_homes.respec_home / "state.json").read_text())
    assert state["active_profile"] == "work"
    recorded = sorted(Path(item["path"]).name for item in state["installed"])
    assert recorded == ["lint", "mine", "tdd"]


def test_check_reports_local_edits(run, sourced, profiles_root):
    (profiles_root / "work" / "skills" / "tdd" / "SKILL.md").write_text("# edited\n")

    rows = check(run)

    assert rows["tdd"]["modified"] is True
    assert rows["lint"]["modified"] is False


def test_update_over_local_edits_asks_and_keeps_them_when_declined(
    run, sourced, profiles_root
):
    edited = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    edited.write_text("# edited\n")
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    result = run("update", "tdd", "-p", "work", input="n\n")

    assert "local edits" in result.output
    assert edited.read_text() == "# edited\n"
    source = read_yaml(profiles_root, "work")["skills"]["tdd"]["source"]
    assert source["commit"] == sourced.first


def test_update_over_local_edits_overwrites_when_confirmed(run, sourced, profiles_root):
    edited = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    edited.write_text("# edited\n")
    (edited.parent / "notes.md").write_text("mine\n")
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    ok(run("update", "tdd", "-p", "work", input="y\n"))

    assert edited.read_text() == "# tdd v2\n"
    assert not (edited.parent / "notes.md").exists()


def test_update_with_yes_overwrites_local_edits_without_asking(
    run, sourced, profiles_root
):
    edited = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    edited.write_text("# edited\n")
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    ok(run("update", "tdd", "-p", "work", "--yes"))

    assert edited.read_text() == "# tdd v2\n"


def test_update_json_skips_locally_edited_items_without_yes(
    run, sourced, profiles_root
):
    edited = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    edited.write_text("# edited\n")
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.write("lint/SKILL.md", "# lint v2\n")
    sourced.commit()

    result = ok(run("update", "-p", "work", "--json"))

    rows = {row["item"]: row for row in json.loads(result.output)["items"]}
    assert rows["tdd"]["result"] == "skipped-local-edits"
    assert rows["lint"]["result"] == "updated"
    assert edited.read_text() == "# edited\n"


def test_update_of_up_to_date_item_reports_nothing_to_do(run, sourced):
    result = ok(run("update", "tdd", "-p", "work", "--json"))

    rows = json.loads(result.output)["items"]
    assert rows == [
        {
            "item": "tdd",
            "result": "up-to-date",
            "current": sourced.first,
            "latest": sourced.first,
        }
    ]


# --- profile install --------------------------------------------------------


def make_modpack(upstream, skills_upstream):
    pack = upstream("acme/modpack")
    pack.write(
        "profile.yaml",
        yaml.safe_dump(
            {
                "targets": ["claude-code", "agents"],
                "skills": {
                    "tdd": {
                        "enabled": True,
                        "source": {
                            "repo": "acme/skills",
                            "path": "tdd",
                            "commit": skills_upstream.first,
                        },
                    },
                    "house": {"enabled": False},
                },
            }
        ),
    )
    pack.write("skills/tdd/SKILL.md", "# tdd v1\n")
    pack.write("skills/house/SKILL.md", "# house\n")
    pack.write("README.md", "modpack\n")
    pack.commit()
    return pack


@pytest.fixture
def skills_repo(upstream):
    repo = upstream("acme/skills")
    repo.write("tdd/SKILL.md", "# tdd v1\n")
    repo.first = repo.commit()
    return repo


def test_profile_install_copies_whole_profile(
    run, upstream, skills_repo, profiles_root
):
    make_modpack(upstream, skills_repo)

    ok(run("profile", "install", "acme/modpack"))

    folder = profiles_root / "modpack"
    data = read_yaml(profiles_root, "modpack")
    assert data["targets"] == ["claude-code", "agents"]
    assert data["skills"]["house"] == {"enabled": False}
    assert data["skills"]["tdd"]["source"]["repo"] == "acme/skills"
    assert (folder / "skills" / "house" / "SKILL.md").read_text() == "# house\n"
    assert not (folder / ".git").exists()
    shown = json.loads(ok(run("profile", "show", "modpack", "--json")).output)
    assert {row["name"] for row in shown["skills"]} == {"tdd", "house"}


def test_profile_install_with_name_and_then_owned_locally(
    run, upstream, skills_repo, profiles_root
):
    pack = make_modpack(upstream, skills_repo)
    ok(run("profile", "install", pack.url, "--name", "mine"))

    # Later changes to the modpack never reach the installed profile...
    pack.write("skills/house/SKILL.md", "# house v2\n")
    pack.commit()
    # ...but its items keep their own sources and update from those.
    skills_repo.write("tdd/SKILL.md", "# tdd v2\n")
    skills_repo.commit()
    rows = {
        row["item"]: row
        for row in json.loads(
            ok(run("update", "--check", "-p", "mine", "--json")).output
        )["items"]
    }
    assert set(rows) == {"tdd"}
    assert rows["tdd"]["update_available"] is True

    ok(run("update", "-p", "mine", "--yes"))

    folder = profiles_root / "mine" / "skills"
    assert (folder / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert (folder / "house" / "SKILL.md").read_text() == "# house\n"


def test_profile_install_refuses_existing_profile(run, upstream, skills_repo):
    make_modpack(upstream, skills_repo)
    new_profile(run, "modpack")

    result = fails(run("profile", "install", "acme/modpack"))

    assert "already exists" in result.output


def test_profile_install_of_invalid_profile_leaves_nothing(
    run, upstream, profiles_root
):
    pack = upstream("acme/broken")
    pack.write("profile.yaml", yaml.safe_dump({"targets": ["nowhere"]}))
    pack.commit()

    result = fails(run("profile", "install", "acme/broken"))

    assert "nowhere" in result.output
    assert not (profiles_root / "broken").exists()


def test_profile_install_rejects_listed_item_without_folder(
    run, upstream, profiles_root
):
    pack = upstream("acme/holes")
    pack.write(
        "profile.yaml",
        yaml.safe_dump({"targets": ["agents"], "skills": {"gone": {"enabled": True}}}),
    )
    pack.commit()

    result = fails(run("profile", "install", "acme/holes"))

    assert "gone" in result.output
    assert not (profiles_root / "holes").exists()


# --- review round 1: safety -------------------------------------------------


def write_profile_yaml(profiles_root, profile, data):
    (profiles_root / profile / "profile.yaml").write_text(yaml.safe_dump(data))


def test_option_like_repo_in_profile_is_rejected_and_runs_nothing(
    run, sourced, profiles_root, tmp_path
):
    marker = tmp_path / "PWNED"
    data = read_yaml(profiles_root, "work")
    data["skills"]["tdd"]["source"]["repo"] = f"--upload-pack=touch {marker};false"
    write_profile_yaml(profiles_root, "work", data)

    result = fails(run("update", "--check", "-p", "work"))

    assert not marker.exists()
    assert "must not start with '-'" in result.output


def test_option_like_ref_on_add_is_rejected_and_runs_nothing(
    run, upstream, profiles_root, tmp_path
):
    marker = tmp_path / "PWNED"
    repo = upstream("acme/tdd")
    repo.write("SKILL.md", "# tdd\n")
    repo.commit()
    new_profile(run)

    result = fails(
        run(
            "add", "acme/tdd", f"--ref=--upload-pack=touch {marker};false", "-p", "work"
        )
    )

    assert not marker.exists()
    assert "must not start with '-'" in result.output
    assert read_yaml(profiles_root, "work")["skills"] == {}


def test_option_like_ref_on_profile_install_is_rejected_and_runs_nothing(
    run, upstream, skills_repo, profiles_root, tmp_path
):
    marker = tmp_path / "PWNED"
    make_modpack(upstream, skills_repo)

    fails(
        run("profile", "install", "acme/modpack", f"--ref=--upload-pack=touch {marker}")
    )

    assert not marker.exists()
    assert not (profiles_root / "modpack").exists()


def test_option_like_path_in_spec_is_rejected(run, upstream, profiles_root):
    repo = upstream("acme/tdd")
    repo.write("SKILL.md", "# tdd\n")
    repo.commit()
    new_profile(run)

    result = fails(run("add", "acme/tdd#-x", "-p", "work"))

    assert "must not start with '-'" in result.output


def test_git_treats_option_like_url_as_a_repository_not_an_option(tmp_path):
    """Defense in depth: even unvalidated values never reach git as options."""
    from respec import sources
    from respec.errors import RespecError

    marker = tmp_path / "PWNED"
    evil = f"--upload-pack=touch {marker};false"
    with pytest.raises(RespecError):
        sources.remote_commit(evil, None, "evil")
    with pytest.raises(RespecError):
        with sources.checkout(evil, None, "evil"):
            pass
    with pytest.raises(RespecError):
        with sources.checkout((tmp_path / "none").as_uri(), evil, "evil"):
            pass
    assert not marker.exists()


@pytest.mark.parametrize("path", ["../../outside", "ABSOLUTE", "tdd/../.."])
def test_source_path_escaping_the_repository_is_rejected(
    run, sourced, profiles_root, tmp_path, path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("# outside\n")
    data = read_yaml(profiles_root, "work")
    data["skills"]["tdd"]["source"]["path"] = (
        str(outside) if path == "ABSOLUTE" else path
    )
    write_profile_yaml(profiles_root, "work", data)
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    result = fails(run("update", "tdd", "-p", "work", "--yes"))

    assert "inside the repository" in result.output
    tdd = profiles_root / "work" / "skills" / "tdd" / "SKILL.md"
    assert tdd.read_text() == "# tdd v1\n"


def test_failed_swap_restores_the_item_folder(run, sourced, profiles_root, monkeypatch):
    from respec import sources

    real_replace = sources.os.replace

    def failing_replace(src, dst):
        if str(src).endswith(".incoming"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(sources.os, "replace", failing_replace)
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    run("update", "tdd", "-p", "work", "--yes")

    skills = profiles_root / "work" / "skills"
    assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert sorted(p.name for p in skills.iterdir()) == ["lint", "mine", "tdd"]
    source = read_yaml(profiles_root, "work")["skills"]["tdd"]["source"]
    assert source["commit"] == sourced.first


def test_refresh_error_leaves_no_old_folders(run, sourced, profiles_root, monkeypatch):
    from respec import switch
    from respec.errors import RespecError

    ok(run("use", "work"))
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    def broken_use(*args, **kwargs):
        raise RespecError("target folder vanished")

    monkeypatch.setattr(switch, "use", broken_use)

    fails(run("update", "tdd", "--yes"))

    skills = profiles_root / "work" / "skills"
    assert sorted(p.name for p in skills.iterdir()) == ["lint", "mine", "tdd"]
    # Files and profile.yaml agree: the new content and the new commit.
    assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    source = read_yaml(profiles_root, "work")["skills"]["tdd"]["source"]
    assert source["commit"] != sourced.first


def test_inherited_git_dir_is_ignored(
    run, upstream, profiles_root, tmp_path, monkeypatch
):
    other = tmp_path / "other.git"
    git(tmp_path, "init", "-q", "--bare", str(other))
    repo = upstream("acme/tdd")
    repo.write("SKILL.md", "# tdd\n")
    repo.commit()
    new_profile(run)
    monkeypatch.setenv("GIT_DIR", str(other))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "elsewhere"))

    ok(run("add", "acme/tdd", "-p", "work"))

    assert not (other / "FETCH_HEAD").exists()
    assert not (tmp_path / "elsewhere").exists()
    assert (profiles_root / "work" / "skills" / "tdd" / "SKILL.md").exists()


@pytest.mark.parametrize("kind", ["empty-dir", "dir-symlink"])
def test_check_sees_added_folders_and_symlinks_as_local_edits(
    run, sourced, profiles_root, tmp_path, kind
):
    folder = profiles_root / "work" / "skills" / "tdd"
    if kind == "empty-dir":
        (folder / "notes").mkdir()
    else:
        (tmp_path / "target").mkdir()
        (folder / "link").symlink_to(tmp_path / "target")

    assert check(run)["tdd"]["modified"] is True


# --- unknown entries (ticket 004) and symlinks ------------------------------


def test_add_from_git_into_active_profile_is_blocked_by_unknown_entries(
    run, upstream, profiles_root, claude_dir
):
    repo = upstream("acme/tdd")
    repo.write("SKILL.md", "# tdd\n")
    repo.commit()
    new_profile(run)
    ok(run("use", "work"))
    (claude_dir / "stranger").mkdir(parents=True)
    (claude_dir / "stranger" / "SKILL.md").write_text("# not respec\n")

    result = fails(run("add", "acme/tdd"))

    assert "stranger" in result.output
    assert read_yaml(profiles_root, "work")["skills"] == {}
    assert not (profiles_root / "work" / "skills" / "tdd").exists()
    assert not (claude_dir / "tdd").exists()
    assert (claude_dir / "stranger" / "SKILL.md").read_text() == "# not respec\n"


def test_update_of_active_profile_is_blocked_by_unknown_entries(
    run, sourced, profiles_root, claude_dir
):
    ok(run("use", "work"))
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()
    (claude_dir / "stranger").mkdir()

    result = fails(run("update", "tdd", "--yes"))

    assert "stranger" in result.output
    skills = profiles_root / "work" / "skills"
    assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert sorted(p.name for p in skills.iterdir()) == ["lint", "mine", "tdd"]
    source = read_yaml(profiles_root, "work")["skills"]["tdd"]["source"]
    assert source["commit"] == sourced.first
    assert (claude_dir / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"


@pytest.fixture
def secret(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir()
    (folder / "id_rsa").write_text("PRIVATE KEY\n")
    return folder


def symlinked_repo(upstream, secret, slug, prefix=""):
    repo = upstream(slug)
    repo.write(f"{prefix}SKILL.md", "# evil\n")
    (repo.work / prefix / "key.txt").symlink_to(secret / "id_rsa")
    (repo.work / prefix / "keys").symlink_to(secret)
    repo.commit()
    return repo


def no_secret_copied(root):
    for file in root.rglob("*"):
        if file.is_file() and not file.is_symlink():
            assert "PRIVATE KEY" not in file.read_text(errors="ignore"), file


def test_add_refuses_symlinks_pointing_outside_the_repository(
    run, upstream, secret, profiles_root
):
    symlinked_repo(upstream, secret, "acme/evil")
    new_profile(run)

    result = fails(run("add", "acme/evil", "-p", "work"))

    assert "symlink" in result.output
    no_secret_copied(profiles_root)
    assert read_yaml(profiles_root, "work")["skills"] == {}
    assert not (profiles_root / "work" / "skills" / "evil").exists()


def test_add_keeps_symlinks_inside_the_skill(run, upstream, profiles_root):
    repo = upstream("acme/linked")
    repo.write("SKILL.md", "# linked\n")
    repo.write("docs/guide.md", "guide\n")
    (repo.work / "guide.md").symlink_to("docs/guide.md")
    repo.commit()
    new_profile(run)

    ok(run("add", "acme/linked", "-p", "work"))

    copied = profiles_root / "work" / "skills" / "linked" / "guide.md"
    assert copied.read_text() == "guide\n"


def test_update_refuses_symlinks_pointing_outside_the_repository(
    run, sourced, secret, profiles_root
):
    (sourced.work / "tdd" / "key.txt").symlink_to(secret / "id_rsa")
    sourced.commit()

    result = fails(run("update", "tdd", "-p", "work", "--yes"))

    assert "symlink" in result.output
    no_secret_copied(profiles_root)
    skills = profiles_root / "work" / "skills"
    assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert sorted(p.name for p in skills.iterdir()) == ["lint", "mine", "tdd"]


def test_profile_install_refuses_symlinks_pointing_outside_the_repository(
    run, upstream, secret, profiles_root
):
    pack = upstream("acme/evilpack")
    pack.write(
        "profile.yaml",
        yaml.safe_dump({"targets": ["agents"], "skills": {"a": {"enabled": True}}}),
    )
    pack.write("skills/a/SKILL.md", "# a\n")
    (pack.work / "skills" / "a" / "keys").symlink_to(secret)
    pack.commit()

    result = fails(run("profile", "install", "acme/evilpack"))

    assert "symlink" in result.output
    no_secret_copied(profiles_root)
    assert not (profiles_root / "evilpack").exists()


def test_profile_install_refuses_symlinked_profile_file_and_item_folder(
    run, upstream, secret, profiles_root
):
    (secret / "profile.yaml").write_text(
        yaml.safe_dump({"targets": ["agents"], "skills": {"a": {"enabled": True}}})
    )
    (secret / "skills" / "a").mkdir(parents=True)
    (secret / "skills" / "a" / "SKILL.md").write_text("PRIVATE KEY\n")
    pack = upstream("acme/linkedpack")
    pack.write("README.md", "x\n")
    (pack.work / "profile.yaml").symlink_to(secret / "profile.yaml")
    pack.commit()
    other = upstream("acme/linkeditem")
    other.write(
        "profile.yaml",
        yaml.safe_dump({"targets": ["agents"], "skills": {"a": {"enabled": True}}}),
    )
    (other.work / "skills").mkdir()
    (other.work / "skills" / "a").symlink_to(secret / "skills" / "a")
    other.commit()

    assert "symlink" in fails(run("profile", "install", "acme/linkedpack")).output
    assert "symlink" in fails(run("profile", "install", "acme/linkeditem")).output

    no_secret_copied(profiles_root)
    assert not (profiles_root / "linkedpack").exists()
    assert not (profiles_root / "linkeditem").exists()


def test_add_path_to_folder_of_skills_adds_each(run, upstream, profiles_root):
    repo = upstream("acme/nested")
    repo.write("packs/web/one/SKILL.md", "# one\n")
    repo.write("packs/web/two/SKILL.md", "# two\n")
    repo.commit()
    new_profile(run)

    ok(run("add", "acme/nested#packs/web", "-p", "work"))

    skills = read_yaml(profiles_root, "work")["skills"]
    assert skills["one"]["source"]["path"] == "packs/web/one"
    assert skills["two"]["source"]["path"] == "packs/web/two"


# --- review round 2: symlinks behind in-repo links, transports, local repos -


def nested_escape(repo, secret, skill="skill", variant="file"):
    """``skill/link -> ../other`` (inside the repo) hiding an escaping link."""
    repo.write(f"{skill}/SKILL.md", "# skill\n")
    other = repo.work / "other"
    other.mkdir(exist_ok=True)
    if variant == "file":
        (other / "evil").symlink_to(secret)
    elif variant == "chain":
        (other / "c1").symlink_to("c2")
        (other / "c2").symlink_to(secret / "id_rsa")
    elif variant == "dir":
        (other / "keys").symlink_to(secret, target_is_directory=True)
    depth = "../" * (skill.count("/") + 1)
    (repo.work / skill / "link").symlink_to(f"{depth}other")
    repo.write("other/plain.md", "plain\n")


@pytest.mark.parametrize("variant", ["file", "chain", "dir"])
def test_add_refuses_escaping_symlink_behind_in_repo_folder_link(
    run, upstream, secret, profiles_root, variant
):
    repo = upstream("acme/nest")
    nested_escape(repo, secret, variant=variant)
    repo.commit()
    new_profile(run)

    result = fails(run("add", "acme/nest#skill", "-p", "work"))

    assert "symlink" in result.output
    no_secret_copied(profiles_root)
    assert read_yaml(profiles_root, "work")["skills"] == {}
    assert not (profiles_root / "work" / "skills" / "skill").exists()


def test_profile_install_refuses_escaping_symlink_behind_folder_link(
    run, upstream, secret, profiles_root
):
    pack = upstream("acme/pk")
    pack.write(
        "profile.yaml",
        yaml.safe_dump({"targets": ["agents"], "skills": {"a": {"enabled": True}}}),
    )
    nested_escape(pack, secret, skill="skills/a")
    pack.commit()

    result = fails(run("profile", "install", "acme/pk"))

    assert "symlink" in result.output
    no_secret_copied(profiles_root)
    assert not (profiles_root / "pk").exists()


def test_update_refuses_escaping_symlink_behind_folder_link(
    run, sourced, secret, profiles_root
):
    other = sourced.work / "other"
    other.mkdir()
    (other / "evil").symlink_to(secret)
    (sourced.work / "tdd" / "link").symlink_to("../other")
    sourced.commit()

    result = fails(run("update", "tdd", "-p", "work", "--yes"))

    assert "symlink" in result.output
    no_secret_copied(profiles_root)
    skills = profiles_root / "work" / "skills"
    assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert sorted(p.name for p in skills.iterdir()) == ["lint", "mine", "tdd"]


def test_symlink_loop_is_a_clean_error_and_adds_nothing(run, upstream, profiles_root):
    repo = upstream("acme/loop")
    repo.write("skill/SKILL.md", "# skill\n")
    (repo.work / "other").mkdir()
    (repo.work / "other" / "back").symlink_to("../skill")
    (repo.work / "skill" / "link").symlink_to("../other")
    repo.commit()
    new_profile(run)

    result = run("add", "acme/loop#skill", "-p", "work")

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "symlink" in result.output
    assert read_yaml(profiles_root, "work")["skills"] == {}
    assert list((profiles_root / "work" / "skills").iterdir()) == []


def test_remote_helper_transports_are_refused(tmp_path, monkeypatch):
    from respec import sources
    from respec.errors import RespecError

    marker = tmp_path / "HELPER_RAN"
    helpers = tmp_path / "bin"
    helpers.mkdir()
    helper = helpers / "git-remote-evil"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{helpers}:{os.environ['PATH']}")

    with pytest.raises(RespecError):
        sources.remote_commit("evil::anything", None, "evil")

    assert not marker.exists()


@pytest.mark.parametrize("kind", ["absolute", "relative", "file-url", "helper"])
def test_profile_repo_naming_a_local_path_is_rejected(
    run, sourced, profiles_root, tmp_path, kind
):
    local = tmp_path / "elsewhere" / "repo"
    local.parent.mkdir()
    git(tmp_path, "clone", "-q", "--bare", sourced.url, str(local))
    repo = {
        "absolute": str(local),
        "relative": "../elsewhere/repo",
        "file-url": local.as_uri(),
        "helper": "fd::3",
    }[kind]
    data = read_yaml(profiles_root, "work")
    data["skills"]["tdd"]["source"]["repo"] = repo
    write_profile_yaml(profiles_root, "work", data)

    result = fails(run("update", "--check", "-p", "work"))

    assert "repo" in result.output and "URL" in result.output


def test_file_url_under_the_configured_base_url_is_allowed(run, sourced):
    assert check(run)["tdd"]["update_available"] is False


def test_update_in_copy_mode_refreshes_copies_and_records_their_digest(
    run, sourced, claude_dir, isolated_homes, monkeypatch
):
    from respec import unknown

    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    monkeypatch.setattr(os, "symlink", refuse)
    ok(run("use", "work"))
    sourced.write("tdd/SKILL.md", "# tdd v2\n")
    sourced.commit()

    ok(run("update", "tdd", "--yes"))

    copy = claude_dir / "tdd"
    assert not copy.is_symlink()
    assert (copy / "SKILL.md").read_text() == "# tdd v2\n"
    state = json.loads((isolated_homes.respec_home / "state.json").read_text())
    recorded = {Path(item["path"]).name: item for item in state["installed"]}
    assert recorded["tdd"]["mode"] == "copy"
    assert recorded["tdd"]["digest"] == unknown.digest(copy)
    # The refreshed copy counts as managed: a later switch is not blocked.
    ok(run("use", "work"))


# --- fix-4: hardening -------------------------------------------------------


def tree_bytes(root: Path) -> int:
    return sum(
        file.stat().st_size
        for file in root.rglob("*")
        if file.is_file() and not file.is_symlink()
    )


def test_nested_folder_links_cannot_multiply_the_copied_files(
    run, upstream, profiles_root
):
    repo = upstream("acme/bomb")
    repo.write("SKILL.md", "# bomb\n")
    repo.write("l0/blob", "x" * 10_000)
    for level in range(1, 7):
        (repo.work / f"l{level}").mkdir()
        for name in ("a", "b"):
            (repo.work / f"l{level}" / name).symlink_to(f"../l{level - 1}")
    repo.commit()
    new_profile(run)

    result = fails(run("add", "acme/bomb", "-p", "work"))

    assert "symlink" in result.output and "folder" in result.output
    # Expanding the links would write 2**6 copies of the 10 kB blob.
    assert tree_bytes(profiles_root) < 10_000
    assert read_yaml(profiles_root, "work")["skills"] == {}


def test_sibling_folder_link_loop_is_a_short_readable_error(
    run, upstream, profiles_root
):
    repo = upstream("acme/loops")
    repo.write("SKILL.md", "# loops\n")
    for one, other in (("a", "e"), ("e", "a")):
        (repo.work / one).mkdir()
        (repo.work / one / "c").symlink_to(f"../{other}")
    repo.commit()
    new_profile(run)

    result = fails(run("add", "acme/loops", "-p", "work"))

    message = result.output.strip()
    assert "symlink" in message
    assert "respec-check-" not in message and "Errno" not in message
    assert len(message) < 300, message
    assert read_yaml(profiles_root, "work")["skills"] == {}


def strip_commit(upstream, skills_repo):
    pack = make_modpack(upstream, skills_repo)
    data = yaml.safe_load((pack.work / "profile.yaml").read_text())
    del data["skills"]["tdd"]["source"]["commit"]
    pack.write("profile.yaml", yaml.safe_dump(data))
    pack.commit()


def test_check_of_item_without_recorded_commit_reports_unknown(
    run, upstream, skills_repo
):
    strip_commit(upstream, skills_repo)
    ok(run("profile", "install", "acme/modpack"))

    result = ok(run("update", "--check", "-p", "modpack"))

    assert f"tdd  update available unknown -> {skills_repo.first[:12]}" in (
        result.output
    )


def test_update_of_item_without_recorded_commit_fetches_and_records_it(
    run, upstream, skills_repo, profiles_root
):
    strip_commit(upstream, skills_repo)
    ok(run("profile", "install", "acme/modpack"))

    result = ok(run("update", "-p", "modpack", "--yes"))

    assert f"tdd  updated unknown -> {skills_repo.first[:12]}" in result.output
    source = read_yaml(profiles_root, "modpack")["skills"]["tdd"]["source"]
    assert source["commit"] == skills_repo.first
    assert source["digest"].startswith("sha256:")


def test_failed_update_of_item_without_commit_changes_nothing(
    run, upstream, skills_repo, profiles_root
):
    strip_commit(upstream, skills_repo)
    ok(run("profile", "install", "acme/modpack"))
    (skills_repo.work / "tdd" / "SKILL.md").unlink()
    skills_repo.write("tdd/README.md", "moved\n")
    skills_repo.commit()
    folder = profiles_root / "modpack"
    before = (folder / "profile.yaml").read_text()

    result = fails(run("update", "-p", "modpack", "--yes"))

    assert "tdd  error:" in result.output
    assert (folder / "profile.yaml").read_text() == before
    assert (folder / "skills" / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert sorted(p.name for p in (folder / "skills").iterdir()) == ["house", "tdd"]


def test_names_with_a_trailing_newline_are_rejected(run, profiles_root):
    result = run("profile", "new", "bad\n", "--target", "agents")

    assert result.exit_code != 0
    assert not any(profiles_root.glob("bad*"))


@pytest.mark.parametrize(
    "key, value",
    [
        ("repo", "acme/skills\n"),
        ("repo", "https://example.invalid/r\n"),
        ("repo", "git@example.invalid:acme/r\n"),
        ("ref", "main\n"),
    ],
)
def test_source_values_with_a_trailing_newline_are_rejected(key, value):
    from respec import profiles

    assert profiles.source_value_problem(key, value) is not None


def test_commit_ref_with_a_trailing_newline_is_not_taken_as_a_commit(skills_repo):
    from respec import sources
    from respec.errors import RespecError

    with pytest.raises(RespecError):
        sources.remote_commit(skills_repo.url, skills_repo.first + "\n", "skills")


@pytest.mark.parametrize("repo", ["../x", "./x", "acme/..", "acme/.", "../.."])
def test_shorthand_with_dot_segments_is_rejected(run, sourced, profiles_root, repo):
    data = read_yaml(profiles_root, "work")
    data["skills"]["tdd"]["source"]["repo"] = repo
    write_profile_yaml(profiles_root, "work", data)

    result = fails(run("update", "--check", "-p", "work"))

    assert "repo" in result.output and "URL" in result.output


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """An ``ssh`` on PATH that records how git ran it and then fails."""
    bin_dir = tmp_path / "ssh-bin"
    bin_dir.mkdir()
    log = tmp_path / "ssh.log"
    script = bin_dir / "ssh"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "ssh $* prompt=$GIT_TERMINAL_PROMPT" >> "{log}"\n'
        "exit 255\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    return log


def test_ssh_runs_in_batch_mode_with_prompts_off(fake_ssh):
    from respec import sources
    from respec.errors import RespecError

    with pytest.raises(RespecError):
        sources.remote_commit("git@example.invalid:acme/x", None, "acme/x")

    logged = fake_ssh.read_text()
    assert "BatchMode=yes" in logged
    assert "prompt=0" in logged


def test_users_own_ssh_command_is_kept(fake_ssh):
    from respec import sources
    from respec.errors import RespecError

    config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    config.write_text("[core]\n\tsshCommand = ssh -o User=mine\n")

    with pytest.raises(RespecError):
        sources.remote_commit("git@example.invalid:acme/x", None, "acme/x")

    logged = fake_ssh.read_text()
    assert "User=mine" in logged
    assert "BatchMode" not in logged
