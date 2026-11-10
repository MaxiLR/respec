"""A profile remembers where it was installed from (a local folder or a git
repository): ``profile install`` records it, ``update`` refreshes the skills
from it, adds the skills that are new there and removes the ones that are
gone. respec never writes to the source."""

import json
import shutil

import pytest
import yaml

from test_folder_sources import snapshot
from test_sources import isolated_git, upstream  # noqa: F401  (fixtures)


@pytest.fixture
def profiles_root(isolated_homes):
    return isolated_homes.respec_home / "profiles"


@pytest.fixture
def claude_dir(isolated_homes):
    return isolated_homes.home / ".claude" / "skills"


def read_yaml(profiles_root, profile="pack"):
    return yaml.safe_load((profiles_root / profile / "profile.yaml").read_text())


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def fails(result):
    assert result.exit_code == 1, result.output
    return result


def rows(result):
    return {row["skill"]: row for row in json.loads(result.output)["skills"]}


class Pack:
    """A profile folder outside respec (``profile.yaml`` and ``skills/``) that
    must never change: ``tdd`` (enabled) and ``house`` (disabled)."""

    def __init__(self, folder):
        self.folder = folder
        self.path = str(folder.resolve())
        self.data = {"targets": ["claude-code"], "skills": {}}
        self.skill("tdd", True)
        self.skill("house", False)
        self.write("skills/tdd/refs/note.txt", "note\n")
        self.write("README.md", "a profile\n")
        self.keep()

    def write(self, relative, text):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def save(self):
        self.write("profile.yaml", yaml.safe_dump(self.data, sort_keys=False))

    def skill(self, name, enabled, text=None, **entry):
        """Add a skill (or change one) in ``profile.yaml`` and ``skills/``."""
        self.data["skills"][name] = {"enabled": enabled, **entry}
        self.write(f"skills/{name}/SKILL.md", text or f"# {name} v1\n")
        self.save()

    def drop(self, name):
        del self.data["skills"][name]
        shutil.rmtree(self.folder / "skills" / name)
        self.save()

    def source_of(self, name):
        return f"{self.path}/skills/{name}"

    def keep(self):
        """Remember the folder as the test left it."""
        self.kept = snapshot(self.folder)

    def untouched(self):
        assert snapshot(self.folder) == self.kept
        return True


@pytest.fixture
def pack(tmp_path):
    return Pack(tmp_path / "checkout" / "pack")


@pytest.fixture
def installed(run, pack, profiles_root):
    """Profile ``pack`` installed from the folder and active; returns its
    ``skills`` folder."""
    ok(run("profile", "install", str(pack.folder)))
    ok(run("use", "pack"))
    return profiles_root / "pack" / "skills"


# --- profile install from a folder ---------------------------------------------


