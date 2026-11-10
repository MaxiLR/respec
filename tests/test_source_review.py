"""Edges of sources found in review: a skill added by hand from inside the
profile's source, updates decided by files, ``.git`` and ``.DS_Store``,
``SOURCE.md`` after an interruption, sources inside respec's own data and
symlinked skill folders in a folder source."""

import hashlib
import json
import os
import shutil

import pytest
import yaml

from test_folder_sources import snapshot
from test_profile_sources import Pack, fails, ok, rows  # noqa: F401
from test_profile_sources import claude_dir, from_git, installed  # noqa: F401
from test_profile_sources import pack, profiles_root, read_yaml  # noqa: F401
from test_sources import isolated_git, upstream  # noqa: F401  (fixtures)


def text_of(profiles_root, profile="pack"):
    return (profiles_root / profile / "profile.yaml").read_text()


def skill_folder(folder, text=None):
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text or f"# {folder.name}\n")
    return folder


# --- a skill added by hand from inside the profile's source ---------------------


def test_add_refuses_a_skill_folder_inside_the_profiles_own_source(
    run, installed, pack, profiles_root, claude_dir
):
    pack.write("skills/wip/SKILL.md", "# wip\n")  # not listed in profile.yaml
    pack.keep()
    before = text_of(profiles_root)

    result = fails(run("add", str(pack.folder / "skills" / "wip"), "-p", "pack"))

    assert "profile.yaml" in result.output
    assert "respec update" in result.output
    assert text_of(profiles_root) == before
    assert sorted(p.name for p in installed.iterdir()) == ["house", "tdd"]
    assert sorted(p.name for p in claude_dir.iterdir()) == ["tdd"]
    assert pack.untouched()


def test_add_refuses_it_through_a_symlink_too(
    run, installed, pack, profiles_root, tmp_path
):
    pack.write("skills/wip/SKILL.md", "# wip\n")
    pack.keep()
    link = tmp_path / "wip"
    link.symlink_to(pack.folder / "skills" / "wip")
    before = text_of(profiles_root)

    fails(run("add", str(link), "-p", "pack", "--json"))

    assert text_of(profiles_root) == before
    assert not (installed / "wip").exists()
    assert pack.untouched()


def test_listing_the_skill_in_the_source_and_updating_adds_it(
    run, installed, pack, profiles_root
):
    pack.skill("wip", True)
    pack.keep()

    assert rows(ok(run("update", "--json")))["wip"]["result"] == "added"
    assert rows(ok(run("update", "--json")))["wip"]["result"] == "up-to-date"
    assert (installed / "wip" / "SKILL.md").is_file()
    assert pack.untouched()


def test_add_refuses_a_skill_inside_the_profiles_own_git_source(
    run, from_git, profiles_root, claude_dir
):
    from_git.write("skills/wip/SKILL.md", "# wip\n")  # not listed
    from_git.commit()
    before = text_of(profiles_root)

    for spec in ("acme/pack#skills/wip", "acme/pack"):
        result = fails(run("add", spec, "-p", "pack"))

        assert "profile.yaml" in result.output
        assert "respec update" in result.output
        assert text_of(profiles_root) == before
        skills = profiles_root / "pack" / "skills"
        assert sorted(p.name for p in skills.iterdir()) == ["house", "tdd"]
        assert sorted(p.name for p in claude_dir.iterdir()) == ["tdd"]


def test_the_same_git_skill_is_added_to_a_profile_with_another_source(
    run, from_git, profiles_root
):
    from_git.write("skills/wip/SKILL.md", "# wip\n")
    from_git.commit()
    ok(run("profile", "new", "other", "--target", "claude-code"))

    ok(run("add", "acme/pack#skills/wip", "-p", "other"))

    assert "wip" in read_yaml(profiles_root, "other")["skills"]


# --- updates of skills from the profile's source are decided by files -----------


def available(run):
    data = json.loads(ok(run("update", "--check", "--json")).output)
    return {row["skill"] for row in data["skills"] if row.get("update_available")}, data


def changed_in_source(run):
    data = json.loads(ok(run("profile", "diff", "pack", "--json")).output)
    return {row["skill"] for row in data["changed_in_source"]} | {
        row["skill"] for row in data["edited"] if row.get("changed_in_source")
    }


