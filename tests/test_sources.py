"""Git sources: add from a repo, update checks and updates, profile install.

Every repository is a local bare repository reached over ``file://``. Git runs
with a temporary HOME and no global or system config, and the ``owner/repo``
shorthand resolves through ``RESPEC_GIT_BASE_URL`` so no test touches GitHub.
"""

from __future__ import annotations

import json
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