def test_install_from_a_folder_copies_the_profile_and_records_its_source(
    run, pack, profiles_root
):
    result = ok(run("profile", "install", str(pack.folder)))

    folder = profiles_root / "pack"
    assert f"Installed profile 'pack' at {folder} (2 skills)" in result.output
    assert f"from {pack.path}" in result.output
    data = read_yaml(profiles_root)
    assert data["source"] == {"folder": pack.path}
    assert data["targets"] == ["claude-code"]
    assert {name: entry["enabled"] for name, entry in data["skills"].items()} == {
        "tdd": True,
        "house": False,
    }
    assert (folder / "skills" / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert (folder / "skills" / "tdd" / "refs" / "note.txt").read_text() == "note\n"
    assert (folder / "skills" / "house" / "SKILL.md").read_text() == "# house v1\n"
    assert sorted(p.name for p in folder.iterdir()) == ["profile.yaml", "skills"]
    assert pack.untouched()


def test_install_from_a_folder_gives_each_skill_a_source_inside_it(
    run, pack, profiles_root
):
    ok(run("profile", "install", str(pack.folder)))

    for name in ("tdd", "house"):
        source = read_yaml(profiles_root)["skills"][name]["source"]
        assert sorted(source) == ["digest", "folder"]
        assert source["folder"] == pack.source_of(name)
        assert source["digest"].startswith("sha256:")


def test_install_json_shows_the_source(run, pack, profiles_root, assert_no_nulls):
    data = assert_no_nulls(
        json.loads(ok(run("profile", "install", str(pack.folder), "--json")).output)
    )

    assert data == {
        "name": "pack",
        "path": str(profiles_root / "pack"),
        "source": {"folder": pack.path},
        "warnings": [],
    }
    assert pack.untouched()


def test_install_stores_a_relative_folder_as_an_absolute_path(
    run, pack, profiles_root, monkeypatch
):
    monkeypatch.chdir(pack.folder.parent)

    ok(run("profile", "install", "pack", "--name", "mine"))

    data = read_yaml(profiles_root, "mine")
    assert data["source"] == {"folder": pack.path}
    assert data["skills"]["tdd"]["source"]["folder"] == pack.source_of("tdd")
    assert pack.untouched()


def test_install_from_a_folder_refuses_a_ref(run, pack, profiles_root):
    result = fails(run("profile", "install", str(pack.folder), "--ref", "main"))

    assert "--ref only applies to git sources" in result.output
    assert not (profiles_root / "pack").exists()


def test_install_from_a_folder_without_profile_yaml_leaves_nothing(
    run, pack, profiles_root
):
    (pack.folder / "profile.yaml").unlink()
    pack.keep()

    result = fails(run("profile", "install", str(pack.folder)))

    assert "has no profile.yaml" in result.output
    assert not (profiles_root / "pack").exists()
    assert pack.untouched()


def test_install_from_a_folder_refuses_a_symlink_that_leaves_a_skill(
    run, pack, profiles_root, tmp_path
):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n")
    (pack.folder / "skills" / "tdd" / "leak.txt").symlink_to(secret)
    pack.keep()

    result = fails(run("profile", "install", str(pack.folder)))

    assert "leak.txt" in result.output
    assert not (profiles_root / "pack").exists()
    assert pack.untouched()


def test_a_skill_with_its_own_git_source_keeps_it(run, pack, profiles_root):
    own = {"repo": "acme/skills", "path": "lint", "commit": "0" * 40}
    pack.skill("lint", True, source=own)
    pack.keep()

    ok(run("profile", "install", str(pack.folder)))

    assert read_yaml(profiles_root)["skills"]["lint"]["source"] == own
    assert pack.untouched()


# --- profile install from git ---------------------------------------------------


def make_git_pack(upstream, slug="acme/pack", prefix=""):
    repo = upstream(slug)
    repo.data = {
        "targets": ["claude-code"],
        "skills": {"tdd": {"enabled": True}, "house": {"enabled": False}},
    }
    repo.prefix = prefix

    def save():
        repo.write(f"{prefix}profile.yaml", yaml.safe_dump(repo.data, sort_keys=False))

    repo.save = save
    save()
    repo.write(f"{prefix}skills/tdd/SKILL.md", "# tdd v1\n")
    repo.write(f"{prefix}skills/house/SKILL.md", "# house v1\n")
    repo.first = repo.commit()
    return repo


def test_install_from_git_records_the_source_of_the_profile_and_its_skills(
    run, upstream, profiles_root, assert_no_nulls
):
    repo = make_git_pack(upstream)

    shown = assert_no_nulls(
        json.loads(ok(run("profile", "install", "acme/pack", "--json")).output)
    )

    data = read_yaml(profiles_root)
    assert data["source"] == {"repo": "acme/pack", "commit": repo.first}
    assert shown["source"] == data["source"]
    for name in ("tdd", "house"):
        source = data["skills"][name]["source"]
        assert sorted(source) == ["commit", "digest", "path", "repo"]
        assert source["repo"] == "acme/pack"
        assert source["path"] == f"skills/{name}"
        assert source["commit"] == repo.first
    assert data["skills"]["house"]["enabled"] is False


def test_install_from_git_records_the_path_and_the_ref(run, upstream, profiles_root):
    repo = make_git_pack(upstream, prefix="profiles/dev/")
    repo.write("profiles/dev/skills/tdd/SKILL.md", "# tdd stable\n")
    stable = repo.commit(branch="stable")

    ok(run("profile", "install", "acme/pack#profiles/dev", "--ref", "stable"))

    data = read_yaml(profiles_root, "dev")
    assert data["source"] == {
        "repo": "acme/pack",
        "path": "profiles/dev",
        "ref": "stable",
        "commit": stable,
    }
    source = data["skills"]["tdd"]["source"]
    assert source["path"] == "profiles/dev/skills/tdd"
    assert source["ref"] == "stable"


def test_a_folder_source_inside_a_git_profile_is_never_trusted(
    run, upstream, profiles_root, tmp_path
):
    """A fetched profile.yaml naming a local folder must not make a later
    update copy from that folder."""
    local = tmp_path / "private" / "tdd"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text("# private files\n")
    repo = make_git_pack(upstream)
    repo.data["source"] = {"folder": str(local.parent)}
    repo.data["skills"]["tdd"]["source"] = {"folder": str(local)}
    repo.save()
    commit = repo.commit()

    ok(run("profile", "install", "acme/pack"))
    data = read_yaml(profiles_root)
    ok(run("update", "-p", "pack", "--yes"))

    assert data["source"] == {"repo": "acme/pack", "commit": commit}
    source = data["skills"]["tdd"]["source"]
    assert "folder" not in source
    assert (source["repo"], source["path"]) == ("acme/pack", "skills/tdd")
    assert read_yaml(profiles_root)["skills"]["tdd"]["source"] == source
    copied = profiles_root / "pack" / "skills" / "tdd" / "SKILL.md"
    assert copied.read_text() == "# tdd v1\n"


# --- update --check and update: the skills of the source -------------------------


def test_check_right_after_install_says_everything_is_current(
    run, installed, pack, assert_no_nulls
):
    text = ok(run("update", "--check")).output
    data = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))

    assert "tdd  up to date" in text and "house  up to date" in text
    assert "local edits" not in text
    assert data == {
        "profile": "pack",
        "source": {"folder": pack.path},
        "skills": [
            {
                "skill": name,
                "folder": pack.source_of(name),
                "update_available": False,
                "modified": False,
            }
            for name in ("tdd", "house")
        ],
        "warnings": [],
    }
    assert pack.untouched()


