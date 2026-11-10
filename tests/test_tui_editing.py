"""The TUI profile editor: toggles, layers, adding skills, updates, new profiles.

Driven headless through Textual's Pilot against the temporary homes from
``conftest.py``; outcomes are checked in ``profile.yaml``, in the target
folders and through ``respec status``.
"""

import asyncio
import json
import subprocess

import pytest
import yaml

SIZE = (120, 40)


@pytest.fixture
def respec_home(isolated_homes):
    return isolated_homes.respec_home


@pytest.fixture
def claude_dir(isolated_homes):
    return isolated_homes.home / ".claude" / "skills"


def make_profile(respec_home, name, targets, skills, layers=None):
    """``skills`` maps skill name to enabled."""
    folder = respec_home / "profiles" / name
    (folder / "skills").mkdir(parents=True)
    for skill in skills:
        (folder / "skills" / skill).mkdir()
        (folder / "skills" / skill / "SKILL.md").write_text(f"# {skill}\n")
    data = {
        "targets": targets,
        "skills": {skill: {"enabled": on} for skill, on in skills.items()},
    }
    if layers:
        data["layers"] = layers
    (folder / "profile.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return folder


def read_yaml(respec_home, name):
    path = respec_home / "profiles" / name / "profile.yaml"
    return yaml.safe_load(path.read_text())


def enabled(respec_home, name):
    skills = read_yaml(respec_home, name)["skills"]
    return {skill for skill, entry in skills.items() if entry["enabled"]}


def linked(folder):
    if not folder.exists():
        return set()
    return {entry.name for entry in folder.iterdir()}


def ok(result):
    assert result.exit_code == 0, result.output
    return result


def text_of(widget):
    return str(widget.render())


def drive(isolated_homes, scenario):
    from respec.tui import RespecApp

    async def main():
        app = RespecApp(
            respec_home=isolated_homes.respec_home, user_home=isolated_homes.home
        )
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())


async def settle(app, pilot):
    """Wait for background work (git runs in a worker) and the redraw after it."""
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.pause()


async def open_editor(app, pilot, name, key=True):
    if key:
        await pilot.click(f"#profile-{name}")
        await pilot.press("e")
    else:
        await pilot.click(f"#profile-{name}")
        await pilot.click("#edit")
    await pilot.pause()
    assert name in text_of(app.screen.query_one("#editor-title"))


@pytest.fixture
def work(respec_home, run):
    make_profile(respec_home, "work", ["claude-code"], {"s1": True, "s2": True})
    ok(run("use", "work"))


# --- skill toggles ---------------------------------------------------------


def test_clicking_a_toggle_disables_the_skill_and_unlinks_it(
    isolated_homes, respec_home, work, claude_dir
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work", key=False)
        await pilot.click("#toggle-s1")
        await pilot.pause()
        assert "Disabled 's1'" in text_of(app.screen.query_one("#editor-feedback"))

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"s2"}
    assert linked(claude_dir) == {"s2"}


def test_keyboard_toggle_enables_a_disabled_skill_and_links_it(
    isolated_homes, respec_home, run, claude_dir
):
    make_profile(respec_home, "work", ["claude-code"], {"s1": False, "s2": True})
    ok(run("use", "work"))

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        app.screen.query_one("#toggle-s1").focus()
        await pilot.press("space")
        await pilot.pause()
        assert "Enabled 's1'" in text_of(app.screen.query_one("#editor-feedback"))

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"s1", "s2"}
    assert linked(claude_dir) == {"s1", "s2"}


def test_toggle_refused_by_an_unknown_entry_leaves_the_profile_unchanged(
    isolated_homes, respec_home, run, claude_dir
):
    make_profile(respec_home, "work", ["claude-code"], {"s1": False, "s2": True})
    ok(run("use", "work"))
    (claude_dir / "s1").mkdir()
    (claude_dir / "s1" / "SKILL.md").write_text("foreign\n")

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#toggle-s1")
        await pilot.pause()
        feedback = text_of(app.screen.query_one("#editor-feedback"))
        assert "error" in feedback and "s1" in feedback
        assert app.screen.query_one("#toggle-s1").value is False

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"s2"}
    assert (claude_dir / "s1" / "SKILL.md").read_text() == "foreign\n"


def test_toggle_while_another_respec_changes_skills_is_refused_cleanly(
    isolated_homes, respec_home, work, claude_dir, holder
):
    other = holder("links:begin", "disable", "s2")

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#toggle-s1")
        await pilot.pause()
        feedback = text_of(app.screen.query_one("#editor-feedback"))
        assert "another respec is running" in feedback
        assert "interrupted" not in feedback

    drive(isolated_homes, scenario)

    # The other process stopped before it saved; the TUI changed nothing.
    assert enabled(respec_home, "work") == {"s1", "s2"}
    code, out, err = other.finish()
    assert code == 0, out + err
    assert enabled(respec_home, "work") == {"s1"}
    assert linked(claude_dir) == {"s1"}


