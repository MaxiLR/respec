"""Textual TUI: profiles, switching, status, profile editing and the Sync check.

A thin layer over the same core functions the CLI uses: profiles are read with
:mod:`respec.profiles`, switching and status come from :mod:`respec.switch`,
unknown entries are resolved through :mod:`respec.adopt`, profiles are edited
through :mod:`respec.items`, :mod:`respec.layers` and :mod:`respec.sources`
(with their safety checks and rollback), and the Sync check comes from
:mod:`respec.sync`. The TUI only collects choices and renders results.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Input,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
    Switch,
)

from respec import (
    adopt,
    items,
    layers,
    profiles,
    sources,
    switch,
    sync,
    targets,
    unknown,
)
from respec.errors import RespecError
from respec.state import load_state

# Semantic colour tokens from the default design language (Bencho, dark theme),
# shared by the stylesheet and the styled text below.
COLORS = {
    "page": "#101114",
    "surface-base": "#191b1e",
    "surface-raised": "#222428",
    "surface-high": "#2a2c31",
    "text-primary": "#eceae5",
    "text-secondary": "#b8b7b1",
    "text-muted": "#9d9c96",
    "accent": "#3aa9ff",
    "success": "#34d17a",
    "warning": "#e8b04b",
    "danger": "#ff6b6b",
}
SECONDARY = COLORS["text-secondary"]
MUTED = COLORS["text-muted"]
SUCCESS = COLORS["success"]
WARNING = COLORS["warning"]
DANGER = COLORS["danger"]
ACCENT = COLORS["accent"]
SYNC_ICON = "⟳"

CSS = "".join(f"${name}: {value};\n" for name, value in COLORS.items()) + """

Screen {
    background: $page;
    color: $text-primary;
}

#topbar {
    height: 1;
    padding: 0 2;
    background: $surface-base;
}
#title { width: auto; text-style: bold; color: $text-primary; }
#active { width: 1fr; content-align-horizontal: right; color: $text-secondary; }
#topbar Button { height: 1; min-width: 8; margin-left: 2; }

#body { height: 1fr; padding: 1 1 0 1; }

#sidebar {
    width: 36;
    margin-right: 1;
    padding: 0 1;
    background: $surface-base;
    border: round $surface-high;
    border-title-color: $text-secondary;
}
#profiles { height: 1fr; background: $surface-base; }
#profiles > ListItem {
    background: $surface-base;
    padding: 0 1;
    margin-bottom: 1;
}
#profiles > ListItem.-highlight { background: $surface-high; }
#profiles:focus > ListItem.-highlight { background: $surface-high; }
.profile-name { color: $text-primary; }
.profile-meta { color: $text-muted; }
#profiles-empty { color: $text-secondary; padding: 1 0; }
#activate { width: 100%; margin: 1 0 0 0; }
#profile-actions { height: auto; margin: 1 0; }
#profile-actions Button { width: 1fr; }
#profile-actions #edit { margin-right: 1; }

#status {
    width: 1fr;
    padding: 0 1;
    background: $surface-base;
    border: round $surface-high;
    border-title-color: $text-secondary;
}
.folder {
    background: $surface-raised;
    padding: 0 1;
    margin-bottom: 1;
}
#status-empty { color: $text-secondary; padding: 1 0; }

#feedback { height: auto; max-height: 6; padding: 0 2; color: $text-secondary; }
#feedback.-success { color: $success; }
#feedback.-error { color: $danger; }

Button {
    background: $surface-raised;
    color: $text-primary;
    border: none;
    min-width: 10;
}
Button:hover { background: $surface-high; }
Button:focus { text-style: bold; background: $surface-high; color: $accent; }
Button.-primary { background: $accent; color: $page; }
Button:disabled { background: $surface-base; color: $text-muted; }

AdoptDialog, AddDialog, NewProfileDialog, SyncScreen {
    align: center middle;
    background: $page 70%;
}
#dialog {
    width: 96;
    max-height: 90%;
    height: auto;
    padding: 1 2;
    background: $surface-base;
    border: round $surface-high;
    border-title-color: $text-primary;
}
#dialog-intro { color: $text-secondary; margin-bottom: 1; }
#entries { height: auto; max-height: 24; }
.unknown { height: auto; margin-bottom: 1; }
.unknown-path { color: $text-primary; }
.unknown-meta { color: $text-muted; }
.unknown RadioSet {
    width: 100%;
    layout: horizontal;
    background: $surface-base;
    border: none;
}
.unknown RadioButton { background: $surface-base; margin-right: 2; }
#dialog-actions { height: auto; align-horizontal: right; }
#dialog-actions Button { margin-left: 1; }
.field-label { color: $text-secondary; margin-top: 1; }
Input { background: $surface-raised; border: tall $surface-high; }
Input:focus { border: tall $accent; }
Checkbox { background: $surface-base; border: none; }
.dialog-error { color: $danger; height: auto; }

#editor-bar { height: 1; padding: 0 2; background: $surface-base; }
#editor-title { width: 1fr; }
#editor-skills {
    height: 1fr;
    margin: 1 1 0 1;
    padding: 0 1;
    background: $surface-base;
    border: round $surface-high;
    border-title-color: $text-secondary;
}
.group { height: auto; margin-bottom: 1; }
.group-title { color: $text-primary; }
.group-note { color: $warning; }
.group RadioSet { width: 100%; background: $surface-base; border: none; }
.group RadioButton { background: $surface-base; }
.skill-row { height: auto; }
.skill-row Switch { background: $surface-base; border: none; }
.skill-meta { width: 1fr; padding: 0 1; content-align-vertical: middle; }
#editor-empty { color: $text-secondary; padding: 1 0; }
#editor-actions { height: auto; padding: 1 1 0 1; }
#editor-actions Button { margin-right: 1; }
#editor-log { height: auto; max-height: 8; padding: 0 2; }
#editor-feedback { color: $text-secondary; }
#editor-feedback.-success { color: $success; }
#editor-feedback.-error { color: $danger; }