def test_a_commit_that_leaves_a_skill_alone_is_no_update_of_it(
    run, from_git, profiles_root, assert_no_nulls
):
    repo = from_git
    tdd = profiles_root / "pack" / "skills" / "tdd"
    (tdd / "mine.md").write_text("my notes\n")
    repo.write("skills/house/SKILL.md", "# house v2\n")
    second = repo.commit()

    updates, check = available(run)
    assert_no_nulls(check)
    assert updates == {"house"} == changed_in_source(run)
    assert rows(ok(run("update", "--check", "tdd", "--json")))["tdd"][
        "update_available"
    ] is (False)

    # No --yes, no --json and no terminal: a question would abort the update.
    text = ok(run("update")).output

    assert "tdd  up to date" in text
    assert (tdd / "mine.md").read_text() == "my notes\n"
    house = profiles_root / "pack" / "skills" / "house"
    assert (house / "SKILL.md").read_text() == "# house v2\n"
    data = read_yaml(profiles_root)
    assert data["source"]["commit"] == second
    assert data["skills"]["house"]["source"]["commit"] == second
    updates, check = available(run)
    assert updates == set() == changed_in_source(run)
    by_name = {row["skill"]: row for row in check["skills"]}
    assert by_name["tdd"]["modified"] is True
    assert rows(ok(run("update", "--json")))["tdd"]["result"] == "up-to-date"
    assert rows(ok(run("update", "tdd", "--json")))["tdd"]["result"] == "up-to-date"
    assert (tdd / "mine.md").read_text() == "my notes\n"


def test_an_edited_skill_that_also_changed_in_the_source_is_still_asked_about(
    run, from_git, profiles_root
):
    repo = from_git
    tdd = profiles_root / "pack" / "skills" / "tdd"
    (tdd / "mine.md").write_text("my notes\n")
    repo.write("skills/tdd/SKILL.md", "# tdd v2\n")
    repo.commit()

    updates, _ = available(run)
    assert updates == {"tdd"} == changed_in_source(run)
    assert rows(ok(run("update", "--json")))["tdd"]["result"] == "skipped-local-edits"
    assert (tdd / "SKILL.md").read_text() == "# tdd v1\n"
    updates, _ = available(run)
    assert updates == {"tdd"} == changed_in_source(run)

    assert rows(ok(run("update", "--yes", "--json")))["tdd"]["result"] == "updated"
    assert (tdd / "SKILL.md").read_text() == "# tdd v2\n"
    assert not (tdd / "mine.md").exists()


# --- .git and .DS_Store are not content ----------------------------------------