def test_update_refreshes_a_skill_changed_in_the_source_without_asking(
    run, installed, pack, claude_dir
):
    pack.write("skills/tdd/SKILL.md", "# tdd v2\n")
    pack.keep()

    check = rows(ok(run("update", "--check", "--json")))
    updated = rows(ok(run("update", "--json")))

    assert check["tdd"]["update_available"] is True
    assert check["tdd"]["modified"] is False
    assert updated["tdd"]["result"] == "updated"
    assert updated["house"]["result"] == "up-to-date"
    assert (installed / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert (claude_dir / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert pack.untouched()


def test_check_reports_new_and_gone_skills_and_changes_nothing(
    run, installed, pack, profiles_root, assert_no_nulls
):
    pack.skill("lint", True)
    pack.skill("docs", False)
    pack.drop("house")
    pack.keep()
    before = read_yaml(profiles_root)

    text = ok(run("update", "--check")).output
    data = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))

    assert "house  gone from the source" in text
    assert "lint  new in the source (enabled)" in text
    assert "docs  new in the source (disabled)" in text
    assert data["skills"] == [
        {
            "skill": "tdd",
            "folder": pack.source_of("tdd"),
            "update_available": False,
            "modified": False,
        },
        {
            "skill": "house",
            "folder": pack.source_of("house"),
            "modified": False,
            "gone": True,
        },
        {"skill": "lint", "new": True, "enabled": True},
        {"skill": "docs", "new": True, "enabled": False},
    ]
    assert data["warnings"] == []
    assert read_yaml(profiles_root) == before
    assert sorted(p.name for p in installed.iterdir()) == ["house", "tdd"]
    assert pack.untouched()


