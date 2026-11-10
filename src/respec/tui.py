"""Textual TUI: profile list, switching, status per target folder, adopt dialog.

A thin layer over the same core functions the CLI uses: profiles are read with
:mod:`respec.profiles`, switching and status come from :mod:`respec.switch`,
and unknown entries are resolved through :mod:`respec.adopt`. The TUI only
collects choices and renders results.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
)

from respec import adopt, profiles, switch, unknown
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
#activate { width: 100%; margin: 1 0; }

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

AdoptDialog { align: center middle; background: $page 70%; }
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
"""


def _dom_id(prefix: str, name: str) -> str:
    """A DOM id for a name that may hold '.' (escaped without collisions)."""
    return f"{prefix}-" + name.replace("_", "__").replace(".", "_-")


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


def _resolved_text(lead: str, resolved: Sequence[adopt.Resolution]) -> str:
    """``lead``, then what happened to each entry (the CLI's wording)."""
    return "\n".join([lead, *(resolution.describe() for resolution in resolved)])


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
                    replaced = (
                        ", an edited or replaced copy of a skill respec installed"
                        if entry.replaced
                        else ""
                    )
                    with Vertical(id=f"unknown-{index}", classes="unknown"):
                        yield Static(entry.path, classes="unknown-path")
                        yield Static(
                            f"{entry.kind} in {', '.join(entry.targets)}{replaced}",
                            classes="unknown-meta",
                        )
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


class RespecApp(App[None]):
    """Profiles on the left, the status of every owned folder on the right."""

    TITLE = "respec"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS
    BINDINGS = [
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

    # --- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("respec", id="title")
            yield Static("", id="active")
        with Horizontal(id="body"):
            with Vertical(id="sidebar") as sidebar:
                sidebar.border_title = "Profiles"
                yield ProfileList(id="profiles")
                yield Static(
                    "No profiles yet. Create one with\n"
                    "respec profile new <name> --target <target>",
                    id="profiles-empty",
                )
                yield Button("Activate", id="activate", variant="primary")
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

    def _active_now(self) -> str | None:
        """The active profile on disk: where ``add`` goes."""
        try:
            return load_state(self.respec_home).active_profile
        except RespecError:
            return None

    def activate(self, name: str, choices: dict[str, str] | None = None) -> None:
        """Switch to ``name``; unknown entries in the way open the adopt dialog.

        With ``choices`` (``{path: choice}`` from the dialog) the switch resolves
        them through :func:`respec.adopt.resolve`; ``add`` goes to the profile
        active now, the one being left. An entry without a choice (for example
        one that appeared after the dialog opened) blocks the switch before
        anything is resolved, and the dialog opens again. Entries that were
        already in a folder the switch took over are asked about right after.
        """
        previous = self._active_now()
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
                name, blocked.entries, previous, again=choices is not None
            )
            return
        except RespecError as error:
            self._failed(error, resolved)
            return
        self._switched(result, resolved)
        self._ask_about_takeover(result)

    def _ask_then_activate(
        self,
        name: str,
        entries: list[unknown.Unknown],
        previous: str | None,
        again: bool,
    ) -> None:
        def chosen(choices: dict[str, str] | None) -> None:
            if choices is None:
                self.show_feedback(
                    f"Switch to {name} cancelled; nothing changed.", ok=False
                )
                return
            self.activate(name, choices)

        reason = (
            f"Before switching to {name}: these entries were not placed by "
            "respec and sit where it would install or remove a skill. "
            "Choose for each."
        )
        if again:
            reason = "The unknown entries changed; nothing was done yet. " + reason
        self.push_screen(AdoptDialog(entries, profile=previous, reason=reason), chosen)

    def _ask_about_takeover(self, result: switch.SwitchResult) -> None:
        """Ask about entries already in folders this switch took over."""
        try:
            entries = adopt.taken_over(self.respec_home, result)
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

        folders = ", ".join(result.backups)
        reason = (
            f"respec took over {folders} and backed it up. These entries were "
            "already there. Choose for each."
        )
        self.push_screen(AdoptDialog(entries, profile=profile, reason=reason), chosen)

    def _switched(
        self, result: switch.SwitchResult, resolved: list[adopt.Resolution]
    ) -> None:
        parts = [f"Switched to {result.profile}: installed {len(result.installed)}"]
        if result.removed:
            parts.append(f"removed {len(result.removed)}")
        if result.backups:
            parts.append(f"backed up {', '.join(result.backups)}")
        self.selected = result.profile
        self.show_feedback(_resolved_text(", ".join(parts), resolved), ok=True)
        self.call_later(self.refresh_view)

    def _failed(
        self, error: RespecError, resolved: Sequence[adopt.Resolution] = ()
    ) -> None:
        done = [resolution.describe() for resolution in resolved]
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