def test_git_and_ds_store_are_never_copied_from_a_folder(run, tmp_path, profiles_root):
    checkout = skill_folder(tmp_path / "checkout" / "solo")
    (checkout / ".git").mkdir()
    (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (checkout / ".DS_Store").write_bytes(b"\0finder")
    (checkout / "refs").mkdir()
    (checkout / "refs" / ".DS_Store").write_bytes(b"\0finder")
    (checkout / "refs" / "note.txt").write_text("note\n")
    kept = snapshot(checkout)
    ok(run("profile", "new", "work", "--target", "claude-code"))

    ok(run("add", str(checkout), "-p", "work"))

    copy = profiles_root / "work" / "skills" / "solo"
    found = sorted(
        os.path.relpath(os.path.join(root, name), copy)
        for root, dirs, files in os.walk(copy)
        for name in dirs + files
    )
    assert found == ["SKILL.md", "refs", "refs/note.txt"]
    assert snapshot(checkout) == kept


def test_changes_inside_git_or_a_ds_store_are_neither_an_update_nor_an_edit(
    run, tmp_path, profiles_root
):
    checkout = skill_folder(tmp_path / "checkout" / "solo")
    (checkout / ".git").mkdir()
    ok(run("profile", "new", "work", "--target", "claude-code"))
    ok(run("add", str(checkout), "-p", "work"))
    copy = profiles_root / "work" / "skills" / "solo"

    (checkout / ".git" / "COMMIT_EDITMSG").write_text("an empty commit\n")
    (checkout / ".DS_Store").write_bytes(b"\0finder")
    (copy / ".DS_Store").write_bytes(b"\0finder opened the copy")

    [row] = json.loads(ok(run("update", "--check", "-p", "work", "--json")).output)[
        "skills"
    ]
    assert (row["update_available"], row["modified"]) == (False, False)
    shown = json.loads(ok(run("profile", "show", "work", "--json")).output)
    assert shown["skills"][0]["edited"] is False

    (checkout / "SKILL.md").write_text("# solo v2\n")
    [row] = json.loads(ok(run("update", "-p", "work", "--json")).output)["skills"]
    assert row["result"] == "updated"
    assert (copy / "SKILL.md").read_text() == "# solo v2\n"


def test_git_is_never_copied_from_a_profile_source_and_diff_ignores_both(
    run, installed, pack
):
    pack.skill("lint", True)
    pack.write("skills/lint/.git", "gitdir: ../../.git/modules/lint\n")
    pack.write("skills/tdd/.DS_Store", "finder")
    pack.keep()
    (installed / "house" / ".DS_Store").write_bytes(b"\0finder")

    ok(run("update", "--json"))

    assert sorted(p.name for p in (installed / "lint").iterdir()) == ["SKILL.md"]
    diff = json.loads(ok(run("profile", "diff", "pack", "--json")).output)
    assert diff["matches"] is True, diff
    assert pack.untouched()


def digest_of_everything(folder):
    """The digest respec recorded before it left ``.DS_Store`` out."""
    hasher = hashlib.sha256()
    entries = []
    for root, dirs, files in os.walk(folder):
        entries.extend(os.path.join(root, name) for name in dirs + files)
    for entry in sorted(entries):
        relative = os.path.relpath(entry, folder)
        if os.path.isdir(entry):
            hasher.update(f"d\0{relative}\0".encode())
        else:
            executable = "x" if os.access(entry, os.X_OK) else "-"
            hasher.update(f"f\0{relative}\0{executable}\0".encode())
            with open(entry, "rb") as handle:
                hasher.update(hashlib.sha256(handle.read()).digest())
    return f"sha256:{hasher.hexdigest()}"


def test_a_digest_recorded_when_ds_store_still_counted_stays_valid(
    run, upstream, profiles_root
):
    repo = upstream("acme/skills")
    repo.write("tdd/SKILL.md", "# tdd v1\n")
    repo.commit()
    ok(run("profile", "new", "work", "--target", "claude-code"))
    ok(run("add", "acme/skills#tdd", "-p", "work"))
    # As an earlier respec left it: the repository's .DS_Store was copied
    # and is part of the recorded digest.
    copy = profiles_root / "work" / "skills" / "tdd"
    (copy / ".DS_Store").write_bytes(b"\0committed upstream")
    file = profiles_root / "work" / "profile.yaml"
    data = yaml.safe_load(file.read_text())
    data["skills"]["tdd"]["source"]["digest"] = digest_of_everything(copy)
    file.write_text(yaml.safe_dump(data, sort_keys=False))

    shown = json.loads(ok(run("profile", "show", "work", "--json")).output)
    [row] = json.loads(ok(run("update", "--check", "-p", "work", "--json")).output)[
        "skills"
    ]

    assert shown["skills"][0]["edited"] is False
    assert row["modified"] is False

    (copy / "SKILL.md").write_text("# tdd, edited here\n")
    shown = json.loads(ok(run("profile", "show", "work", "--json")).output)
    assert shown["skills"][0]["edited"] is True


# --- SOURCE.md after an interruption ---------------------------------------------


def test_recover_brings_source_md_in_line_after_a_kill_before_it_was_written(
    run, killed, installed, pack, profiles_root
):
    pack.skill("lint", True)
    file = profiles_root / "pack" / "SOURCE.md"
    assert "`lint`" not in file.read_text()

    assert killed("before-source-file", 1, "update")

    assert "lint" in read_yaml(profiles_root)["skills"]
    assert "`lint`" not in file.read_text()
    ok(run("recover"))
    assert (
        f"- `lint`: from the profile's source; edit it at `{pack.source_of('lint')}`"
        in (file.read_text())
    )


def test_a_stale_source_md_is_only_rewritten_by_a_command_that_changes_things(
    run, installed, pack, profiles_root
):
    file = profiles_root / "pack" / "SOURCE.md"
    fresh = file.read_text()
    file.write_text("stale\n")

    ok(run("profile", "show", "pack"))
    ok(run("status"))
    ok(run("update", "--check"))
    ok(run("profile", "diff", "pack"))
    assert file.read_text() == "stale\n"

    ok(run("enable", "tdd"))  # enabled already: profile.yaml is not saved

    assert file.read_text() == fresh


# --- sources inside respec's own data ------------------------------------------


def test_profile_install_refuses_a_folder_inside_the_respec_home(
    run, installed, profiles_root
):
    result = fails(
        run("profile", "install", str(profiles_root / "pack"), "--name", "q")
    )

    assert "respec" in result.output
    assert not (profiles_root / "q").exists()


def test_add_of_a_link_respec_installed_records_no_source(
    run, installed, claude_dir, profiles_root, assert_no_nulls
):
    ok(run("profile", "new", "r", "--target", "claude-code"))
    assert (claude_dir / "tdd").is_symlink()

    result = ok(run("add", str(claude_dir / "tdd"), "-p", "r", "--json"))

    change = assert_no_nulls(json.loads(result.output))
    assert "source" not in change
    assert read_yaml(profiles_root, "r")["skills"] == {"tdd": {"enabled": True}}
    copy = profiles_root / "r" / "skills" / "tdd"
    assert (copy / "SKILL.md").read_text() == "# tdd v1\n"
    shown = json.loads(ok(run("profile", "show", "r", "--json")).output)
    assert shown["skills"][0]["provenance"] == "original"
    assert str(profiles_root) not in (profiles_root / "r" / "SOURCE.md").read_text()


def test_add_of_a_folder_inside_a_target_folder_records_no_source(
    run, claude_dir, profiles_root
):
    skill_folder(claude_dir / "mine")
    ok(run("profile", "new", "r", "--target", "claude-code"))

    result = ok(run("add", str(claude_dir / "mine"), "-p", "r"))

    assert "Added 'mine' to profile 'r'" in result.output
    assert read_yaml(profiles_root, "r")["skills"] == {"mine": {"enabled": True}}
    assert (profiles_root / "r" / "skills" / "mine" / "SKILL.md").is_file()


# --- a skill folder of a folder source that is a symlink out of it --------------


@pytest.fixture
def outside(tmp_path):
    return skill_folder(tmp_path / "private" / "secret", "# not part of the pack\n")


def test_install_refuses_a_skill_folder_that_links_out_of_the_folder_source(
    run, pack, outside, profiles_root
):
    (pack.folder / "skills" / "secret").symlink_to(outside)
    pack.data["skills"]["secret"] = {"enabled": True}
    pack.save()
    pack.keep()

    result = fails(run("profile", "install", str(pack.folder)))

    assert "outside" in result.output
    assert not (profiles_root / "pack").exists()
    assert pack.untouched()


def test_update_refuses_skill_folders_that_now_link_out_of_the_folder_source(
    run, installed, pack, outside
):
    (pack.folder / "skills" / "secret").symlink_to(outside)
    pack.data["skills"]["secret"] = {"enabled": True}
    pack.save()
    shutil.rmtree(pack.folder / "skills" / "tdd")
    (pack.folder / "skills" / "tdd").symlink_to(outside)
    pack.keep()

    result = run("update", "--yes", "--json")
    named = run("update", "tdd", "--yes", "--json")

    assert result.exit_code == 1, result.output
    found = rows(result)
    assert found["secret"]["result"] == "error"
    assert found["tdd"]["result"] == "error"
    assert "outside" in found["tdd"]["error"]
    assert rows(named)["tdd"]["result"] == "error"
    assert not (installed / "secret").exists()
    assert (installed / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"
    assert pack.untouched()


def test_a_skill_folder_that_links_to_another_folder_of_the_source_is_copied(
    run, pack, profiles_root
):
    pack.write("shared/kit/SKILL.md", "# kit\n")
    (pack.folder / "skills" / "kit").symlink_to(pack.folder / "shared" / "kit")
    pack.data["skills"]["kit"] = {"enabled": True}
    pack.save()

    ok(run("profile", "install", str(pack.folder)))

    kit = profiles_root / "pack" / "skills" / "kit"
    assert not kit.is_symlink()
    assert (kit / "SKILL.md").read_text() == "# kit\n"


def test_the_folder_typed_for_add_may_be_a_symlink_and_is_stored_resolved(
    run, outside, tmp_path, profiles_root
):
    link = tmp_path / "typed"
    link.symlink_to(outside)
    ok(run("profile", "new", "work", "--target", "claude-code"))

    ok(run("add", str(link), "-p", "work"))

    source = read_yaml(profiles_root, "work")["skills"]["secret"]["source"]
    assert source["folder"] == str(outside.resolve())


# --- a new skill whose folder vanishes while the update runs --------------------


def test_a_new_skill_whose_folder_vanishes_mid_update_is_reported(
    installed, pack, holder, assert_no_nulls
):
    pack.skill("lint", True)
    pack.skill("zeta", True)

    update = holder("added", "update", "--json")  # lint is in, zeta is next
    shutil.rmtree(pack.folder / "skills" / "zeta")
    code, out, err = update.finish()

    assert code == 0, out + err
    data = assert_no_nulls(json.loads(out))
    found = {row["skill"]: row for row in data["skills"]}
    assert found["lint"]["result"] == "added"
    assert found["zeta"]["result"] == "source-missing"
    [warning] = data["warnings"]
    assert (warning["type"], warning["skill"]) == ("source-missing", "zeta")
    assert not (installed / "zeta").exists()
