"""``respec profile diff`` shows how respec's copy of a profile differs from
its source, so that an agent can carry the differences into the source. It
only reads; ``respec update`` then records what was carried."""

import json
import shutil

import pytest
import yaml

from test_folder_sources import snapshot
from test_profile_sources import (  # noqa: F401  (fixtures)
    Pack,
    claude_dir,
    fails,
    make_git_pack,
    ok,
    profiles_root,
    read_yaml,
    rows,
)
from test_sources import isolated_git, upstream  # noqa: F401  (fixtures)


@pytest.fixture
def pack(tmp_path):
    """A profile folder outside respec: ``tdd``, ``docs`` and ``style``
    (enabled) and ``house`` (disabled)."""
    pack = Pack(tmp_path / "checkout" / "pack")
    pack.skill("docs", True)
    pack.skill("style", True)
    pack.keep()
    return pack


@pytest.fixture
def copy(run, pack, profiles_root):
    """Profile ``pack`` installed from the folder and active; returns the
    ``skills`` folder of respec's copy."""
    ok(run("profile", "install", str(pack.folder)))
    ok(run("use", "pack"))
    return profiles_root / "pack" / "skills"


@pytest.fixture
def unchanged(isolated_homes):
    """Call it before, then after: respec's data and the home folder (with
    the target folders) hold the same bytes, modes and times."""
    seen = []

    def check():
        seen.append(
            (snapshot(isolated_homes.respec_home), snapshot(isolated_homes.home))
        )
        assert seen[0] == seen[-1]
        return True

    return check


def diff(run, assert_no_nulls, profile="pack"):
    result = ok(run("profile", "diff", profile, "--json"))
    return assert_no_nulls(json.loads(result.output))


def add_original(profiles_root, name, text):
    """A skill made in respec's copy, with no source."""
    folder = profiles_root / "pack"
    data = read_yaml(profiles_root)
    data["skills"][name] = {"enabled": True}
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (folder / "skills" / name).mkdir()
    (folder / "skills" / name / "SKILL.md").write_text(text)


def elsewhere(tmp_path, name):
    folder = tmp_path / "elsewhere" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"# {name}\n")
    return folder


NOTHING = {
    "only_in_copy": [],
    "edited": [],
    "carried": [],
    "changed_in_source": [],
    "only_in_source": [],
    "gone_from_source": [],
    "local_state": {"enabled": [], "layers": []},
}


# --- nothing differs ---------------------------------------------------------------


def test_a_fresh_copy_matches_its_source_and_nothing_is_written(
    run, copy, pack, profiles_root, unchanged, assert_no_nulls
):
    unchanged()

    text = ok(run("profile", "diff", "pack")).output
    data = diff(run, assert_no_nulls)

    assert text == f"Profile 'pack' matches its source {pack.path}\n"
    assert data == {
        "profile": "pack",
        "path": str(profiles_root / "pack"),
        "source": {"folder": pack.path},
        "matches": True,
        **NOTHING,
        "warnings": [],
    }
    assert unchanged()
    assert pack.untouched()


# --- each kind of difference ---------------------------------------------------------