# --- layers ----------------------------------------------------------------


@pytest.fixture
def layered(respec_home, run):
    make_profile(
        respec_home,
        "work",
        ["claude-code"],
        {"d1": True, "d2": False, "r1": True, "r2": True, "plain": True},
        layers={
            "design-principles": {"skills": ["d1", "d2"]},
            "review": {
                "exclusive": False,
                "description": "Code review helpers",
                "skills": ["r1", "r2"],
            },
        },
    )
    ok(run("use", "work"))


def test_skills_are_grouped_by_layer(isolated_homes, layered):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        design = app.screen.query_one("#group-design-principles")
        review = app.screen.query_one("#group-review")
        plain = app.screen.query_one("#ungrouped")
        assert "exclusive" in text_of(design.query_one(".group-title"))
        assert "Code review helpers" in text_of(review.query_one(".group-title"))
        assert design.query("#choose-design-principles--d1")
        assert design.query("#choose-design-principles--d2")
        assert review.query("#toggle-r1") and review.query("#toggle-r2")
        assert plain.query("#toggle-plain")

    drive(isolated_homes, scenario)


def test_choosing_in_an_exclusive_layer_keeps_one_skill(
    isolated_homes, respec_home, layered, claude_dir
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#choose-design-principles--d2")
        await pilot.pause()
        assert app.screen.query_one("#choose-design-principles--d2").value is True
        assert app.screen.query_one("#choose-design-principles--d1").value is False

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"d2", "r1", "r2", "plain"}
    assert "d2" in linked(claude_dir) and "d1" not in linked(claude_dir)


def test_choosing_none_in_an_exclusive_layer_disables_it(
    isolated_homes, respec_home, layered, claude_dir
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        radios = app.screen.query_one("#layer-design-principles")
        radios.focus()
        # The keyboard: move to "None" and select it.
        await pilot.press("down", "down", "enter")
        await pilot.pause()

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"r1", "r2", "plain"}
    assert not {"d1", "d2"} & linked(claude_dir)


# --- adding skills ---------------------------------------------------------


def test_add_folder_by_key_adds_and_links_the_skill(
    isolated_homes, respec_home, work, claude_dir, tmp_path
):
    folder = tmp_path / "incoming" / "fresh"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# fresh\n")

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.press("a")
        await pilot.pause()
        await pilot.press(*str(folder))
        await pilot.press("enter")
        await pilot.pause()
        feedback = text_of(app.screen.query_one("#editor-feedback"))
        assert "Added 'fresh' to profile 'work'" in feedback
        assert app.screen.query("#toggle-fresh")

    drive(isolated_homes, scenario)

    assert "fresh" in enabled(respec_home, "work")
    assert (claude_dir / "fresh").is_symlink()