def test_update_adds_new_skills_in_the_state_the_source_gives_them(
    run, installed, pack, profiles_root, claude_dir, assert_no_nulls
):
    pack.skill("lint", True)
    pack.skill("docs", False)
    pack.keep()

    data = assert_no_nulls(json.loads(ok(run("update", "--json")).output))

    assert data["skills"][2:] == [
        {
            "skill": "lint",
            "folder": pack.source_of("lint"),
            "result": "added",
            "enabled": True,
        },
        {
            "skill": "docs",
            "folder": pack.source_of("docs"),
            "result": "added",
            "enabled": False,
        },
    ]
    assert data["source"] == {"folder": pack.path}
    skills = read_yaml(profiles_root)["skills"]
    assert list(skills) == ["tdd", "house", "lint", "docs"]
    assert skills["lint"]["enabled"] is True and skills["docs"]["enabled"] is False
    for name in ("lint", "docs"):
        assert skills[name]["source"]["folder"] == pack.source_of(name)
        assert skills[name]["source"]["digest"].startswith("sha256:")
        assert (installed / name / "SKILL.md").read_text() == f"# {name} v1\n"
    assert (claude_dir / "lint").is_symlink()
    assert not (claude_dir / "docs").exists()
    assert pack.untouched()
    # Nothing more to do, and nothing is asked.
    again = rows(ok(run("update", "--json")))
    assert {row["result"] for row in again.values()} == {"up-to-date"}
    assert pack.untouched()


def test_update_says_what_it_added_and_removed(run, installed, pack):
    pack.skill("lint", True)
    pack.drop("house")

    text = ok(run("update")).output

    assert f"lint  added from {pack.source_of('lint')} (enabled)" in text
    assert "house  removed: gone from the source" in text


def test_the_source_only_gives_a_new_skill_its_starting_state(
    run, installed, pack, profiles_root
):
    pack.skill("lint", True)
    ok(run("update"))
    ok(run("disable", "lint"))
    ok(run("enable", "house"))
    pack.write("skills/lint/SKILL.md", "# lint v2\n")
    pack.skill("house", False, text="# house v2\n")
    pack.data["targets"] = ["agents"]
    pack.data["layers"] = {
        "design-principles": {"skills": ["tdd"]},
        "mine": {"exclusive": False, "description": "x", "skills": ["lint"]},
    }
    pack.save()
    pack.keep()

    ok(run("update"))

    data = read_yaml(profiles_root)
    assert data["skills"]["lint"]["enabled"] is False
    assert data["skills"]["house"]["enabled"] is True
    assert data["targets"] == ["claude-code"]
    assert "layers" not in data
    assert (installed / "lint" / "SKILL.md").read_text() == "# lint v2\n"
    assert (installed / "house" / "SKILL.md").read_text() == "# house v2\n"
    assert pack.untouched()


def test_update_removes_skills_gone_from_the_source(
    run, installed, pack, profiles_root, claude_dir, assert_no_nulls
):
    ok(run("layer", "add", "mine", "--additive", "-d", "x"))
    ok(run("layer", "add-skill", "mine", "tdd"))
    pack.drop("tdd")
    pack.keep()
    assert (claude_dir / "tdd").is_symlink()

    data = assert_no_nulls(json.loads(ok(run("update", "--json")).output))

    assert data["skills"] == [
        {
            "skill": "tdd",
            "folder": pack.source_of("tdd"),
            "gone": True,
            "result": "removed",
        },
        {"skill": "house", "folder": pack.source_of("house"), "result": "up-to-date"},
    ]
    assert data["unlinked"] == [str(claude_dir / "tdd")]
    saved = read_yaml(profiles_root)
    assert list(saved["skills"]) == ["house"]
    assert "tdd" not in saved["layers"]["mine"].get("skills", [])
    assert sorted(p.name for p in installed.iterdir()) == ["house"]
    assert not (claude_dir / "tdd").exists()
    assert pack.untouched()


