"""Local folders as skill sources: ``add`` records the folder, ``update``
checks and refreshes from it, and respec never writes to the folder."""

import json
import os
import shutil

import pytest
import yaml


@pytest.fixture
def profiles_root(isolated_homes):
    return isolated_homes.respec_home / "profiles"


def read_yaml(profiles_root, profile="work"):
    return yaml.safe_load((profiles_root / profile / "profile.yaml").read_text())


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def snapshot(folder):
    """Every entry under ``folder`` (and the folder itself): kind, bytes or
    link target, mode and modification time."""
    found = {".": ("d", None, folder.stat().st_mode, folder.stat().st_mtime_ns)}
    for root, dirs, files in os.walk(folder):
        for name in dirs + files:
            entry = os.path.join(root, name)
            relative = os.path.relpath(entry, folder)
            info = os.lstat(entry)
            if os.path.islink(entry):
                found[relative] = ("l", os.readlink(entry), info.st_mode, None)
            elif os.path.isdir(entry):
                found[relative] = ("d", None, info.st_mode, info.st_mtime_ns)
            else:
                with open(entry, "rb") as handle:
                    content = handle.read()
                found[relative] = ("f", content, info.st_mode, info.st_mtime_ns)
    return found


class Reference:
    """A skill folder outside respec that must never change."""

    def __init__(self, folder):
        self.folder = folder
        (folder / "refs").mkdir(parents=True)
        self.write("SKILL.md", f"# {folder.name} v1\n")
        self.write("refs/note.txt", "note\n")
        script = folder / "run.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        (folder / "alias.md").symlink_to("SKILL.md")
        self.keep()

    def write(self, relative, text):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def keep(self):
        """Remember the folder as the test left it."""
        self.kept = snapshot(self.folder)

    def untouched(self):
        assert snapshot(self.folder) == self.kept
        return True


@pytest.fixture
def reference(tmp_path):
    return Reference(tmp_path / "checkout" / "tdd")


@pytest.fixture
def work(run, reference, profiles_root):
    """Profile ``work`` (active) with ``tdd`` added from the reference."""
    ok(run("profile", "new", "work", "--target", "claude-code"))
    ok(run("use", "work"))
    ok(run("add", str(reference.folder)))
    return profiles_root / "work" / "skills"


def test_add_records_the_folder_and_a_digest(run, reference, profiles_root, tmp_path):
    ok(run("profile", "new", "work", "--target", "claude-code"))

    ok(run("add", str(reference.folder), "-p", "work"))

    source = read_yaml(profiles_root)["skills"]["tdd"]["source"]
    assert sorted(source) == ["digest", "folder"]
    assert source["folder"] == str(reference.folder.resolve())
    assert source["digest"].startswith("sha256:")
    assert reference.untouched()


def test_add_stores_a_relative_folder_as_an_absolute_path(
    run, reference, profiles_root, monkeypatch
):
    ok(run("profile", "new", "work", "--target", "claude-code"))
    monkeypatch.chdir(reference.folder.parent)

    ok(run("add", "tdd", "-p", "work"))

    source = read_yaml(profiles_root)["skills"]["tdd"]["source"]
    assert source["folder"] == str(reference.folder.resolve())


def test_add_json_shows_the_source(run, reference, profiles_root, assert_no_nulls):
    ok(run("profile", "new", "work", "--target", "claude-code"))

    added = assert_no_nulls(
        json.loads(ok(run("add", str(reference.folder), "-p", "work", "--json")).output)
    )

    assert added["source"] == read_yaml(profiles_root)["skills"]["tdd"]["source"]
    assert added["source"]["folder"] == str(reference.folder.resolve())
    assert reference.untouched()


def test_add_says_where_the_skill_came_from(run, reference):
    ok(run("profile", "new", "work", "--target", "claude-code"))

    result = ok(run("add", str(reference.folder), "-p", "work"))

    assert f"from {reference.folder.resolve()}" in result.output


def test_add_refuses_a_symlink_that_leaves_the_folder(
    run, reference, profiles_root, tmp_path
):
    ok(run("profile", "new", "work", "--target", "claude-code"))
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n")
    (reference.folder / "leak.txt").symlink_to(secret)
    reference.keep()

    result = run("add", str(reference.folder), "-p", "work")

    assert result.exit_code == 1
    assert "leak.txt" in result.output
    assert read_yaml(profiles_root).get("skills") in (None, {})
    assert not (profiles_root / "work" / "skills" / "tdd").exists()
    assert reference.untouched()


def test_check_says_current_when_the_folder_is_as_copied(
    run, work, reference, assert_no_nulls
):
    text = ok(run("update", "--check")).output
    data = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))

    assert "tdd  up to date" in text
    assert data["skills"] == [
        {
            "skill": "tdd",
            "folder": str(reference.folder.resolve()),
            "update_available": False,
            "modified": False,
        }
    ]
    assert data["warnings"] == []
    assert reference.untouched()