@pytest.fixture
def differing(run, copy, pack, profiles_root, tmp_path):
    """One skill of every kind of difference; returns the folder of the
    skill added from elsewhere."""
    mine = elsewhere(tmp_path, "mine")
    ok(run("add", str(mine)))
    add_original(profiles_root, "bare", "# bare\n")
    (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    (copy / "tdd" / "extra.md").write_text("more\n")
    (copy / "tdd" / "refs" / "note.txt").unlink()
    (copy / "style" / "SKILL.md").write_text("# style edited here\n")
    ok(run("disable", "house"))
    ok(run("enable", "house"))
    ok(run("disable", "docs"))
    ok(run("layer", "add", "mine", "--additive", "-d", "x"))
    pack.write("skills/house/SKILL.md", "# house v2\n")
    pack.write("skills/style/SKILL.md", "# style v2\n")
    pack.skill("lint", False)
    pack.drop("docs")
    pack.data["targets"] = ["claude-code", "agents"]
    pack.save()
    pack.keep()
    return mine


def test_diff_json_lists_each_kind_of_difference(
    run, copy, pack, differing, unchanged, assert_no_nulls
):
    unchanged()

    data = diff(run, assert_no_nulls)

    assert data["source"] == {"folder": pack.path}
    assert data["matches"] is False
    assert data["only_in_copy"] == [
        {
            "skill": "mine",
            "path": str(copy / "mine"),
            "source": {
                "folder": str(differing.resolve()),
                "digest": data["only_in_copy"][0]["source"]["digest"],
            },
        },
        {"skill": "bare", "path": str(copy / "bare")},
    ]
    assert data["edited"] == [
        {
            "skill": "tdd",
            "path": str(copy / "tdd"),
            "files": {
                # The folder the removed file left behind, now empty.
                "added": ["extra.md", "refs/"],
                "changed": ["SKILL.md"],
                "removed": ["refs/note.txt"],
            },
        },
        {
            "skill": "style",
            "path": str(copy / "style"),
            "files": {"added": [], "changed": ["SKILL.md"], "removed": []},
            "changed_in_source": True,
        },
    ]
    assert data["carried"] == []
    assert data["changed_in_source"] == [{"skill": "house"}]
    assert data["only_in_source"] == [{"skill": "lint", "enabled": False}]
    assert data["gone_from_source"] == [
        {"skill": "docs", "path": str(copy / "docs"), "modified": False}
    ]
    assert data["local_state"] == {
        "enabled": [{"skill": "house", "copy": True, "source": False}],
        "targets": {"copy": ["claude-code"], "source": ["claude-code", "agents"]},
        "layers": [{"layer": "mine", "copy": {"exclusive": False, "description": "x"}}],
    }
    assert data["warnings"] == []
    assert unchanged()
    assert pack.untouched()


def test_diff_text_can_be_read_at_a_glance(run, copy, pack, differing, unchanged):
    unchanged()

    text = ok(run("profile", "diff", "pack")).output

    assert text.splitlines() == [
        f"Profile 'pack' differs from its source {pack.path}",
        "Only in the copy (copy the folder into the source, or record its "
        "source there):",
        f"  mine  {copy / 'mine'}  (source: {differing.resolve()})",
        f"  bare  {copy / 'bare'}",
        "Edited in the copy (copy the listed files into the source):",
        f"  tdd  {copy / 'tdd'}",
        "    added    extra.md",
        "    added    refs/",
        "    changed  SKILL.md",
        "    removed  refs/note.txt",
        f"  style  {copy / 'style'}  (also changed in the source)",
        "    changed  SKILL.md",
        "Changed in the source ('respec update' brings it in):",
        "  house",
        "Only in the source ('respec update' adds it):",
        "  lint  (disabled)",
        "Gone from the source ('respec update' removes it):",
        f"  docs  {copy / 'docs'}",
        "Local state (respec keeps it; an update never changes it):",
        "  house  enabled here, disabled in the source",
        "  targets  claude-code here; claude-code, agents in the source",
        "  layer mine  only here",
    ]
    assert unchanged()
    assert pack.untouched()


def test_a_gone_skill_with_local_edits_says_so(run, copy, pack, assert_no_nulls):
    (copy / "docs" / "SKILL.md").write_text("# docs edited here\n")
    pack.drop("docs")
    pack.keep()

    text = ok(run("profile", "diff", "pack")).output
    data = diff(run, assert_no_nulls)

    assert f"  docs  {copy / 'docs'}  (local edits)" in text
    assert data["gone_from_source"] == [
        {"skill": "docs", "path": str(copy / "docs"), "modified": True}
    ]
    assert pack.untouched()


def test_a_skill_of_the_same_name_that_did_not_come_from_the_source_is_listed(
    run, copy, pack, tmp_path, assert_no_nulls
):
    """Its files are listed against the source's, and an update leaves it."""
    mine = elsewhere(tmp_path, "lint")
    ok(run("add", str(mine)))
    pack.skill("lint", True)
    pack.keep()

    data = diff(run, assert_no_nulls)
    updated = rows(ok(run("update", "--json")))

    assert data["edited"] == [
        {
            "skill": "lint",
            "path": str(copy / "lint"),
            "files": {"added": [], "changed": ["SKILL.md"], "removed": []},
            "not_from_source": True,
        }
    ]
    assert data["matches"] is False
    assert updated["lint"]["result"] == "up-to-date"
    assert (copy / "lint" / "SKILL.md").read_text() == "# lint\n"
    assert diff(run, assert_no_nulls)["edited"] == data["edited"]
    assert pack.untouched()


def test_a_skill_following_the_git_source_the_source_names_is_not_a_difference(
    run, pack, profiles_root, upstream, assert_no_nulls
):
    repo = upstream("acme/skills")
    repo.write("lint/SKILL.md", "# lint v1\n")
    first = repo.commit()
    pack.skill("lint", True, source={"repo": "acme/skills", "path": "lint"})
    pack.keep()
    ok(run("profile", "install", str(pack.folder)))
    repo.write("lint/SKILL.md", "# lint v2\n")
    repo.commit()
    ok(run("update", "lint", "-p", "pack", "--yes"))
    copied = profiles_root / "pack" / "skills" / "lint" / "SKILL.md"
    assert copied.read_text() == "# lint v2\n" and first

    data = diff(run, assert_no_nulls)

    assert data["matches"] is True
    assert pack.untouched()


# --- a profile without a source, and a source that cannot be read -------------------


def test_a_profile_without_a_source_says_so(run, profiles_root, assert_no_nulls):
    ok(run("profile", "new", "work", "--target", "claude-code"))

    text = ok(run("profile", "diff", "work")).output
    data = diff(run, assert_no_nulls, "work")

    assert text == "Profile 'work' has no source: there is nothing to compare.\n"
    assert data == {
        "profile": "work",
        "path": str(profiles_root / "work"),
        "warnings": [],
    }


def test_an_unknown_profile_is_refused(run):
    result = fails(run("profile", "diff", "nope"))

    assert "nope" in result.output


def folder_gone(pack):
    shutil.rmtree(pack.folder)
    return "no longer exists"


def without_profile_yaml(pack):
    (pack.folder / "profile.yaml").unlink()
    pack.keep()
    return "no longer holds profile.yaml"


@pytest.mark.parametrize("lose", [folder_gone, without_profile_yaml])
def test_a_missing_source_is_reported_and_is_not_a_failure(
    run, copy, pack, profiles_root, lose, unchanged, assert_no_nulls
):
    said = lose(pack)
    message = f"source folder {pack.path} {said}"
    unchanged()

    text = ok(run("profile", "diff", "pack")).output
    data = diff(run, assert_no_nulls)

    assert text == (
        f"Profile 'pack': source missing: {pack.path} {said}; "
        "nothing was compared.\n"
    )
    assert data == {
        "profile": "pack",
        "path": str(profiles_root / "pack"),
        "source": {"folder": pack.path, "source_missing": True, "message": message},
        "warnings": [
            {
                "type": "source-missing",
                "profile": "pack",
                "folder": pack.path,
                "message": message,
            }
        ],
    }
    assert unchanged()
    if pack.folder.exists():
        assert pack.untouched()


def test_an_unreadable_source_is_an_error(run, copy, pack, unchanged, assert_no_nulls):
    pack.write("profile.yaml", "targets: [nowhere]\n")
    pack.keep()
    unchanged()

    text = fails(run("profile", "diff", "pack"))
    result = fails(run("profile", "diff", "pack", "--json"))

    data = assert_no_nulls(json.loads(result.output))
    assert "Profile 'pack': error:" in text.output and "nowhere" in text.output
    assert "nowhere" in data["source"]["error"]
    assert "matches" not in data and "edited" not in data
    assert data["warnings"] == []
    assert unchanged()
    assert pack.untouched()


# --- it only reads ---------------------------------------------------------------------


def test_diff_runs_while_another_respec_changes_things(
    run, copy, pack, holder, assert_no_nulls
):
    busy = holder("use:begin", "use", "pack")

    data = diff(run, assert_no_nulls)
    refused = fails(run("disable", "tdd"))

    assert data["matches"] is True
    assert "another respec" in refused.output.lower()
    code, out, err = busy.finish()
    assert code == 0, out + err


# --- the round trip: carry into the source, update, nothing differs ------------------


def carry(copy, pack, name):
    """What an agent does: put the copy's files of a skill into the source."""
    target = pack.folder / "skills" / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(copy / name, target)


def test_carried_skills_are_adopted_by_update_without_asking(
    run, copy, pack, profiles_root, claude_dir, tmp_path, unchanged, assert_no_nulls
):
    ok(run("add", str(elsewhere(tmp_path, "mine"))))
    add_original(profiles_root, "bare", "# bare\n")
    (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    (copy / "tdd" / "extra.md").write_text("more\n")
    ok(run("disable", "mine"))
    before = diff(run, assert_no_nulls)
    for name in ("mine", "bare", "tdd"):
        carry(copy, pack, name)
    pack.data["skills"]["mine"] = {"enabled": True}
    pack.data["skills"]["bare"] = {"enabled": True}
    pack.save()
    pack.keep()
    unchanged()

    waiting = diff(run, assert_no_nulls)
    assert unchanged()
    text = ok(run("profile", "diff", "pack")).output
    updated = json.loads(ok(run("update", "--json")).output)
    said = ok(run("update")).output
    after = diff(run, assert_no_nulls)

    assert [row["skill"] for row in before["only_in_copy"]] == ["mine", "bare"]
    assert [row["skill"] for row in before["edited"]] == ["tdd"]
    assert waiting["carried"] == [
        {"skill": "tdd"},
        {"skill": "mine"},
        {"skill": "bare"},
    ]
    assert waiting["only_in_copy"] == waiting["edited"] == []
    assert waiting["matches"] is False
    assert "Same in the source ('respec update' records it):" in text
    assert rows_of(updated) == {
        "tdd": {"skill": "tdd", "folder": pack.source_of("tdd"), "result": "adopted"},
        "house": {
            "skill": "house",
            "folder": pack.source_of("house"),
            "result": "up-to-date",
        },
        "docs": {
            "skill": "docs",
            "folder": pack.source_of("docs"),
            "result": "up-to-date",
        },
        "style": {
            "skill": "style",
            "folder": pack.source_of("style"),
            "result": "up-to-date",
        },
        "mine": {
            "skill": "mine",
            "folder": pack.source_of("mine"),
            "result": "adopted",
        },
        "bare": {
            "skill": "bare",
            "folder": pack.source_of("bare"),
            "result": "adopted",
        },
    }
    assert updated["warnings"] == []
    assert "adopted" not in said and "tdd  up to date" in said
    skills = read_yaml(profiles_root)["skills"]
    for name in ("mine", "bare", "tdd"):
        assert sorted(skills[name]["source"]) == ["digest", "folder"]
        assert skills[name]["source"]["folder"] == pack.source_of(name)
    assert skills["mine"]["enabled"] is False and skills["bare"]["enabled"] is True
    assert (copy / "tdd" / "SKILL.md").read_text() == "# tdd edited here\n"
    assert (copy / "tdd" / "extra.md").read_text() == "more\n"
    assert (claude_dir / "tdd" / "extra.md").read_text() == "more\n"
    assert after == {
        "profile": "pack",
        "path": str(profiles_root / "pack"),
        "source": {"folder": pack.path},
        "matches": True,
        **NOTHING,
        "local_state": {
            "enabled": [{"skill": "mine", "copy": False, "source": True}],
            "layers": [],
        },
        "warnings": [],
    }
    assert pack.untouched()


def rows_of(data):
    return {row["skill"]: row for row in data["skills"]}


def test_update_says_what_it_adopted(run, copy, pack):
    (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    carry(copy, pack, "tdd")

    text = ok(run("update")).output

    assert "tdd  adopted: the copy already holds what the source holds" in text
    assert "Overwrite?" not in text


def test_a_carried_copy_that_was_changed_again_is_not_adopted(
    run, copy, pack, profiles_root, assert_no_nulls
):
    add_original(profiles_root, "bare", "# bare\n")
    (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    for name in ("bare", "tdd"):
        carry(copy, pack, name)
    pack.data["skills"]["bare"] = {"enabled": True}
    pack.save()
    pack.keep()
    (copy / "bare" / "SKILL.md").write_text("# bare, changed again\n")
    (copy / "tdd" / "SKILL.md").write_text("# tdd, changed again\n")

    updated = rows(ok(run("update", "--json")))
    data = diff(run, assert_no_nulls)

    assert updated["tdd"]["result"] == "skipped-local-edits"
    assert "bare" not in updated
    assert "source" not in read_yaml(profiles_root)["skills"]["bare"]
    assert (copy / "bare" / "SKILL.md").read_text() == "# bare, changed again\n"
    assert (copy / "tdd" / "SKILL.md").read_text() == "# tdd, changed again\n"
    assert [row["skill"] for row in data["edited"]] == ["tdd", "bare"]
    assert data["edited"][0]["changed_in_source"] is True
    assert data["edited"][1]["not_from_source"] is True
    assert pack.untouched()


def test_updating_one_named_skill_adopts_nothing(run, copy, pack, profiles_root):
    add_original(profiles_root, "bare", "# bare\n")
    carry(copy, pack, "bare")
    pack.data["skills"]["bare"] = {"enabled": True}
    pack.save()
    pack.keep()

    ok(run("update", "tdd"))

    assert "source" not in read_yaml(profiles_root)["skills"]["bare"]
    assert pack.untouched()


# --- a profile installed from git ----------------------------------------------------


@pytest.fixture
def from_git(run, upstream, profiles_root):
    repo = make_git_pack(upstream)
    ok(run("profile", "install", "acme/pack"))
    ok(run("use", "pack"))
    return repo


def test_diff_against_a_git_source(
    run, from_git, profiles_root, tmp_path, unchanged, assert_no_nulls
):
    repo = from_git
    copy = profiles_root / "pack" / "skills"
    same = diff(run, assert_no_nulls)
    ok(run("add", str(elsewhere(tmp_path, "mine"))))
    (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    repo.write("skills/house/SKILL.md", "# house v2\n")
    repo.data["skills"]["lint"] = {"enabled": True}
    repo.save()
    repo.write("skills/lint/SKILL.md", "# lint v1\n")
    second = repo.commit()
    unchanged()

    text = ok(run("profile", "diff", "pack")).output
    data = diff(run, assert_no_nulls)

    assert same["matches"] is True
    assert same["source"] == {
        "repo": "acme/pack",
        "commit": repo.first,
        "latest": repo.first,
    }
    assert text.splitlines()[0] == "Profile 'pack' differs from its source acme/pack"
    assert data["source"] == {
        "repo": "acme/pack",
        "commit": repo.first,
        "latest": second,
    }
    assert [row["skill"] for row in data["only_in_copy"]] == ["mine"]
    assert data["edited"] == [
        {
            "skill": "tdd",
            "path": str(copy / "tdd"),
            "files": {"added": [], "changed": ["SKILL.md"], "removed": []},
        }
    ]
    assert data["changed_in_source"] == [{"skill": "house"}]
    assert data["only_in_source"] == [{"skill": "lint", "enabled": True}]
    assert data["gone_from_source"] == []
    assert unchanged()


def test_the_round_trip_through_a_git_source(
    run, from_git, profiles_root, tmp_path, assert_no_nulls
):
    repo = from_git
    copy = profiles_root / "pack" / "skills"
    ok(run("add", str(elsewhere(tmp_path, "mine"))))
    (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
    (copy / "tdd" / "extra.md").write_text("more\n")
    before = diff(run, assert_no_nulls)
    repo.write("skills/mine/SKILL.md", (copy / "mine" / "SKILL.md").read_text())
    repo.write("skills/tdd/SKILL.md", "# tdd edited here\n")
    repo.write("skills/tdd/extra.md", "more\n")
    repo.data["skills"]["mine"] = {"enabled": True}
    repo.save()
    second = repo.commit()

    updated = rows(ok(run("update", "--json")))
    after = diff(run, assert_no_nulls)

    assert before["matches"] is False
    assert updated["tdd"]["result"] == updated["mine"]["result"] == "adopted"
    assert updated["house"]["result"] == "updated"  # to the new commit
    data = read_yaml(profiles_root)
    assert data["source"] == {"repo": "acme/pack", "commit": second}
    for name in ("mine", "tdd"):
        source = data["skills"][name]["source"]
        assert sorted(source) == ["commit", "digest", "path", "repo"]
        assert (source["repo"], source["path"]) == ("acme/pack", f"skills/{name}")
        assert source["commit"] == second
    assert (copy / "tdd" / "extra.md").read_text() == "more\n"
    assert after["matches"] is True
    assert {key: after[key] for key in NOTHING} == NOTHING
    again = rows(ok(run("update", "--json")))
    assert {row["result"] for row in again.values()} == {"up-to-date"}


# --- interruption ----------------------------------------------------------------------


def test_an_adopting_update_killed_at_every_step_is_consistent(
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
        ok(run("profile", "install", str(pack.folder)))
        ok(run("use", "pack"))
        copy = respec_home / "profiles" / "pack" / "skills"
        add_original(respec_home / "profiles", "bare", "# bare\n")
        (copy / "tdd" / "SKILL.md").write_text("# tdd edited here\n")
        for name in ("bare", "tdd"):
            carry(copy, pack, name)
        pack.data["skills"]["bare"] = {"enabled": True}
        pack.save()
        pack.keep()
        first = read_yaml(respec_home / "profiles")
        if not killed("#", index, "update"):
            break
        recovered = json.loads(ok(run("recover", "--json")).stdout)
        outcome = recovered["warnings"][0]["outcome"]
        seen.add(outcome)
        data = read_yaml(respec_home / "profiles")
        rolled_back = data == first
        assert outcome == ("rolled-back" if rolled_back else "finished"), index
        assert rolled_back or "source" in data["skills"]["bare"], index
        assert (copy / "tdd" / "SKILL.md").read_text() == "# tdd edited here\n"
        assert (copy / "bare" / "SKILL.md").read_text() == "# bare\n"
        assert pack.untouched()
        ok(run("update"))
        data = read_yaml(respec_home / "profiles")
        assert data["skills"]["bare"]["source"]["folder"] == pack.source_of("bare")
        assert sorted(p.name for p in copy.iterdir()) == ["bare", "house", "tdd"]
        assert pack.untouched()
    assert index > 3 and seen == {"finished", "rolled-back"}