def test_a_gone_skill_with_local_edits_is_kept_unless_confirmed(
    run, installed, pack, profiles_root
):
    pack.drop("tdd")
    pack.keep()
    (installed / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    before = read_yaml(profiles_root)

    check = ok(run("update", "--check"))
    skipped = rows(ok(run("update", "--json")))
    declined = ok(run("update", input="n\n"))

    assert "tdd  gone from the source  (local edits)" in check.output
    assert skipped["tdd"] == {
        "skill": "tdd",
        "folder": pack.source_of("tdd"),
        "gone": True,
        "result": "skipped-local-edits",
    }
    assert "gone from the source" in declined.output
    assert "local edits kept (use --yes to remove)" in declined.output
    assert (installed / "tdd" / "SKILL.md").read_text() == "# tdd edited here\n"
    assert read_yaml(profiles_root) == before
    assert pack.untouched()


@pytest.mark.parametrize("answer", [("--yes",), ()])
def test_a_gone_skill_with_local_edits_is_removed_when_told_to(
    run, installed, pack, profiles_root, answer
):
    pack.drop("tdd")
    pack.keep()
    (installed / "tdd" / "SKILL.md").write_text("# tdd edited here\n")

    ok(run("update", *answer, input=None if answer else "y\n"))

    assert list(read_yaml(profiles_root)["skills"]) == ["house"]
    assert not (installed / "tdd").exists()
    assert pack.untouched()


def test_only_skills_that_came_from_the_source_are_removed(
    run, installed, pack, profiles_root, tmp_path, upstream
):
    """Skills the user added, and skills with a source of their own, stay."""
    mine = tmp_path / "elsewhere" / "mine"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("# mine\n")
    ok(run("add", str(mine)))
    repo = upstream("acme/skills")
    repo.write("up/SKILL.md", "# up\n")
    repo.commit()
    ok(run("add", "acme/skills#up"))
    data = read_yaml(profiles_root)
    data["skills"]["bare"] = {"enabled": True}
    (profiles_root / "pack" / "profile.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False)
    )
    (installed / "bare").mkdir()
    (installed / "bare" / "SKILL.md").write_text("# bare\n")
    pack.drop("house")
    pack.keep()

    check = rows(ok(run("update", "--check", "--json")))
    updated = rows(ok(run("update", "--json")))

    assert [name for name, row in check.items() if row.get("gone")] == ["house"]
    assert updated["house"]["result"] == "removed"
    assert updated["mine"]["result"] == updated["up"]["result"] == "up-to-date"
    assert list(read_yaml(profiles_root)["skills"]) == ["tdd", "mine", "up", "bare"]
    assert sorted(p.name for p in installed.iterdir()) == ["bare", "mine", "tdd", "up"]
    assert pack.untouched()


def test_updating_one_named_skill_neither_adds_nor_removes(
    run, installed, pack, profiles_root
):
    pack.skill("lint", True)
    pack.drop("house")
    pack.write("skills/tdd/SKILL.md", "# tdd v2\n")
    pack.keep()

    check = json.loads(ok(run("update", "--check", "tdd", "--json")).output)
    data = json.loads(ok(run("update", "tdd", "--json")).output)

    assert [row["skill"] for row in check["skills"]] == ["tdd"]
    assert "source" not in check and "source" not in data
    assert data["skills"] == [
        {"skill": "tdd", "folder": pack.source_of("tdd"), "result": "updated"}
    ]
    assert list(read_yaml(profiles_root)["skills"]) == ["tdd", "house"]
    assert pack.untouched()


@pytest.mark.shipped
def test_a_new_skill_named_like_a_shipped_or_global_skill_is_refused(
    run, installed, pack, profiles_root, isolated_homes
):
    shared = isolated_homes.respec_home / "global" / "skills" / "shared"
    shared.mkdir(parents=True)
    (shared / "SKILL.md").write_text("# global shared\n")
    (isolated_homes.respec_home / "config.yaml").write_text(
        yaml.safe_dump({"global": {"skills": ["shared"]}})
    )
    pack.skill("shared", True)
    pack.skill("respec", True)
    pack.skill("lint", True)
    pack.keep()

    result = fails(run("update", "--json"))

    updated = rows(result)
    assert updated["shared"]["result"] == updated["respec"]["result"] == "error"
    assert "cannot add 'shared'" in updated["shared"]["error"]
    assert "cannot add 'respec'" in updated["respec"]["error"]
    assert updated["lint"]["result"] == "added"
    assert list(read_yaml(profiles_root)["skills"]) == ["tdd", "house", "lint"]
    assert sorted(p.name for p in installed.iterdir()) == ["house", "lint", "tdd"]
    assert pack.untouched()


def test_a_profile_without_a_source_is_checked_and_updated_as_before(
    run, installed, pack, profiles_root
):
    data = read_yaml(profiles_root)
    del data["source"]
    (profiles_root / "pack" / "profile.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False)
    )
    pack.skill("lint", True)
    pack.drop("house")
    pack.keep()

    check = json.loads(ok(run("update", "--check", "--json")).output)
    updated = json.loads(ok(run("update", "--json")).output)

    assert "source" not in check and "source" not in updated
    assert list(rows_of(check)) == list(rows_of(updated)) == ["tdd", "house"]
    assert rows_of(check)["house"]["source_missing"] is True
    assert rows_of(updated)["house"]["result"] == "source-missing"
    assert list(read_yaml(profiles_root)["skills"]) == ["tdd", "house"]
    assert pack.untouched()


def rows_of(data):
    return {row["skill"]: row for row in data["skills"]}


# --- a source that cannot be read ------------------------------------------------


def folder_gone(pack):
    shutil.rmtree(pack.folder)
    return "no longer exists"


def without_profile_yaml(pack):
    (pack.folder / "profile.yaml").unlink()
    pack.keep()
    return "no longer holds profile.yaml"


def tree(folder):
    return {
        str(path.relative_to(folder)): path.read_bytes() if path.is_file() else None
        for path in sorted(folder.rglob("*"))
    }


@pytest.mark.parametrize("lose", [folder_gone, without_profile_yaml])
def test_a_missing_profile_source_is_reported_and_changes_nothing(
    run, installed, pack, profiles_root, lose, assert_no_nulls
):
    pack.write("skills/tdd/SKILL.md", "# tdd v2\n")
    pack.skill("lint", True)
    said = lose(pack)
    message = f"source folder {pack.path} {said}"
    before = tree(profiles_root / "pack")

    check_text = ok(run("update", "--check")).output
    check = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))
    update_text = ok(run("update")).output
    update = assert_no_nulls(json.loads(ok(run("update", "--json")).output))

    line = f"Profile 'pack': source missing: {pack.path} {said}"
    assert line in check_text and line in update_text
    assert check["source"] == {
        "folder": pack.path,
        "source_missing": True,
        "message": message,
    }
    assert update["source"] == {
        "folder": pack.path,
        "result": "source-missing",
        "message": message,
    }
    warning = {
        "type": "source-missing",
        "profile": "pack",
        "folder": pack.path,
        "message": message,
    }
    assert check["warnings"][0] == update["warnings"][0] == warning
    assert [row["skill"] for row in check["skills"]] == ["tdd", "house"]
    assert all(row["source_missing"] for row in check["skills"])
    assert [row["result"] for row in update["skills"]] == ["source-missing"] * 2
    assert tree(profiles_root / "pack") == before
    if pack.folder.exists():
        assert pack.untouched()