#sync-summary { margin-bottom: 1; }
#sync-summary.-success { color: $success; }
#sync-summary.-warning { color: $warning; }
SyncScreen #dialog { height: 90%; }
#sync-body { height: 1fr; }
#sync-log {
    height: auto;
    padding: 0 1;
    margin-bottom: 1;
    background: $surface-raised;
    color: $text-secondary;
}
.section { height: auto; margin-bottom: 1; }
.section-title { text-style: bold; color: $text-primary; }
.section-intro { color: $text-muted; }
.conflict { height: auto; margin-bottom: 1; }
.conflict RadioSet {
    width: 100%;
    layout: horizontal;
    background: $surface-base;
    border: none;
}
.conflict RadioButton { background: $surface-base; margin-right: 2; }
.section Button { margin-top: 1; }
"""


def _escape(name: str) -> str:
    """``name`` usable in a DOM id: '.' escaped without collisions."""
    return name.replace("_", "__").replace(".", "_-")


def _dom_id(prefix: str, name: str) -> str:
    """A DOM id for a name that may hold '.'."""
    return f"{prefix}-{_escape(name)}"


def _choice_id(layer: str, skill: str) -> str:
    """The DOM id of ``skill``'s button in exclusive layer ``layer``."""
    return f"{_dom_id('choose', layer)}--{_escape(skill)}"


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _one_line(error: Exception) -> str:
    return " ".join(line.strip() for line in str(error).splitlines())


def _link_lines(change: Any) -> list[str]:
    """The links a change added or removed (the CLI's wording)."""
    return [
        *(f"  linked {path}" for path in change.linked),
        *(f"  unlinked {path}" for path in change.unlinked),
    ]


def _skill_change_lines(change: items.SkillChange) -> list[str]:
    where = f"{change.skill!r} {{}} profile {change.profile!r}"
    lead = {
        "add": "Added " + where.format("to"),
        "enable": "Enabled " + where.format("in"),
        "disable": "Disabled " + where.format("in"),
    }[change.action]
    return [lead, *_link_lines(change)]


def _layer_change_lines(change: layers.LayerChange) -> list[str]:
    where = f"layer {change.layer!r} of profile {change.profile!r}"
    lead = {
        "use": f"Using {change.skill!r} in {where}",
        "disable": f"Disabled the skills of {where}",
        "repair": f"Repaired {where}: kept {change.skill!r}",
        "nothing": f"Nothing to repair in {where}: at most one skill is enabled",
        "additive": f"Nothing to repair in {where}: it is additive",
    }[change.action]
    if change.disabled:
        lead += ", disabled " + ", ".join(repr(skill) for skill in change.disabled)
    return [lead, *_link_lines(change)]


def _source_label(source: profiles.Source) -> str:
    where = f"{source.repo}#{source.path}" if source.path else source.repo
    return f"{where}@{source.ref}" if source.ref else where


def _short(commit: str | None) -> str:
    return commit[:12] if commit else "unknown"


def _skill_text(
    name: str, entry: profiles.SkillEntry, update: sources.Row | None
) -> Text:
    """A skill's name, where it came from and, once checked, its update state."""
    text = Text(name, style="bold")
    if entry.source is not None:
        text.append(f"  from {_source_label(entry.source)}", style=MUTED)
    if update is None:
        return text
    if update.error:
        text.append(f"  check failed: {update.error.splitlines()[0]}", style=DANGER)
    elif update.update_available:
        text.append(
            f"  ⬆ update available {_short(update.current)} → {_short(update.latest)}",
            style=WARNING,
        )
    else:
        text.append("  ✓ up to date", style=SUCCESS)
    if update.modified:
        text.append("  local edits", style=MUTED)
    return text


def _profile_rows(respec_home: Path) -> list[tuple[str, str]]:
    """(name, one-line summary) for every profile folder."""
    rows: list[tuple[str, str]] = []
    for name in profiles.list_profile_names(respec_home):
        try:
            profile = profiles.load_profile(respec_home, name)
        except RespecError:
            rows.append((name, "invalid profile.yaml"))
            continue
        enabled = sum(entry.enabled for entry in profile.skills.values())
        rows.append(
            (
                name,
                f"{', '.join(profile.targets)}\n"
                f"{len(profile.skills)} skill{'' if len(profile.skills) == 1 else 's'}, "
                f"{enabled} enabled",
            )
        )
    return rows


def _folder_text(folder: dict[str, Any]) -> Text:
    """One target folder of :func:`respec.switch.status` as styled text."""
    text = Text()
    text.append(folder["target"], style="bold")
    text.append(f"  {folder['skills_dir']}\n", style=MUTED)
    if folder["same_as"]:
        text.append(f"same folder as {folder['same_as']}", style=SECONDARY)
        return text
    lines: list[Text] = []
    for skill in folder["skills"]:
        lines.append(
            Text.assemble(("● ", SUCCESS), skill["name"], (f"  {skill['mode']}", MUTED))
        )
    for entry in folder["unknown"]:
        replaced = ", edited or replaced copy" if entry["replaced"] else ""
        lines.append(
            Text.assemble(
                ("▲ ", WARNING),
                entry["name"],
                (f"  unknown {entry['kind']}{replaced}", WARNING),
            )
        )
    if not lines:
        lines.append(Text("no managed skills", style=MUTED))
    text.append(Text("\n").join(lines))
    return text


def _backup_lines(backups: dict[str, str]) -> list[str]:
    """Folders respec took over, with their backups (the CLI's wording)."""
    return [f"Backed up {target} folder to {path}" for target, path in backups.items()]


def _resolved_text(lead: str, resolved: Sequence[adopt.Resolution]) -> str:
    """``lead``, then what happened to each entry (the CLI's wording)."""
    return "\n".join([lead, *(resolution.describe() for resolution in resolved)])


def _unknown_meta(entry: unknown.Unknown) -> str:
    replaced = (
        ", an edited or replaced copy of a skill respec installed"
        if entry.replaced
        else ""
    )
    return f"{entry.kind} in {', '.join(entry.targets)}{replaced}"


class ProfileList(ListView):
    """Profile list: a click or the arrow keys select, Enter activates."""

    BINDINGS = [Binding("enter", "select_cursor", "Activate")]

    def action_select_cursor(self) -> None:
        item = self.highlighted_child
        if isinstance(item, ProfileItem):
            self.app.activate(item.profile_name)