def test_check_says_update_available_when_the_folder_changed(
    run, work, reference, profiles_root
):
    reference.write("SKILL.md", "# tdd v2\n")
    reference.keep()
    before = read_yaml(profiles_root)

    text = ok(run("update", "--check", "tdd")).output
    data = json.loads(ok(run("update", "--check", "--json")).output)

    assert "tdd  update available" in text
    assert data["skills"][0]["update_available"] is True
    assert data["skills"][0]["modified"] is False
    assert (work / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert read_yaml(profiles_root) == before
    assert reference.untouched()


def test_update_copies_the_folder_again_and_records_the_new_digest(
    run, work, reference, profiles_root, isolated_homes, assert_no_nulls
):
    reference.write("SKILL.md", "# tdd v2\n")
    reference.write("refs/new.txt", "new\n")
    (reference.folder / "refs" / "note.txt").unlink()
    reference.keep()
    old = read_yaml(profiles_root)["skills"]["tdd"]["source"]

    data = assert_no_nulls(json.loads(ok(run("update", "--json")).output))

    assert data["skills"] == [
        {
            "skill": "tdd",
            "folder": str(reference.folder.resolve()),
            "result": "updated",
        }
    ]
    assert (work / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert (work / "tdd" / "refs" / "new.txt").read_text() == "new\n"
    assert not (work / "tdd" / "refs" / "note.txt").exists()
    assert os.access(work / "tdd" / "run.sh", os.X_OK)
    assert sorted(p.name for p in work.iterdir()) == ["tdd"]
    new = read_yaml(profiles_root)["skills"]["tdd"]["source"]
    assert new["folder"] == old["folder"] and new["digest"] != old["digest"]
    linked = isolated_homes.home / ".claude" / "skills" / "tdd" / "SKILL.md"
    assert linked.read_text() == "# tdd v2\n"
    assert reference.untouched()
    # The new digest is the folder's: nothing more to do.
    assert "tdd  up to date" in ok(run("update")).output
    assert "tdd  up to date" in ok(run("update", "--check")).output
    assert reference.untouched()


def test_update_says_updated_in_text(run, work, reference):
    reference.write("SKILL.md", "# tdd v2\n")

    assert "tdd  updated" in ok(run("update", "tdd")).output


def test_update_of_an_unchanged_folder_changes_nothing(
    run, work, reference, profiles_root
):
    before = read_yaml(profiles_root)

    data = json.loads(ok(run("update", "--json")).output)

    assert data["skills"][0]["result"] == "up-to-date"
    assert read_yaml(profiles_root) == before
    assert reference.untouched()


def test_update_keeps_local_edits_unless_confirmed(run, work, reference, profiles_root):
    reference.write("SKILL.md", "# tdd v2\n")
    reference.keep()
    (work / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    before = read_yaml(profiles_root)

    check = json.loads(ok(run("update", "--check", "--json")).output)
    skipped = json.loads(ok(run("update", "--json")).output)
    declined = ok(run("update", input="n\n"))

    assert check["skills"][0]["modified"] is True
    assert skipped["skills"][0]["result"] == "skipped-local-edits"
    assert "local edits" in declined.output
    assert (work / "tdd" / "SKILL.md").read_text() == "# tdd edited here\n"
    assert read_yaml(profiles_root) == before
    assert reference.untouched()


@pytest.mark.parametrize("answer", [("--yes",), ()])
def test_update_overwrites_local_edits_when_told_to(run, work, reference, answer):
    reference.write("SKILL.md", "# tdd v2\n")
    reference.keep()
    (work / "tdd" / "SKILL.md").write_text("# tdd edited here\n")

    ok(run("update", *answer, input=None if answer else "y\n"))

    assert (work / "tdd" / "SKILL.md").read_text() == "# tdd v2\n"
    assert reference.untouched()


def gone(reference):
    shutil.rmtree(reference.folder)
    return "no longer exists"


def without_skill_md(reference):
    (reference.folder / "SKILL.md").unlink()
    (reference.folder / "alias.md").unlink()
    reference.keep()
    return "no longer holds SKILL.md"


@pytest.mark.parametrize("lose", [gone, without_skill_md])
def test_a_missing_source_is_reported_and_other_skills_still_update(
    run, work, reference, profiles_root, tmp_path, lose, assert_no_nulls
):
    other = Reference(tmp_path / "checkout" / "lint")
    ok(run("add", str(other.folder)))
    other.write("SKILL.md", "# lint v2\n")
    other.keep()
    said = lose(reference)
    folder = str(reference.folder.resolve())
    tdd_before = read_yaml(profiles_root)["skills"]["tdd"]

    check_text = ok(run("update", "--check")).output
    check = assert_no_nulls(json.loads(ok(run("update", "--check", "--json")).output))
    update = assert_no_nulls(json.loads(ok(run("update", "--json")).output))

    assert f"tdd  source missing: {folder} {said}" in check_text
    assert "lint  update available" in check_text
    assert check["skills"] == [
        {
            "skill": "tdd",
            "folder": folder,
            "modified": False,
            "source_missing": True,
            "message": f"source folder {folder} {said}",
        },
        {
            "skill": "lint",
            "folder": str(other.folder.resolve()),
            "update_available": True,
            "modified": False,
        },
    ]
    warning = {
        "type": "source-missing",
        "profile": "work",
        "skill": "tdd",
        "folder": folder,
        "message": f"source folder {folder} {said}",
    }
    assert check["warnings"] == [warning]
    assert update["warnings"] == [warning]
    assert update["skills"] == [
        {
            "skill": "tdd",
            "folder": folder,
            "result": "source-missing",
            "message": f"source folder {folder} {said}",
        },
        {"skill": "lint", "folder": str(other.folder.resolve()), "result": "updated"},
    ]
    assert (work / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert (work / "lint" / "SKILL.md").read_text() == "# lint v2\n"
    assert read_yaml(profiles_root)["skills"]["tdd"] == tdd_before
    assert f"tdd  source missing: {folder} {said}" in ok(run("update")).output
    assert reference.folder.exists() == (lose is without_skill_md)
    if reference.folder.exists():
        assert reference.untouched()
    assert other.untouched()


def test_update_refuses_a_symlink_that_now_leaves_the_folder(
    run, work, reference, profiles_root, tmp_path
):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n")
    (reference.folder / "leak.txt").symlink_to(secret)
    reference.keep()
    before = read_yaml(profiles_root)

    check = run("update", "--check", "--json")
    result = run("update", "--json")

    assert check.exit_code == 1 and result.exit_code == 1
    assert "leak.txt" in json.loads(check.output)["skills"][0]["error"]
    row = json.loads(result.output)["skills"][0]
    assert row["result"] == "error" and "leak.txt" in row["error"]
    assert not (work / "tdd" / "leak.txt").exists()
    assert read_yaml(profiles_root) == before
    assert reference.untouched()


def test_update_from_a_folder_killed_at_every_step_is_consistent(
    run, killed, tmp_path, monkeypatch
):
    reference = Reference(tmp_path / "checkout" / "tdd")
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
        reference.write("SKILL.md", "# tdd v1\n")
        ok(run("profile", "new", "work", "--target", "claude-code"))
        ok(run("use", "work"))
        ok(run("add", str(reference.folder)))
        first = read_yaml(respec_home / "profiles")["skills"]["tdd"]["source"]
        reference.write("SKILL.md", "# tdd v2\n")
        reference.keep()
        if not killed("#", index, "update"):
            break
        recovered = json.loads(ok(run("recover", "--json")).stdout)
        outcome = recovered["warnings"][0]["outcome"]
        seen.add(outcome)
        skills = respec_home / "profiles" / "work" / "skills"
        assert sorted(p.name for p in skills.iterdir()) == ["tdd"], index
        source = read_yaml(respec_home / "profiles")["skills"]["tdd"]["source"]
        text = (skills / "tdd" / "SKILL.md").read_text()
        rolled_back = source == first
        assert text == ("# tdd v1\n" if rolled_back else "# tdd v2\n"), index
        assert outcome == ("rolled-back" if rolled_back else "finished"), index
        linked = home / ".claude" / "skills" / "tdd" / "SKILL.md"
        assert linked.read_text() == text, index
        assert reference.untouched()
        ok(run("update"))
        assert (skills / "tdd" / "SKILL.md").read_text() == "# tdd v2\n", index
        assert reference.untouched()
    assert index > 5 and seen == {"finished", "rolled-back"}


def test_a_skill_without_a_source_still_never_changes(run, work, profiles_root):
    data = read_yaml(profiles_root)
    del data["skills"]["tdd"]["source"]
    (profiles_root / "work" / "profile.yaml").write_text(yaml.safe_dump(data))

    refused = run("update", "tdd")
    everything = ok(run("update"))
    shown = json.loads(ok(run("profile", "show", "work", "--json")).output)

    assert refused.exit_code == 1 and "has no source" in refused.output
    assert "has no skills with a source" in everything.output
    assert shown["skills"] == [
        {"name": "tdd", "enabled": True, "provenance": "original"}
    ]


@pytest.mark.parametrize(
    "source, problem",
    [
        ({"folder": "relative/tdd"}, "must be an absolute path"),
        ({"folder": "/x/tdd", "repo": "acme/skills"}, "cannot be combined"),
        ({"folder": "/x/tdd", "commit": "0123abcd"}, "cannot be combined"),
        ({"digest": "sha256:0"}, "repo is required"),
    ],
)
def test_a_malformed_folder_source_is_refused(
    run, work, profiles_root, source, problem
):
    data = read_yaml(profiles_root)
    data["skills"]["tdd"]["source"] = source
    (profiles_root / "work" / "profile.yaml").write_text(yaml.safe_dump(data))

    result = run("profile", "show", "work")

    assert result.exit_code == 1
    assert problem in " ".join(result.output.split())