def invalid_yaml(pack):
    pack.write("profile.yaml", "targets: [nowhere]\n")
    return "nowhere"


def skill_without_folder(pack):
    pack.data["skills"]["ghost"] = {"enabled": True}
    pack.save()
    return "lists skills without a skills/<skill>/SKILL.md: ghost"


@pytest.mark.parametrize("damage", [invalid_yaml, skill_without_folder])
def test_an_unreadable_profile_source_is_an_error_and_changes_nothing(
    run, installed, pack, profiles_root, damage, assert_no_nulls
):
    pack.write("skills/tdd/SKILL.md", "# tdd v2\n")
    said = damage(pack)
    pack.keep()
    before = tree(profiles_root / "pack")

    check = fails(run("update", "--check", "--json"))
    update = fails(run("update", "--json"))
    text = fails(run("update", "--yes"))

    checked = assert_no_nulls(json.loads(check.output))
    updated = assert_no_nulls(json.loads(update.output))
    assert said in checked["source"]["error"]
    assert updated["source"]["result"] == "error"
    assert said in updated["source"]["error"]
    assert checked["warnings"] == updated["warnings"] == []
    assert [row["result"] for row in updated["skills"]] == ["error", "error"]
    assert "Profile 'pack': error:" in text.output
    assert tree(profiles_root / "pack") == before
    assert pack.untouched()