class ProfileItem(ListItem):
    def __init__(self, name: str, summary: str, active: bool) -> None:
        super().__init__(id=_dom_id("profile", name))
        self.profile_name = name
        self.summary = summary
        self.active = active

    def compose(self) -> ComposeResult:
        if self.active:
            label = Text.assemble(
                ("● ", SUCCESS), (self.profile_name, "bold"), ("  active", SUCCESS)
            )
        else:
            label = Text.assemble(("  ", ""), self.profile_name)
        yield Static(label, classes="profile-name")
        yield Static(self.summary, classes="profile-meta")


class AdoptDialog(ModalScreen[dict[str, str] | None]):
    """Ask, per unknown entry: add to the active profile, or back up and remove.

    Without a profile to add to, only remove is offered. Dismisses with
    ``{path: choice}`` (choices from :func:`respec.adopt.choices`) or ``None``
    when cancelled.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, entries: list[unknown.Unknown], profile: str | None, reason: str
    ) -> None:
        super().__init__()
        self.entries = entries
        self.profile = profile
        self.reason = reason
        self.choices: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        labels = {
            "add": f"Add to profile {self.profile}",
            "remove": "Back up and remove",
        }
        with Vertical(id="dialog") as dialog:
            dialog.border_title = "Unknown entries"
            yield Static(self.reason, id="dialog-intro")
            with VerticalScroll(id="entries"):
                for index, entry in enumerate(self.entries):
                    with Vertical(id=f"unknown-{index}", classes="unknown"):
                        yield Static(entry.path, classes="unknown-path")
                        yield Static(_unknown_meta(entry), classes="unknown-meta")
                        with RadioSet(id=f"unknown-{index}-choice"):
                            for choice in adopt.choices(self.profile):
                                yield RadioButton(
                                    labels[choice], id=f"unknown-{index}-{choice}"
                                )
            with Horizontal(id="dialog-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Apply", id="apply", variant="primary", disabled=True)

    @on(RadioSet.Changed)
    def _chosen(self, event: RadioSet.Changed) -> None:
        index = int(event.radio_set.id.split("-")[1])
        choice = event.pressed.id.rsplit("-", 1)[1]
        self.choices[self.entries[index].path] = choice
        self.query_one("#apply", Button).disabled = len(self.choices) < len(
            self.entries
        )

    @on(Button.Pressed, "#apply")
    def _apply(self) -> None:
        self.dismiss(dict(self.choices))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class AddDialog(ModalScreen[tuple[str, str | None] | None]):
    """Ask for a local skill folder, or for a git source and an optional ref.

    Dismisses with ``(text, ref)`` or ``None`` when cancelled.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, profile: str, git: bool) -> None:
        super().__init__()
        self.profile = profile
        self.git = git

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog") as dialog:
            if self.git:
                dialog.border_title = "Add from a git source"
                intro = (
                    f"Fetch skills into profile {self.profile} from 'owner/repo', "
                    "'owner/repo#path' or a git URL. The source is recorded, so "
                    "updates can be checked later."
                )
                placeholder = "owner/repo#path/to/skill"
            else:
                dialog.border_title = "Add a skill folder"
                intro = (
                    f"Copy a local skill folder (one with SKILL.md) into profile "
                    f"{self.profile}. It is enabled right away."
                )
                placeholder = "~/path/to/skill"
            yield Static(intro, id="dialog-intro")
            yield Input(placeholder=placeholder, id="add-input")
            if self.git:
                yield Static("Ref (optional)", classes="field-label")
                yield Input(placeholder="branch, tag or commit", id="add-ref")
            with Horizontal(id="dialog-actions"):
                yield Button("Cancel", id="add-cancel")
                yield Button("Add", id="add-confirm", variant="primary")

    @on(Input.Submitted)
    @on(Button.Pressed, "#add-confirm")
    def _confirm(self) -> None:
        text = self.query_one("#add-input", Input).value.strip()
        if not text:
            self.query_one("#add-input", Input).focus()
            return
        ref = None
        if self.git:
            ref = self.query_one("#add-ref", Input).value.strip() or None
        self.dismiss((text, ref))

    @on(Button.Pressed, "#add-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class NewProfileDialog(ModalScreen[profiles.Profile | None]):
    """Name a new profile and choose its targets; creates it on confirm."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, respec_home: Path) -> None:
        super().__init__()
        self.respec_home = respec_home

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog") as dialog:
            dialog.border_title = "New profile"
            yield Static("Name", classes="field-label")
            yield Input(placeholder="work", id="new-name")
            yield Static(
                "Targets (the folders this profile is applied to)",
                classes="field-label",
            )
            for target in targets.registry().values():
                yield Checkbox(
                    f"{target.display_name}  {target.global_skills_dir}",
                    id=_dom_id("new-target", target.name),
                )
            yield Static("", id="new-error", classes="dialog-error")
            with Horizontal(id="dialog-actions"):
                yield Button("Cancel", id="new-cancel")
                yield Button("Create", id="create", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#new-name", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#create")
    def _create(self) -> None:
        name = self.query_one("#new-name", Input).value.strip()
        chosen = [
            target
            for target in targets.registry()
            if self.query_one(f"#{_dom_id('new-target', target)}", Checkbox).value
        ]
        error = self.query_one("#new-error", Static)
        if not name:
            error.update("Give the profile a name.")
            return
        if not chosen:
            error.update("Choose at least one target folder.")
            return
        try:
            profile = profiles.create_profile(self.respec_home, name, chosen)
        except RespecError as problem:
            error.update(f"error: {_one_line(problem)}")
            return
        self.dismiss(profile)

    @on(Button.Pressed, "#new-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class SkillSwitch(Switch):
    """Enable or disable one skill (Space, Enter or a click)."""

    def __init__(self, skill: str, value: bool) -> None:
        super().__init__(value=value, id=_dom_id("toggle", skill))
        self.skill = skill


class SkillChoice(RadioButton):
    """One skill of an exclusive layer; ``skill`` is ``None`` for "None"."""

    def __init__(self, label: Text | str, layer: str, skill: str | None, value: bool):
        button_id = _choice_id(layer, skill) if skill else _dom_id("none", layer)
        super().__init__(label, value=value, id=button_id)
        self.skill = skill


class LayerChoice(RadioSet):
    """Exclusive selection inside one active exclusive layer."""

    def __init__(self, layer: str, *buttons: SkillChoice) -> None:
        super().__init__(*buttons, id=_dom_id("layer", layer))
        self.layer_name = layer


class ProfileScreen(Screen[None]):
    """One profile: skills grouped by layer, toggles, adding, update checks.

    Every change goes through :mod:`respec.items`, :mod:`respec.layers` or
    :mod:`respec.sources`, exactly as the CLI does, so an active profile is
    re-applied at once and a refused change leaves the profile as it was.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add_folder", "Add folder"),
        Binding("g", "add_git", "Add from git"),
        Binding("u", "check_updates", "Check updates"),
    ]

    def __init__(self, respec_home: Path, user_home: Path, profile: str) -> None:
        super().__init__()
        self.respec_home = respec_home
        self.user_home = user_home
        self.profile_name = profile
        self.updates: dict[str, sources.Row] = {}
        self._drawing = asyncio.Lock()

    def compose(self) -> ComposeResult:
        with Horizontal(id="editor-bar"):
            yield Static("", id="editor-title")
        with VerticalScroll(id="editor-skills") as panel:
            panel.border_title = "Skills"
        with Horizontal(id="editor-actions"):
            yield Button("Add folder", id="add-folder", variant="primary")
            yield Button("Add from git", id="add-git")
            yield Button("Check updates", id="check-updates")
            yield Button("Back", id="back")
        with VerticalScroll(id="editor-log"):
            yield Static("", id="editor-feedback")
        yield Footer()

    async def on_screen_resume(self) -> None:
        """Draw on opening, and again after Sync or a dialog closes."""
        await self.render_profile()

    # --- rendering ----------------------------------------------------------

    def _load(self) -> profiles.Profile | None:
        try:
            return profiles.load_profile(self.respec_home, self.profile_name)
        except RespecError as error:
            self.show_feedback([f"error: {_one_line(error)}"], ok=False)
            return None

    async def render_profile(self) -> None:
        """Re-read the profile from disk and redraw every group."""
        async with self._drawing:  # one redraw at a time: ids stay unique
            await self._render_profile()

    async def _render_profile(self) -> None:
        profile = self._load()
        panel = self.query_one("#editor-skills", VerticalScroll)
        focused = self.focused.id if self.focused is not None else None
        await panel.remove_children()
        if profile is None:
            return
        try:
            active = load_state(self.respec_home).active_profile == profile.name
        except RespecError:
            active = False
        title = Text.assemble(
            ("Profile ", SECONDARY),
            (profile.name, "bold"),
            (f"  {', '.join(profile.targets)}", MUTED),
        )
        if active:
            title.append("  ● active", style=SUCCESS)
        self.query_one("#editor-title", Static).update(title)
        groups = [
            self._layer_group(profile, name, layer)
            for name, layer in profile.layers.items()
            if layer.items or not layer.builtin
        ]
        loose = [skill for skill in profile.skills if profile.layer_of(skill) is None]
        if loose:
            group = Vertical(id="ungrouped", classes="group")
            group.compose_add_child(
                Static(Text("Skills", style="bold"), classes="group-title")
            )
            for skill in loose:
                group.compose_add_child(self._skill_row(profile, skill))
            groups.append(group)
        if not profile.skills:
            groups.insert(
                0,
                Static(
                    "No skills yet. Press a to add a skill folder, or g to add "
                    "skills from a git source.",
                    id="editor-empty",
                ),
            )
        await panel.mount_all(groups)
        if focused:
            for widget in self.query(f"#{focused}"):
                if widget.focusable:
                    widget.focus()

    def _skill_row(self, profile: profiles.Profile, skill: str) -> Horizontal:
        entry = profile.skills[skill]
        row = Horizontal(classes="skill-row")
        row.compose_add_child(SkillSwitch(skill, entry.enabled))
        row.compose_add_child(
            Static(
                _skill_text(skill, entry, self.updates.get(skill)),
                id=_dom_id("skill", skill),
                classes="skill-meta",
            )
        )
        return row

    def _layer_group(
        self, profile: profiles.Profile, name: str, layer: profiles.Layer
    ) -> Vertical:
        title = Text(name, style="bold")
        if not layer.exclusive:
            title.append("  additive", style=SECONDARY)
        elif layer.active:
            title.append("  exclusive · one skill at a time", style=SECONDARY)
        else:
            title.append("  exclusive, off: its rules lapse", style=SECONDARY)
        if layer.description:
            title.append(f"  {layer.description}", style=MUTED)
        group = Vertical(id=_dom_id("group", name), classes="group")
        group.compose_add_child(Static(title, classes="group-title"))
        members = [skill for skill in layer.items if skill in profile.skills]
        if not members:
            group.compose_add_child(
                Static("no skills in this layer", classes="section-intro")
            )
            return group
        if not (layer.exclusive and layer.active):
            for skill in members:
                group.compose_add_child(self._skill_row(profile, skill))
            return group
        on = profiles.enabled_members(profile, name)
        if len(on) > 1:
            group.compose_add_child(
                Static(
                    f"{len(on)} skills are enabled ({', '.join(on)}); choose one "
                    "here, or repair the layer with Sync.",
                    classes="group-note",
                )
            )
        buttons = [
            SkillChoice(
                _skill_text(skill, profile.skills[skill], self.updates.get(skill)),
                name,
                skill,
                value=on == [skill],
            )
            for skill in members
        ]
        buttons.append(SkillChoice("None", name, None, value=not on))
        group.compose_add_child(LayerChoice(name, *buttons))
        return group

    def show_feedback(self, lines: Sequence[str], ok: bool) -> None:
        feedback = self.query_one("#editor-feedback", Static)
        feedback.update("\n".join(lines))
        feedback.set_class(ok, "-success")
        feedback.set_class(not ok, "-error")
        self.query_one("#editor-log", VerticalScroll).scroll_home(animate=False)

    def _failed(self, error: RespecError) -> None:
        self.show_feedback(f"error: {str(error).strip()}".splitlines(), ok=False)

    # --- actions ------------------------------------------------------------

    @on(Switch.Changed)
    async def _toggled(self, event: Switch.Changed) -> None:
        switch_ = event.switch
        if not isinstance(switch_, SkillSwitch):
            return
        profile = self._load()
        if profile is None or switch_.skill not in profile.skills:
            return
        if profile.skills[switch_.skill].enabled == event.value:
            return  # already so (for example the initial value)
        try:
            change = items.set_enabled(
                self.respec_home,
                self.user_home,
                switch_.skill,
                event.value,
                self.profile_name,
            )
        except RespecError as error:
            self._failed(error)
        else:
            self.show_feedback(_skill_change_lines(change), ok=True)
        await self.render_profile()

    @on(RadioSet.Changed)
    async def _chosen(self, event: RadioSet.Changed) -> None:
        radio = event.radio_set
        if not isinstance(radio, LayerChoice) or not isinstance(
            event.pressed, SkillChoice
        ):
            return
        profile = self._load()
        if profile is None or radio.layer_name not in profile.layers:
            return
        on = profiles.enabled_members(profile, radio.layer_name)
        skill = event.pressed.skill
        if (skill is None and not on) or (skill is not None and on == [skill]):
            return  # already so
        try:
            if skill is None:
                change = layers.set_enabled(
                    self.respec_home,
                    self.user_home,
                    radio.layer_name,
                    False,
                    self.profile_name,
                )
            else:
                change = layers.use(
                    self.respec_home,
                    self.user_home,
                    radio.layer_name,
                    skill,
                    self.profile_name,
                )
        except RespecError as error:
            self._failed(error)
        else:
            self.show_feedback(_layer_change_lines(change), ok=True)
        await self.render_profile()

    @on(Button.Pressed, "#add-folder")
    def action_add_folder(self) -> None:
        self._ask_to_add(git=False)

    @on(Button.Pressed, "#add-git")
    def action_add_git(self) -> None:
        self._ask_to_add(git=True)

    def _ask_to_add(self, git: bool) -> None:
        async def chosen(answer: tuple[str, str | None] | None) -> None:
            if answer is None:
                return
            text, ref = answer
            try:
                if git:
                    change = sources.add(
                        self.respec_home, self.user_home, text, self.profile_name, ref
                    )
                    lines = [
                        f"Added {skill!r} to profile {change.profile!r} from "
                        f"{_source_label(profiles.Source(**change.sources[skill]))} "
                        f"at {change.sources[skill]['commit'][:12]}"
                        for skill in change.skills
                    ] + _link_lines(change)
                else:
                    added = items.add(
                        self.respec_home,
                        self.user_home,
                        Path(text).expanduser(),
                        self.profile_name,
                    )
                    lines = _skill_change_lines(added)
            except RespecError as error:
                self._failed(error)
            else:
                self.show_feedback(lines, ok=True)
            await self.render_profile()

        self.app.push_screen(AddDialog(self.profile_name, git), chosen)

    @on(Button.Pressed, "#check-updates")
    async def action_check_updates(self) -> None:
        """Ask each skill's source for a newer commit (manual, never polled)."""
        try:
            _, rows = sources.check(self.respec_home, self.profile_name)
        except RespecError as error:
            self._failed(error)
            return
        self.updates = {row.skill: row for row in rows}
        if not rows:
            self.show_feedback(
                [f"Profile {self.profile_name!r} has no skills with a source."],
                ok=True,
            )
        else:
            newer = [row.skill for row in rows if row.update_available]
            failed = [row.skill for row in rows if row.error]
            lines = [
                f"Checked {_plural(len(rows), 'skill', 'skills')} with a source: "
                + (
                    f"updates available for {', '.join(newer)}"
                    if newer
                    else "no updates available"
                )
            ]
            if failed:
                lines.append(f"Could not check {', '.join(failed)}")
            if newer:
                lines.append("Apply them with 'respec update'.")
            self.show_feedback(lines, ok=not failed)
        await self.render_profile()

    @on(Button.Pressed, "#back")
    def action_back(self) -> None:
        self.dismiss(None)