def test_add_folder_that_is_not_a_skill_reports_the_error(
    isolated_homes, respec_home, work, tmp_path
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#add-folder")
        await pilot.pause()
        app.screen.query_one("#add-input").value = str(tmp_path)
        await pilot.click("#add-confirm")
        await pilot.pause()
        assert "SKILL.md" in text_of(app.screen.query_one("#editor-feedback"))

    drive(isolated_homes, scenario)

    assert set(read_yaml(respec_home, "work")["skills"]) == {"s1", "s2"}


@pytest.fixture
def remote(isolated_homes, tmp_path, monkeypatch):
    """A bare repository ``acme/skills`` with skill ``tdd``, reached by file://."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.invalid")
    remotes = tmp_path / "remotes"
    bare = remotes / "acme" / "skills"
    bare.mkdir(parents=True)
    monkeypatch.setenv("RESPEC_GIT_BASE_URL", remotes.as_uri())
    work = tmp_path / "upstream"
    work.mkdir()

    def git(cwd, *args):
        done = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
        return done.stdout.strip()

    git(bare, "init", "-q", "--bare", "-b", "main")
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", bare.as_uri())

    def publish(text):
        (work / "skills" / "tdd").mkdir(parents=True, exist_ok=True)
        (work / "skills" / "tdd" / "SKILL.md").write_text(text)
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "change")
        git(work, "push", "-q", "origin", "HEAD:main")
        return git(work, "rev-parse", "HEAD")

    publish("# tdd v1\n")
    return publish


def test_add_from_git_source_records_the_source_and_links_it(
    isolated_homes, respec_home, work, remote, claude_dir
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#add-git")
        await pilot.pause()
        app.screen.query_one("#add-input").value = "acme/skills#skills/tdd"
        await pilot.click("#add-confirm")
        await settle(app, pilot)
        feedback = text_of(app.screen.query_one("#editor-feedback"))
        assert "Added 'tdd' to profile 'work' from acme/skills" in feedback

    drive(isolated_homes, scenario)

    entry = read_yaml(respec_home, "work")["skills"]["tdd"]
    assert entry["enabled"] is True
    assert entry["source"]["repo"] == "acme/skills"
    assert (claude_dir / "tdd" / "SKILL.md").read_text() == "# tdd v1\n"


def test_check_updates_marks_a_skill_with_a_newer_commit(
    isolated_homes, respec_home, work, remote, run
):
    ok(run("add", "acme/skills#skills/tdd", "-p", "work"))
    remote("# tdd v2\n")

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        assert "update available" not in text_of(app.screen.query_one("#skill-tdd"))
        await pilot.press("u")
        await settle(app, pilot)
        assert "update available" in text_of(app.screen.query_one("#skill-tdd"))
        # Skills without a source get no indicator.
        assert "update" not in text_of(app.screen.query_one("#skill-s1"))

    drive(isolated_homes, scenario)


def test_check_updates_by_click_says_up_to_date(
    isolated_homes, respec_home, work, remote, run
):
    ok(run("add", "acme/skills#skills/tdd", "-p", "work"))

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#check-updates")
        await settle(app, pilot)
        assert "up to date" in text_of(app.screen.query_one("#skill-tdd"))

    drive(isolated_homes, scenario)


def test_back_returns_to_the_profile_list_with_fresh_counts(
    isolated_homes, respec_home, work
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.click("#toggle-s1")
        await pilot.pause()
        await pilot.click("#back")
        await pilot.pause()
        assert "1 enabled" in text_of(app.query_one("#profile-work .profile-meta"))
        await open_editor(app, pilot, "work")
        await pilot.press("escape")
        await pilot.pause()
        assert app.query("#profiles")

    drive(isolated_homes, scenario)


# --- new profile -----------------------------------------------------------


def test_new_profile_by_mouse_creates_it_with_the_chosen_targets(
    isolated_homes, respec_home, run
):
    async def scenario(app, pilot):
        await pilot.click("#new")
        await pilot.pause()
        app.screen.query_one("#new-name").value = "fresh"
        await pilot.click("#new-target-claude-code")
        await pilot.click("#new-target-oh-my-pi")
        await pilot.click("#create")
        await pilot.pause()
        assert app.query("#profile-fresh")
        assert "Created profile 'fresh'" in text_of(app.query_one("#feedback"))

    drive(isolated_homes, scenario)

    assert read_yaml(respec_home, "fresh")["targets"] == ["claude-code", "oh-my-pi"]
    listed = json.loads(ok(run("profile", "list", "--json")).stdout)
    assert [p["name"] for p in listed["profiles"]] == ["fresh"]


def test_new_profile_by_keyboard(isolated_homes, respec_home):
    async def scenario(app, pilot):
        await pilot.press("n")
        await pilot.pause()
        await pilot.press(*"kb")
        # Tab to the first target (claude-code), tick it, then submit.
        await pilot.press("tab", "space")
        app.screen.query_one("#new-name").focus()
        await pilot.press("enter")
        await pilot.pause()

    drive(isolated_homes, scenario)

    assert read_yaml(respec_home, "kb")["targets"] == ["claude-code"]


def test_new_profile_without_targets_explains_and_creates_nothing(
    isolated_homes, respec_home
):
    async def scenario(app, pilot):
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#new-name").value = "empty"
        await pilot.click("#create")
        await pilot.pause()
        assert "target" in text_of(app.screen.query_one("#new-error"))
        await pilot.click("#new-cancel")
        await pilot.pause()

    drive(isolated_homes, scenario)

    assert not (respec_home / "profiles" / "empty").exists()


def test_list_keys_do_nothing_in_the_editor_but_sync_opens_and_refreshes_it(
    isolated_homes, respec_home, layered
):
    write = respec_home / "profiles" / "work" / "profile.yaml"

    async def scenario(app, pilot):
        from respec.tui import ProfileScreen

        await open_editor(app, pilot, "work")
        await pilot.press("n", "e")
        await pilot.pause()
        assert isinstance(app.screen, ProfileScreen)
        assert len(app.screen_stack) == 2
        # A hand edit makes a conflict; Sync repairs it from the editor.
        data = yaml.safe_load(write.read_text())
        data["skills"]["d2"]["enabled"] = True
        write.write_text(yaml.safe_dump(data))
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#sync-conflict-0-repair")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ProfileScreen)
        assert app.screen.query_one("#choose-design-principles--d1").value is True
        assert not app.screen.query(".group-note")

    drive(isolated_homes, scenario)

    assert enabled(respec_home, "work") == {"d1", "r1", "r2", "plain"}


@pytest.mark.parametrize("typed", ["~nosuchuser_zz/skill", "bad\x00path"])
def test_add_folder_with_an_unusable_path_shows_the_error_and_keeps_running(
    isolated_homes, respec_home, work, typed
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.press("a")
        await pilot.pause()
        app.screen.query_one("#add-input").value = typed
        await pilot.click("#add-confirm")
        await pilot.pause()
        assert "error" in text_of(app.screen.query_one("#editor-feedback"))
        assert app.return_code is None and app.is_running

    drive(isolated_homes, scenario)

    assert set(read_yaml(respec_home, "work")["skills"]) == {"s1", "s2"}


@pytest.fixture
def silent_server():
    """An http URL whose server accepts connections and never answers."""
    import socket

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    yield f"http://127.0.0.1:{server.getsockname()[1]}/x.git"
    server.close()


def test_add_from_git_shows_progress_stays_responsive_and_can_be_cancelled(
    isolated_homes, respec_home, work, remote, silent_server
):
    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.press("g")
        await pilot.pause()
        app.screen.query_one("#add-input").value = silent_server
        await pilot.click("#add-confirm")
        await pilot.pause()
        assert "Fetching" in text_of(app.screen.query_one("#editor-feedback"))
        cancel = app.screen.query_one("#cancel-git")
        assert cancel.display
        # The screen keeps drawing while git waits; editing waits for it.
        assert app.screen.query_one("#editor-skills").disabled
        await pilot.press("s")  # Sync waits too
        await pilot.pause()
        assert app.screen.query("#cancel-git")
        await pilot.click("#cancel-git")
        await settle(app, pilot)
        feedback = text_of(app.screen.query_one("#editor-feedback"))
        assert "Cancelled" in feedback and "nothing was added" in feedback
        assert not app.screen.query_one("#cancel-git").display

    drive(isolated_homes, scenario)

    assert set(read_yaml(respec_home, "work")["skills"]) == {"s1", "s2"}


def test_escape_cancels_a_running_update_check(
    isolated_homes, respec_home, work, remote, run, silent_server
):
    from respec.tui import ProfileScreen

    ok(run("add", "acme/skills#skills/tdd", "-p", "work"))
    data = read_yaml(respec_home, "work")
    data["skills"]["tdd"]["source"]["repo"] = silent_server
    (respec_home / "profiles" / "work" / "profile.yaml").write_text(
        yaml.safe_dump(data)
    )

    async def scenario(app, pilot):
        await open_editor(app, pilot, "work")
        await pilot.press("u")
        await pilot.pause()
        assert "Checking" in text_of(app.screen.query_one("#editor-feedback"))
        await pilot.press("escape")
        await settle(app, pilot)
        # Escape stopped the check; the editor is still open.
        assert isinstance(app.screen, ProfileScreen)
        assert "Cancelled" in text_of(app.screen.query_one("#editor-feedback"))

    drive(isolated_homes, scenario)


def test_e_right_after_launch_edits_the_active_profile(
    isolated_homes, respec_home, run
):
    make_profile(respec_home, "alpha", ["agents"], {"a1": True})
    make_profile(respec_home, "work", ["claude-code"], {"s1": True})
    ok(run("use", "work"))

    async def scenario(app, pilot):
        await pilot.press("e")
        await pilot.pause()
        assert "work" in text_of(app.screen.query_one("#editor-title"))

    drive(isolated_homes, scenario)


def test_e_right_after_launch_without_an_active_profile_edits_the_first(
    isolated_homes, respec_home
):
    make_profile(respec_home, "alpha", ["agents"], {"a1": True})

    async def scenario(app, pilot):
        await pilot.press("e")
        await pilot.pause()
        assert "alpha" in text_of(app.screen.query_one("#editor-title"))

    drive(isolated_homes, scenario)


def test_new_profile_that_cannot_be_written_shows_the_error(
    isolated_homes, respec_home, monkeypatch
):
    from respec import profiles

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(respec_home))

    monkeypatch.setattr(profiles, "create_profile", refuse)

    async def scenario(app, pilot):
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#new-name").value = "fresh"
        await pilot.click("#new-target-claude-code")
        await pilot.click("#create")
        await pilot.pause()
        assert "Permission denied" in text_of(app.screen.query_one("#new-error"))
        assert app.is_running

    drive(isolated_homes, scenario)