# --- a profile installed from git --------------------------------------------------


@pytest.fixture
def from_git(run, upstream, profiles_root):
    repo = make_git_pack(upstream)
    ok(run("profile", "install", "acme/pack"))
    ok(run("use", "pack"))
    return repo


def test_check_right_after_a_git_install_asks_nothing(run, from_git, assert_no_nulls):
    data = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))

    assert data["source"] == {
        "repo": "acme/pack",
        "commit": from_git.first,
        "latest": from_git.first,
    }
    assert data["skills"] == [
        {
            "skill": name,
            "current": from_git.first,
            "latest": from_git.first,
            "update_available": False,
            "modified": False,
        }
        for name in ("tdd", "house")
    ]


def test_update_follows_a_git_profile_source(
    run, from_git, profiles_root, claude_dir, assert_no_nulls
):
    repo = from_git
    repo.write("skills/tdd/SKILL.md", "# tdd v2\n")
    (repo.work / "skills" / "house" / "SKILL.md").unlink()
    del repo.data["skills"]["house"]
    repo.data["skills"]["lint"] = {"enabled": False}
    repo.save()
    repo.write("skills/lint/SKILL.md", "# lint v1\n")
    second = repo.commit()

    check = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))
    text = ok(run("update", "--check")).output
    update = assert_no_nulls(json.loads(ok(run("update", "--json")).output))

    assert check["source"]["latest"] == second
    assert check["skills"] == [
        {
            "skill": "tdd",
            "current": repo.first,
            "latest": second,
            "update_available": True,
            "modified": False,
        },
        {"skill": "house", "current": repo.first, "modified": False, "gone": True},
        {"skill": "lint", "new": True, "enabled": False},
    ]
    assert "house  gone from the source" in text
    assert "lint  new in the source (disabled)" in text
    assert update["source"] == {"repo": "acme/pack", "commit": second}
    assert update["skills"] == [
        {"skill": "tdd", "current": repo.first, "latest": second, "result": "updated"},
        {"skill": "house", "current": repo.first, "gone": True, "result": "removed"},
        {"skill": "lint", "current": second, "result": "added", "enabled": False},
    ]
    data = read_yaml(profiles_root)
    assert data["source"] == {"repo": "acme/pack", "commit": second}
    assert list(data["skills"]) == ["tdd", "lint"]
    lint = data["skills"]["lint"]
    assert lint["enabled"] is False
    assert (lint["source"]["repo"], lint["source"]["path"]) == (
        "acme/pack",
        "skills/lint",
    )
    assert lint["source"]["commit"] == second
    skills = profiles_root / "pack" / "skills"
    assert sorted(p.name for p in skills.iterdir()) == ["lint", "tdd"]
    assert (claude_dir / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert not (claude_dir / "house").exists()
    again = rows(ok(run("update", "--json")))
    assert {row["result"] for row in again.values()} == {"up-to-date"}


def test_a_new_skill_from_git_naming_a_local_folder_is_not_trusted(
    run, from_git, profiles_root, tmp_path
):
    local = tmp_path / "private" / "lint"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text("# private files\n")
    from_git.data["skills"]["lint"] = {
        "enabled": True,
        "source": {"folder": str(local)},
    }
    from_git.save()
    from_git.write("skills/lint/SKILL.md", "# lint v1\n")
    from_git.commit()

    ok(run("update"))
    ok(run("update"))

    source = read_yaml(profiles_root)["skills"]["lint"]["source"]
    assert "folder" not in source and source["path"] == "skills/lint"
    copied = profiles_root / "pack" / "skills" / "lint" / "SKILL.md"
    assert copied.read_text() == "# lint v1\n"


def test_a_git_profile_source_that_cannot_be_fetched_changes_nothing(
    run, from_git, profiles_root, assert_no_nulls
):
    shutil.rmtree(from_git.bare)
    before = tree(profiles_root / "pack")

    check = assert_no_nulls(
        json.loads(fails(run("update", "--check", "--json")).output)
    )
    update = assert_no_nulls(json.loads(fails(run("update", "--json")).output))

    assert "acme/pack" in check["source"]["error"]
    assert update["source"]["result"] == "error"
    assert [row["result"] for row in update["skills"]] == ["error", "error"]
    assert tree(profiles_root / "pack") == before


# --- interruption ----------------------------------------------------------------


def test_update_adding_and_removing_killed_at_every_step_is_consistent(
    run, killed, tmp_path, monkeypatch
):
    seen = set()
    index = 0
    while True:
        index += 1
        home = tmp_path / f"kill-{index}" / "home"
        respec_home = tmp_path / f"kill-{index}" / "respec-home"
        home.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("RESPEC_USER_HOME", str(home))
        monkeypatch.setenv("RESPEC_HOME", str(respec_home))
        pack = Pack(tmp_path / f"kill-{index}" / "checkout" / "pack")
        pack.skill("house", True)
        ok(run("profile", "install", str(pack.folder)))
        ok(run("use", "pack"))
        first = read_yaml(respec_home / "profiles")
        pack.write("skills/tdd/SKILL.md", "# tdd v2\n")
        pack.skill("lint", True)
        pack.drop("house")
        pack.keep()
        if not killed("#", index, "update"):
            break
        recovered = json.loads(ok(run("recover", "--json")).stdout)
        outcome = recovered["warnings"][0]["outcome"]
        seen.add(outcome)
        skills = respec_home / "profiles" / "pack" / "skills"
        data = read_yaml(respec_home / "profiles")
        rolled_back = data == first
        names = ["house", "tdd"] if rolled_back else ["lint", "tdd"]
        assert sorted(data["skills"]) == names, index
        assert sorted(p.name for p in skills.iterdir()) == names, index
        text = (skills / "tdd" / "SKILL.md").read_text()
        assert text == ("# tdd v1\n" if rolled_back else "# tdd v2\n"), index
        assert outcome == ("rolled-back" if rolled_back else "finished"), index
        linked = home / ".claude" / "skills"
        assert sorted(p.name for p in linked.iterdir()) == names, index
        assert (linked / "tdd" / "SKILL.md").read_text() == text, index
        assert pack.untouched()
        ok(run("update"))
        assert sorted(read_yaml(respec_home / "profiles")["skills"]) == [
            "lint",
            "tdd",
        ], index
        assert sorted(p.name for p in skills.iterdir()) == ["lint", "tdd"], index
        assert sorted(p.name for p in linked.iterdir()) == ["lint", "tdd"], index
        assert pack.untouched()
    assert index > 8 and seen == {"finished", "rolled-back"}