class SyncScreen(ModalScreen[None]):
    """A manual check of the setup and every profile, with the fixes.

    Nothing is watched or polled: the check runs when the screen opens and
    when "Check again" is pressed. Unknown entries are resolved through
    :func:`respec.adopt.adopt` (which refuses to add into a profile with
    layer conflicts and rolls back a failed run), conflicts through
    :func:`respec.layers.repair`, and link problems by re-applying the
    active profile. Every completed fix is listed in the log.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("c", "recheck", "Check again"),
    ]

    def __init__(self, respec_home: Path, user_home: Path) -> None:
        super().__init__()
        self.respec_home = respec_home
        self.user_home = user_home
        self.report = sync.SyncReport()
        self.choices: dict[str, str] = {}
        self.log_lines: list[Text] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog") as dialog:
            dialog.border_title = f"{SYNC_ICON} Sync"
            yield Static("", id="sync-summary")
            with VerticalScroll(id="sync-body"):
                log = Static("", id="sync-log")
                log.display = False
                yield log
                yield Vertical(id="sync-findings")
            with Horizontal(id="dialog-actions"):
                yield Button(f"{SYNC_ICON} Check again", id="sync-recheck")
                yield Button("Close", id="sync-close", variant="primary")

    async def on_mount(self) -> None:
        await self.run_check()

    # --- rendering ----------------------------------------------------------

    async def run_check(self) -> None:
        """Look at the setup and every profile now, and redraw the findings."""
        self.choices = {}
        try:
            self.report = sync.check(self.respec_home, self.user_home)
        except RespecError as error:
            self.report = sync.SyncReport()
            self._log(f"error: {_one_line(error)}", ok=False)
            summary_text = "The check failed; see above."
            self._summary(summary_text, clean=False)
            await self.query_one("#sync-findings").remove_children()
            return
        report = self.report
        if report.clean:
            self._summary(
                "All in sync: no unknown entries, layer conflicts or link problems.",
                clean=True,
            )
        else:
            found = []
            if report.unknown:
                found.append(
                    _plural(len(report.unknown), "unknown entry", "unknown entries")
                )
            if report.conflicts:
                found.append(
                    _plural(len(report.conflicts), "layer conflict", "layer conflicts")
                )
            if report.links:
                found.append(
                    _plural(len(report.links), "link problem", "link problems")
                )
            if report.invalid:
                found.append(
                    _plural(len(report.invalid), "invalid profile", "invalid profiles")
                )
            self._summary("Found " + ", ".join(found) + ".", clean=False)
        findings = self.query_one("#sync-findings", Vertical)
        await findings.remove_children()
        sections = []
        if report.unknown:
            sections.append(self._unknown_section(report))
        if report.conflicts:
            sections.append(self._conflict_section(report))
        if report.links:
            sections.append(self._link_section(report))
        if report.invalid:
            sections.append(self._invalid_section(report))
        await findings.mount_all(sections)

    def _summary(self, text: str, clean: bool) -> None:
        summary = self.query_one("#sync-summary", Static)
        summary.update(text)
        summary.set_class(clean, "-success")
        summary.set_class(not clean, "-warning")

    def _section(self, title: str, intro: str, section_id: str) -> Vertical:
        section = Vertical(id=section_id, classes="section")
        section.compose_add_child(Static(title, classes="section-title"))
        section.compose_add_child(Static(intro, classes="section-intro"))
        return section

    def _unknown_section(self, report: sync.SyncReport) -> Vertical:
        profile = report.active_profile
        section = self._section(
            "Unknown entries",
            "Not placed by respec, or edited copies of skills it installed. "
            "Choose for each; entries left unchosen stay as they are.",
            "sync-unknown",
        )
        labels = {"add": f"Add to profile {profile}", "remove": "Back up and remove"}
        for index, entry in enumerate(report.unknown):
            row = Vertical(id=f"sync-unknown-{index}", classes="unknown")
            row.compose_add_child(Static(entry.path, classes="unknown-path"))
            row.compose_add_child(Static(_unknown_meta(entry), classes="unknown-meta"))
            row.compose_add_child(
                RadioSet(
                    *(
                        RadioButton(labels[choice], id=f"sync-unknown-{index}-{choice}")
                        for choice in adopt.choices(profile)
                    ),
                    id=f"sync-unknown-{index}-choice",
                )
            )
            section.compose_add_child(row)
        section.compose_add_child(
            Button("Resolve chosen", id="sync-resolve", disabled=True)
        )
        return section

    def _conflict_section(self, report: sync.SyncReport) -> Vertical:
        section = self._section(
            "Layer conflicts",
            "Exclusive layers with more than one enabled skill. Choose the skill "
            "to keep; the others are disabled ('respec layer repair').",
            "sync-conflicts",
        )
        for index, conflict in enumerate(report.conflicts):
            row = Vertical(id=f"sync-conflict-{index}", classes="conflict")
            row.compose_add_child(
                Static(
                    f"Layer {conflict.layer!r} of profile {conflict.profile!r} has "
                    f"{len(conflict.skills)} enabled skills: "
                    f"{', '.join(conflict.skills)}. Keep:",
                    classes="conflict-text",
                )
            )
            row.compose_add_child(
                RadioSet(
                    *(
                        RadioButton(
                            skill,
                            value=position == 0,
                            id=f"sync-conflict-{index}-keep-{position}",
                        )
                        for position, skill in enumerate(conflict.skills)
                    ),
                    id=f"sync-conflict-{index}-keep",
                )
            )
            row.compose_add_child(
                Button(
                    "Repair layer",
                    id=f"sync-conflict-{index}-repair",
                    classes="conflict-repair",
                )
            )
            section.compose_add_child(row)
        return section

    def _link_section(self, report: sync.SyncReport) -> Vertical:
        active = report.active_profile
        hint = (
            f"Re-applying profile {active} puts its links back in line with its "
            "profile.yaml."
            if active
            else "No profile is active; activate one to put its links in place."
        )
        section = self._section("Links", hint, "sync-link-section")
        section.compose_add_child(
            Static(
                "\n".join(problem.describe() for problem in report.links),
                id="sync-links",
            )
        )
        if active:
            section.compose_add_child(
                Button(f"Re-apply profile {active}", id="sync-relink")
            )
        return section

    def _invalid_section(self, report: sync.SyncReport) -> Vertical:
        section = self._section(
            "Invalid profiles",
            "These profile.yaml files do not load; fix them by hand "
            "('respec profile show <name>' explains the problem).",
            "sync-invalid-section",
        )
        section.compose_add_child(Static("\n".join(report.invalid), id="sync-invalid"))
        return section

    def _log(self, line: str, ok: bool) -> None:
        self.log_lines.append(Text(line, style=SUCCESS if ok else DANGER))
        log = self.query_one("#sync-log", Static)
        log.update(Text("\n").join(self.log_lines))
        log.display = True
        self.query_one("#sync-body", VerticalScroll).scroll_home(animate=False)

    def _log_error(self, error: RespecError) -> None:
        self._log("error: " + str(error).strip(), ok=False)

    # --- actions ------------------------------------------------------------

    @on(RadioSet.Changed)
    def _chosen(self, event: RadioSet.Changed) -> None:
        radio_id = event.radio_set.id or ""
        if not (radio_id.startswith("sync-unknown-") and radio_id.endswith("-choice")):
            return
        index = int(radio_id.split("-")[2])
        choice = (event.pressed.id or "").rsplit("-", 1)[1]
        self.choices[self.report.unknown[index].path] = choice
        self.query_one("#sync-resolve", Button).disabled = False

    @on(Button.Pressed, "#sync-resolve")
    async def _resolve(self) -> None:
        """Apply the chosen add or remove through ``respec adopt``'s full path."""
        choices = dict(self.choices)
        done: list[adopt.Resolution] = []
        try:
            adopt.adopt(
                self.respec_home,
                self.user_home,
                lambda entry: choices.get(entry.path),
                done=done,
            )
        except RespecError as error:
            for resolution in done:
                self._log(resolution.describe(), ok=True)
            self._log_error(error)
        else:
            for resolution in done:
                self._log(resolution.describe(), ok=True)
        await self.run_check()

    @on(Button.Pressed, ".conflict-repair")
    async def _repair(self, event: Button.Pressed) -> None:
        index = int((event.button.id or "").split("-")[2])
        conflict = self.report.conflicts[index]
        keep_set = self.query_one(f"#sync-conflict-{index}-keep", RadioSet)
        keep = conflict.skills[
            keep_set.pressed_index if keep_set.pressed_index >= 0 else 0
        ]
        try:
            change = layers.repair(
                self.respec_home,
                self.user_home,
                conflict.layer,
                keep=keep,
                profile_name=conflict.profile,
            )
        except RespecError as error:
            self._log_error(error)
        else:
            for line in _layer_change_lines(change):
                self._log(line, ok=True)
        await self.run_check()

    @on(Button.Pressed, "#sync-relink")
    async def _relink(self) -> None:
        try:
            result = sync.reapply(self.respec_home, self.user_home)
        except RespecError as error:
            self._log_error(error)
        else:
            self._log(
                f"Re-applied profile {result.profile!r}: "
                f"{_plural(len(result.installed), 'link', 'links')} in place",
                ok=True,
            )
        await self.run_check()

    @on(Button.Pressed, "#sync-recheck")
    async def action_recheck(self) -> None:
        await self.run_check()

    @on(Button.Pressed, "#sync-close")
    def action_close(self) -> None:
        self.dismiss(None)


class RespecApp(App[None]):
    """Profiles on the left, the status of every owned folder on the right."""

    TITLE = "respec"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS
    BINDINGS = [
        Binding("s", "sync", "Sync"),
        Binding("e", "edit", "Edit profile"),
        Binding("n", "new_profile", "New profile"),
        Binding("a", "adopt", "Resolve unknown"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, respec_home: Path, user_home: Path) -> None:
        super().__init__()
        self.respec_home = respec_home
        self.user_home = user_home
        self.selected: str | None = None
        self.active: str | None = None

    # Actions of the profile list; elsewhere their keys do nothing.
    LIST_ACTIONS = frozenset({"edit", "new_profile", "adopt", "refresh"})

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        if action in self.LIST_ACTIONS:
            return len(self.screen_stack) == 1
        if action == "sync":
            return not isinstance(self.screen, ModalScreen)
        return True

    # --- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("respec", id="title")
            yield Static("", id="active")
            yield Button(f"{SYNC_ICON} Sync", id="sync")
        with Horizontal(id="body"):
            with Vertical(id="sidebar") as sidebar:
                sidebar.border_title = "Profiles"
                yield ProfileList(id="profiles")
                yield Static(
                    "No profiles yet. Create one with New profile (n),\n"
                    "or respec profile new <name> --target <target>",
                    id="profiles-empty",
                )
                yield Button("Activate", id="activate", variant="primary")
                with Horizontal(id="profile-actions"):
                    yield Button("Edit", id="edit")
                    yield Button("New profile", id="new")
            with VerticalScroll(id="status") as status:
                status.border_title = "Target folders"
        yield Static("", id="feedback")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_view()
        self.query_one(ProfileList).focus()

    # --- rendering ----------------------------------------------------------

    async def refresh_view(self) -> None:
        """Re-read profiles and status from disk and redraw both panels."""
        try:
            report = switch.status(self.respec_home)
        except RespecError as error:
            report = {"active_profile": None, "targets": [], "folders": []}
            self.show_feedback(f"error: {error}", ok=False)
        self.active = report["active_profile"]
        if self.active is None:
            self.query_one("#active", Static).update("No active profile")
        else:
            self.query_one("#active", Static).update(
                Text.assemble(
                    ("● ", SUCCESS),
                    ("Active ", SECONDARY),
                    (self.active, "bold"),
                    (f"  {', '.join(report['targets'])}", MUTED),
                )
            )
        await self._render_profiles()
        await self._render_status(report["folders"])

    async def _render_profiles(self) -> None:
        rows = _profile_rows(self.respec_home)
        names = [name for name, _ in rows]
        if self.selected not in names:
            self.selected = self.active if self.active in names else None
        listing = self.query_one(ProfileList)
        await listing.clear()
        await listing.extend(
            ProfileItem(name, summary, name == self.active) for name, summary in rows
        )
        if self.selected is not None:
            listing.index = names.index(self.selected)
        elif names:
            listing.index = 0
        self.query_one("#profiles-empty").display = not rows
        listing.display = bool(rows)
        self._update_activate()

    async def _render_status(self, folders: list[dict[str, Any]]) -> None:
        panel = self.query_one("#status", VerticalScroll)
        await panel.remove_children()
        if not folders:
            await panel.mount(
                Static(
                    "respec owns no folders yet. Activating a profile takes over "
                    "its target folders after backing them up.",
                    id="status-empty",
                )
            )
            return
        await panel.mount_all(
            Static(_folder_text(f), id=_dom_id("folder", f["target"]), classes="folder")
            for f in folders
        )

    def _update_activate(self) -> None:
        self.query_one("#edit", Button).disabled = self.selected is None
        button = self.query_one("#activate", Button)
        button.disabled = self.selected is None or self.selected == self.active
        button.label = (
            f"Activate {self.selected}"
            if self.selected and self.selected != self.active
            else "Activate"
        )

    def show_feedback(self, message: str, ok: bool) -> None:
        feedback = self.query_one("#feedback", Static)
        feedback.update(message)
        feedback.set_class(ok, "-success")
        feedback.set_class(not ok, "-error")

    @on(ListView.Highlighted, "#profiles")
    def _highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, ProfileItem):
            self.selected = event.item.profile_name
            self._update_activate()

    # --- actions ------------------------------------------------------------

    @on(Button.Pressed, "#activate")
    def _activate_pressed(self) -> None:
        if self.selected is not None:
            self.activate(self.selected)

    async def action_refresh(self) -> None:
        await self.refresh_view()

    @on(Button.Pressed, "#edit")
    def action_edit(self) -> None:
        """Open the selected profile's skills, layers and sources."""
        if self.selected is None:
            self.show_feedback("Select a profile to edit first.", ok=False)
            return

        def closed(_: None) -> None:
            self.call_later(self.refresh_view)

        self.push_screen(
            ProfileScreen(self.respec_home, self.user_home, self.selected), closed
        )

    @on(Button.Pressed, "#new")
    def action_new_profile(self) -> None:
        def created(profile: profiles.Profile | None) -> None:
            if profile is None:
                return
            self.selected = profile.name
            self.show_feedback(
                f"Created profile {profile.name!r} at {profile.path}", ok=True
            )
            self.call_later(self.refresh_view)

        self.push_screen(NewProfileDialog(self.respec_home), created)

    @on(Button.Pressed, "#sync")
    def action_sync(self) -> None:
        """Check the setup and every profile now (manual; nothing is watched)."""

        def closed(_: None) -> None:
            self.call_later(self.refresh_view)

        self.push_screen(SyncScreen(self.respec_home, self.user_home), closed)

    def _active_now(self) -> str | None:
        """The active profile on disk: where ``add`` goes."""
        try:
            return load_state(self.respec_home).active_profile
        except RespecError:
            return None

    def activate(
        self,
        name: str,
        choices: dict[str, str] | None = None,
        owned_before: set[str] | None = None,
    ) -> None:
        """Switch to ``name``; unknown entries in the way open the adopt dialog.

        With ``choices`` (``{path: choice}`` from the dialog) the switch resolves
        them through :func:`respec.adopt.resolve`; ``add`` goes to the profile
        active now, the one being left. An entry without a choice (for example
        one that appeared after the dialog opened) blocks the switch before
        anything is resolved, and the dialog opens again. Entries that were
        already in a folder the switch took over are asked about right after.
        """
        previous = self._active_now()
        if owned_before is None:
            # Kept across a re-asked dialog, so every takeover is reported.
            try:
                owned_before = set(load_state(self.respec_home).owned)
            except RespecError as error:
                self._failed(error)
                return
        resolved: list[adopt.Resolution] = []
        handler: switch.UnknownHandler | None = None
        if choices is not None:
            decided = choices

            def handler(entries: list[unknown.Unknown]) -> None:
                if any(entry.path not in decided for entry in entries):
                    raise switch.UnknownEntries(name, entries)
                adopt.resolve(
                    self.respec_home,
                    entries,
                    lambda e: decided[e.path],
                    previous,
                    done=resolved,
                )

        try:
            result = switch.use(
                self.respec_home, self.user_home, name, on_unknown=handler
            )
        except switch.UnknownEntries as blocked:
            self._ask_then_activate(
                name, blocked.entries, previous, owned_before, again=choices is not None
            )
            return
        except RespecError as error:
            self._failed(error, resolved, self._new_backups(owned_before))
            return
        backups = self._new_backups(owned_before)
        self._switched(result, resolved, backups)
        self._ask_about_takeover(result, backups)

    def _new_backups(self, owned_before: set[str]) -> dict[str, str]:
        try:
            return switch.new_backups(self.respec_home, owned_before)
        except RespecError:
            return {}

    def _ask_then_activate(
        self,
        name: str,
        entries: list[unknown.Unknown],
        previous: str | None,
        owned_before: set[str],
        again: bool,
    ) -> None:
        def chosen(choices: dict[str, str] | None) -> None:
            if choices is None:
                self.show_feedback(
                    f"Switch to {name} cancelled; nothing changed.", ok=False
                )
                return
            self.activate(name, choices, owned_before)

        reason = (
            f"Before switching to {name}: these entries were not placed by "
            "respec and sit where it would install or remove a skill. "
            "Choose for each."
        )
        if again:
            reason = "The unknown entries changed; nothing was done yet. " + reason
        self.push_screen(AdoptDialog(entries, profile=previous, reason=reason), chosen)

    def _ask_about_takeover(
        self, result: switch.SwitchResult, backups: dict[str, str]
    ) -> None:
        """Ask about entries already in folders this switch took over."""
        try:
            entries = adopt.taken_over(self.respec_home, backups)
        except RespecError as error:
            self._failed(error)
            return
        if not entries:
            return
        profile = adopt.takeover_profile(result)

        def chosen(choices: dict[str, str] | None) -> None:
            if choices is None:
                self.show_feedback(
                    "Left them as they are; press a to resolve them later.", ok=False
                )
                return
            resolved: list[adopt.Resolution] = []
            try:
                adopt.resolve(
                    self.respec_home,
                    entries,
                    lambda e: choices.get(e.path),
                    profile,
                    done=resolved,
                )
                adopt.link_added(self.respec_home, self.user_home, resolved)
            except RespecError as error:
                self._failed(error, resolved)
                return
            self.show_feedback(
                _resolved_text(f"Resolved {len(resolved)} unknown entries:", resolved),
                ok=True,
            )
            self.call_later(self.refresh_view)

        folders = ", ".join(backups)
        reason = (
            f"respec took over {folders} and backed it up. These entries were "
            "already there. Choose for each."
        )
        self.push_screen(AdoptDialog(entries, profile=profile, reason=reason), chosen)

    def _switched(
        self,
        result: switch.SwitchResult,
        resolved: list[adopt.Resolution],
        backups: dict[str, str],
    ) -> None:
        parts = [f"Switched to {result.profile}: installed {len(result.installed)}"]
        if result.removed:
            parts.append(f"removed {len(result.removed)}")
        self.selected = result.profile
        lines = [
            *(resolution.describe() for resolution in resolved),
            *_backup_lines(backups),
        ]
        self.show_feedback("\n".join([", ".join(parts), *lines]), ok=True)
        self.call_later(self.refresh_view)

    def _failed(
        self,
        error: RespecError,
        resolved: Sequence[adopt.Resolution] = (),
        backups: dict[str, str] | None = None,
    ) -> None:
        done = [resolution.describe() for resolution in resolved]
        done += _backup_lines(backups or {})
        detail = " ".join(line.strip() for line in str(error).splitlines())
        self.show_feedback("\n".join([*done, f"error: {detail}"]), ok=False)
        self.call_later(self.refresh_view)

    def action_adopt(self) -> None:
        """Resolve unknown entries outside a switch (``respec adopt``)."""
        try:
            entries = adopt.unresolved(self.respec_home)
            active = load_state(self.respec_home).active_profile
        except RespecError as error:
            self._failed(error)
            return
        if not entries:
            self.show_feedback("No unknown entries.", ok=True)
            return

        def chosen(choices: dict[str, str] | None) -> None:
            if choices is None:
                self.show_feedback("Nothing resolved.", ok=False)
                return
            done: list[adopt.Resolution] = []
            try:
                result = adopt.adopt(
                    self.respec_home,
                    self.user_home,
                    lambda e: choices.get(e.path),
                    done=done,
                )
            except RespecError as error:
                self._failed(error, done)
                return
            self.show_feedback(
                _resolved_text(
                    f"Resolved {len(result.resolved)} unknown entries:",
                    result.resolved,
                ),
                ok=True,
            )
            self.call_later(self.refresh_view)

        self.push_screen(
            AdoptDialog(
                entries,
                profile=active,
                reason=(
                    "These entries in folders respec owns were not placed by "
                    "respec, or are edited copies. Choose for each."
                ),
            ),
            chosen,
        )
