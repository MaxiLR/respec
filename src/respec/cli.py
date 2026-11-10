"""Typer command-line interface for respec."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, NoReturn, Optional

import click
import typer

from respec import adopt as adopt_entries
from respec import items, layers, messages, paths, profiles, sources, switch, targets
from respec import unknown
from respec import restore as restore_backups
from respec.errors import RespecError
from respec.state import load_state

app = typer.Typer(
    help="Switchable global profiles of agent skills. Without a command, opens the TUI.",
    pretty_exceptions_enable=False,
)
profile_app = typer.Typer(help="Create and inspect profiles.", no_args_is_help=True)
app.add_typer(profile_app, name="profile")

JsonOption = Annotated[
    bool, typer.Option("--json", help="Print machine-readable JSON.")
]


@dataclass(frozen=True)
class Homes:
    respec_home: Path
    user_home: Path


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    ctx.obj = Homes(respec_home=paths.respec_home(), user_home=paths.user_home())
    profiles.take_warnings()  # start clean; one process may run several commands
    _failure.clear()
    ctx.call_on_close(_print_warnings)
    if ctx.invoked_subcommand is None:
        if not _interactive():
            # No terminal (pipe, script, CI): print help instead of the TUI.
            typer.echo(ctx.get_help())
            raise typer.Exit()
        _open_tui(ctx.obj)


def _open_tui(homes: Homes) -> None:
    if not _interactive():
        typer.echo(
            "error: the TUI needs a terminal (stdin and stdout must be a TTY); "
            "use the respec commands instead (see 'respec --help')",
            err=True,
        )
        raise typer.Exit(code=1)
    from respec.tui import RespecApp

    RespecApp(respec_home=homes.respec_home, user_home=homes.user_home).run()


@app.command("tui")
def tui(ctx: typer.Context) -> None:
    """Open the terminal UI (same as running respec without a command)."""
    _open_tui(_homes(ctx))


def _homes(ctx: typer.Context) -> Homes:
    return ctx.find_root().obj


# Error text already printed by _fail; conflicts it explains are not repeated.
_failure: list[str] = []


def _print_warnings() -> None:
    """Print the layer conflicts of every profile the command read, as left."""
    explained = "\n".join(_failure)
    _failure.clear()
    for conflict in profiles.take_warnings():
        if conflict.message not in explained:
            typer.echo(f"warning: {conflict.message}", err=True)


def _fail(error: RespecError) -> NoReturn:
    _failure.append(str(error))
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(code=1)


def _print_json(data: Any) -> None:
    """Print ``data``; an object always carries one ``warnings`` list.

    Every warning is an object with a ``type`` and a ``message``:

    - ``layer-conflict``: an exclusive layer of a profile the command read has
      several enabled skills, as the command left it (``profile``, ``layer``,
      ``skills``, ``fix``);
    - ``unknown-entry``: an entry respec did not place, or an edited or
      replaced copy, in a folder it owns (``name``, ``path``, ``kind``,
      ``targets``, ``replaced``), passed in by the command as ``warnings``.
    """
    if isinstance(data, dict):
        layer_conflicts = [
            {"type": "layer-conflict", **conflict.to_dict()}
            for conflict in profiles.peek_warnings()
        ]
        data = {**data, "warnings": layer_conflicts + list(data.get("warnings", []))}
    typer.echo(json.dumps(data, indent=2))


@profile_app.command("new")
def profile_new(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile name.")],
    target: Annotated[
        list[str],
        typer.Option(
            "--target",
            "-t",
            help="Target to apply the profile to (repeatable).",
        ),
    ],
    as_json: JsonOption = False,
) -> None:
    """Create an empty profile for the given targets."""
    homes = _homes(ctx)
    try:
        profile = profiles.create_profile(homes.respec_home, name, target)
    except RespecError as error:
        _fail(error)
    if as_json:
        _print_json({"name": profile.name, "path": str(profile.path)})
    else:
        typer.echo(f"Created profile {profile.name!r} at {profile.path}")


def _profile_summary(profile: profiles.Profile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "targets": list(profile.targets),
        "skills": len(profile.skills),
        "enabled": sum(entry.enabled for entry in profile.skills.values()),
    }


@profile_app.command("list")
def profile_list(ctx: typer.Context, as_json: JsonOption = False) -> None:
    """List profiles with their targets and skill counts."""
    homes = _homes(ctx)
    entries: list[dict[str, Any]] = []
    for name in profiles.list_profile_names(homes.respec_home):
        try:
            entries.append(
                _profile_summary(profiles.load_profile(homes.respec_home, name))
            )
        except RespecError as error:
            entries.append({"name": name, "error": str(error)})

    if as_json:
        _print_json({"profiles": entries})
        return
    if not entries:
        typer.echo(
            "No profiles yet. Create one with "
            "'respec profile new <name> --target <target>'."
        )
        return
    width = max(len(entry["name"]) for entry in entries)
    for entry in entries:
        if "error" in entry:
            problem = entry["error"].splitlines()[-1].strip(" -")
            detail = f"invalid: {problem} (see 'respec profile show {entry['name']}')"
        else:
            detail = (
                f"{', '.join(entry['targets'])}  "
                f"{entry['skills']} skills ({entry['enabled']} enabled)"
            )
        typer.echo(f"{entry['name']:<{width}}  {detail}")


_source_label = messages.source_label


@profile_app.command("show")
def profile_show(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile name.")],
    as_json: JsonOption = False,
) -> None:
    """Show a profile's targets (with resolved folders) and skills."""
    homes = _homes(ctx)
    try:
        profile = profiles.load_profile(homes.respec_home, name)
    except RespecError as error:
        _fail(error)

    registry = targets.registry()
    target_rows = [
        {
            "name": target,
            "display_name": registry[target].display_name,
            "skills_dir": str(registry[target].skills_dir(homes.user_home)),
        }
        for target in profile.targets
    ]
    skill_rows = [
        {
            "name": skill,
            "enabled": entry.enabled,
            "source": entry.source.to_dict() if entry.source else None,
        }
        for skill, entry in profile.skills.items()
    ]
    if as_json:
        _print_json(
            {
                "name": profile.name,
                "path": str(profile.path),
                "targets": target_rows,
                "skills": skill_rows,
            }
        )
        return

    typer.echo(f"Profile {profile.name}  ({profile.path})")
    typer.echo("Targets:")
    width = max(len(row["name"]) for row in target_rows)
    for row in target_rows:
        typer.echo(f"  {row['name']:<{width}}  {row['skills_dir']}")
    if not skill_rows:
        typer.echo("Skills: none")
        return
    typer.echo("Skills:")
    width = max(len(row["name"]) for row in skill_rows)
    for skill, entry in profile.skills.items():
        state = "enabled " if entry.enabled else "disabled"
        origin = f"  {_source_label(entry.source)}" if entry.source else ""
        typer.echo(f"  {skill:<{width}}  {state}{origin}".rstrip())


def _interactive() -> bool:
    """Whether a person can answer prompts on this terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_choice(entry: unknown.Unknown, profile: str | None) -> str:
    """Ask what to do with one unknown entry; ``add`` goes to ``profile``."""
    typer.echo(f"Unknown entry {switch.describe(entry)} in {', '.join(entry.targets)}")
    available = adopt_entries.choices(profile, entry, paths.respec_home())
    if profile is not None and available == ("remove",):
        question = (
            f"  {entry.name!r} is the name of a skill respec ships or a global "
            "skill, so it cannot be added; remove: back up and remove (respec "
            "links its own skill there again) [remove]"
        )
    elif profile is None:
        question = (
            "  no active profile to add it to; remove: back up and remove [remove]"
        )
    else:
        question = (
            f"  add: add to profile {profile!r} / remove: back up and remove "
            "[add/remove]"
        )
    while True:
        answer = typer.prompt(question).strip()
        if answer in available:
            return answer
        typer.echo(
            f"  please answer{' one of' if len(available) > 1 else ''}: "
            f"{', '.join(available)}"
        )


def _report_resolution(resolution: adopt_entries.Resolution) -> None:
    typer.echo(resolution.describe())


def _warn_unresolved(homes: Homes) -> list[dict[str, Any]]:
    """Report unknown entries on stderr; return them as JSON warnings."""
    try:
        entries = adopt_entries.unresolved(homes.respec_home)
    except RespecError:
        return []
    warnings: list[dict[str, Any]] = []
    for entry in entries:
        what = (
            f"is an edited or replaced copy of skill {entry.name!r}"
            if entry.replaced
            else f"is a {entry.kind} respec did not place"
        )
        message = (
            f"{entry.path} {what}; run 'respec adopt' to add it to the active "
            "profile or remove it"
        )
        typer.echo(f"warning: {message}", err=True)
        warnings.append(
            {"type": "unknown-entry", **entry.to_dict(), "message": message}
        )
    return warnings


# Ctrl-C or the end of input at a prompt (typer and click raise their own).
PROMPT_ABORTED = (typer.Abort, click.exceptions.Abort)


class UnknownChoice(str, Enum):
    add = "add"
    remove = "remove"


def _fail_after(
    resolutions: list[adopt_entries.Resolution], error: RespecError, as_json: bool
) -> NoReturn:
    """Fail, still reporting every resolution that was already applied."""
    if as_json:
        _print_json(
            {
                "resolved": [resolution.to_dict() for resolution in resolutions],
                "error": str(error),
            }
        )
        raise typer.Exit(code=1)
    for resolution in resolutions:
        _report_resolution(resolution)
    _fail(error)


@dataclass
class _SwitchRun:
    """Everything one ``respec use`` did, reported the same way however it ends:
    success, a refusal, a failed choice, an interrupted prompt or a link error.
    """

    homes: Homes
    name: str
    owned_before: set[str]
    resolutions: list[adopt_entries.Resolution] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)
    result: switch.SwitchResult | None = None
    errors: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    prompt_cut: bool = False

    def interrupted(self, what: str) -> None:
        self.prompt_cut = True
        self.notices.append(f"interrupted; {what}")

    def ask_about_takeover(self, decide: adopt_entries.Decide) -> None:
        """Resolve entries already in folders this switch took over first."""
        assert self.result is not None
        try:
            adopt_entries.resolve(
                self.homes.respec_home,
                adopt_entries.taken_over(self.homes.respec_home, self.backups()),
                decide,
                adopt_entries.takeover_profile(self.result),
                done=self.resolutions,
            )
        except PROMPT_ABORTED:
            self.interrupted("the remaining entries stay as they are")
        except RespecError as error:
            self.errors.append(str(error))

    def link(self) -> None:
        try:
            self.linked += adopt_entries.link_added(
                self.homes.respec_home, self.homes.user_home, self.resolutions
            ).linked
        except switch.LinkFailed as error:
            self.linked += error.linked
            self.errors.append(str(error))
        except RespecError as error:
            self.errors.append(str(error))

    def backups(self) -> dict[str, str]:
        """Folders taken over by this run (also when it failed), from state."""
        try:
            return switch.new_backups(self.homes.respec_home, self.owned_before)
        except RespecError as error:
            self.errors.append(str(error))
            return dict(self.result.backups) if self.result else {}

    def finish(self, as_json: bool) -> None:
        """Report everything, then exit 1 unless the switch and its choices
        all went through (an interrupted takeover prompt still exits 0)."""
        if self.prompt_cut and not as_json:
            typer.echo()  # end the interrupted prompt's line
        backups = self.backups()
        result = self.result
        if not as_json:
            for resolution in self.resolutions:
                _report_resolution(resolution)
            for path in self.linked:
                typer.echo(f"  linked {path}")
            for target, backup in backups.items():
                typer.echo(f"Backed up {target} folder to {backup}")
            if result is not None:
                if result.removed:
                    left = f" of profile {result.previous!r}" if result.previous else ""
                    typer.echo(f"Removed {len(result.removed)} skills{left}")
                typer.echo(
                    f"Switched to profile {result.profile!r}: "
                    f"installed {len(result.installed)} skills"
                )
        for error in self.errors:
            _failure.append(error)
            typer.echo(f"error: {error}", err=True)
        for notice in self.notices:
            typer.echo(f"warning: {notice}", err=True)
        warnings = _warn_unresolved(self.homes)
        if as_json:
            data: dict[str, Any] = {
                "active_profile": result.profile if result else None,
                "previous_profile": result.previous if result else None,
                "backups": backups,
                "removed": [item.path for item in result.removed] if result else [],
                "installed": (
                    [vars(item) for item in result.installed] if result else []
                ),
                "resolved": [resolution.to_dict() for resolution in self.resolutions],
                "linked": self.linked,
                "warnings": warnings,
            }
            if self.errors:
                data["error"] = "\n".join(self.errors)
            _print_json(data)
        if self.errors or result is None:
            raise typer.Exit(code=1)


@app.command("use")
def use(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile to activate.")],
    on_unknown: Annotated[
        Optional[UnknownChoice],
        typer.Option(
            "--unknown",
            help=(
                "What to do with unknown entries where this switch installs or "
                "removes a skill: add (to the profile active now) or remove "
                "(after a backup). Without it, a terminal asks per entry; "
                "other runs stop. On a terminal it also applies to entries "
                "already in a folder this switch takes over for the first "
                "time. Unknown entries elsewhere only warn."
            ),
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Activate a profile: remove the previous profile's skills, install this one."""
    homes = _homes(ctx)
    interactive = _interactive() and not as_json
    try:
        state = load_state(homes.respec_home)
    except RespecError as error:
        _fail(error)
    previous = state.active_profile
    run = _SwitchRun(homes, name, set(state.owned))
    decide: adopt_entries.Decide | None = None
    if on_unknown is not None:
        if on_unknown.value not in adopt_entries.choices(previous):
            _fail(
                RespecError(
                    "'--unknown add' adds to the profile active now, and no "
                    "profile is active; use '--unknown remove' instead. On a "
                    "terminal without '--unknown', entries found at the first "
                    "takeover can be added to the profile being activated."
                )
            )
        policy = on_unknown.value
        decide = lambda entry: policy  # noqa: E731
    elif interactive:
        decide = lambda entry: _prompt_choice(entry, previous)  # noqa: E731

    handler: switch.UnknownHandler | None = None
    if decide is not None:
        chosen = decide

        def handler(entries: list[unknown.Unknown]) -> None:
            adopt_entries.resolve(
                homes.respec_home, entries, chosen, previous, done=run.resolutions
            )

    try:
        run.result = switch.use(
            homes.respec_home, homes.user_home, name, on_unknown=handler
        )
    except PROMPT_ABORTED:
        run.interrupted(f"the switch to profile {name!r} did not happen")
    except switch.UnknownEntries as error:
        run.errors.append(
            f"{error}\nOr pass "
            f"'--unknown {'|'.join(adopt_entries.choices(previous))}' "
            "to 'respec use'."
        )
    except RespecError as error:
        run.errors.append(str(error))
    if run.result is not None and interactive:
        takeover = adopt_entries.takeover_profile(run.result)
        ask = decide if on_unknown is not None else None
        if ask is None:
            ask = lambda entry: _prompt_choice(entry, takeover)  # noqa: E731
        run.ask_about_takeover(ask)
    # Skills added to the profile active now (the one being left, when the
    # switch did not happen; the new one, for takeover entries) get linked.
    run.link()
    run.finish(as_json)


@app.command("status")
def status(ctx: typer.Context, as_json: JsonOption = False) -> None:
    """Show the active profile, its targets and the skills in each folder."""
    homes = _homes(ctx)
    try:
        report = switch.status(homes.respec_home)
    except RespecError as error:
        _fail(error)
    if as_json:
        _print_json(report)
        return
    if report["active_profile"] is None:
        typer.echo("No active profile. Activate one with 'respec use <profile>'.")
    else:
        typer.echo(f"Active profile: {report['active_profile']}")
        typer.echo(f"Targets: {', '.join(report['targets'])}")
    any_unknown = False
    for folder in report["folders"]:
        typer.echo(f"{folder['target']}  {folder['skills_dir']}")
        if folder["same_as"]:
            typer.echo(f"  (same folder as {folder['same_as']})")
            continue
        if not folder["skills"]:
            typer.echo("  (no managed skills)")
        for skill in folder["skills"]:
            typer.echo(f"  {skill['name']}  {skill['mode']}")
        for entry in folder["unknown"]:
            any_unknown = True
            replaced = ", replaced a managed skill" if entry["replaced"] else ""
            typer.echo(f"  {entry['name']}  unknown {entry['kind']}{replaced}")
    if any_unknown:
        typer.echo(
            "Unknown entries were not placed by respec. Resolve them with "
            "'respec adopt' (add to the active profile, or back up and remove)."
        )


ProfileOption = Annotated[
    Optional[str],
    typer.Option(
        "--profile",
        "-p",
        help="Profile to change (default: the active profile).",
        show_default=False,
    ),
]
SkillArgument = Annotated[str, typer.Argument(help="Skill name.")]


def _report_change(
    change: items.SkillChange, as_json: bool, warnings: list[dict[str, Any]]
) -> None:
    if as_json:
        _print_json({**change.to_dict(), "warnings": warnings})
        return
    for line in messages.skill_change(change):
        typer.echo(line)


RefOption = Annotated[
    Optional[str],
    typer.Option(
        "--ref",
        help="Branch, tag or commit to fetch (default: the remote's default branch).",
        show_default=False,
    ),
]


@app.command("add")
def add(
    ctx: typer.Context,
    source: Annotated[
        str,
        typer.Argument(
            help="Local skill folder (with SKILL.md), 'owner/repo[#path]' "
            "or a git URL[#path]. An existing local folder wins.",
            metavar="SOURCE",
        ),
    ],
    profile: ProfileOption = None,
    ref: RefOption = None,
    as_json: JsonOption = False,
) -> None:
    """Add a skill from a local folder or a git repository and enable it."""
    homes = _homes(ctx)
    try:
        local = items.user_path(source)
        from_git = not local.exists() and sources.is_git_spec(source)
        if from_git:
            sourced = sources.add(
                homes.respec_home, homes.user_home, source, profile, ref
            )
        elif ref is not None:
            raise RespecError("--ref only applies to git sources")
        else:
            change = items.add(homes.respec_home, homes.user_home, local, profile)
    except RespecError as error:
        _fail(error)
    warnings = _warn_unresolved(homes)
    if from_git:
        _report_sourced(sourced, as_json, warnings)
    else:
        _report_change(change, as_json, warnings)


def _report_sourced(
    change: sources.SourceChange, as_json: bool, warnings: list[dict[str, Any]]
) -> None:
    if as_json:
        _print_json({**change.to_dict(), "warnings": warnings})
        return
    for line in messages.sourced_change(change):
        typer.echo(line)


@app.command("remove")
def remove(
    ctx: typer.Context,
    skill: SkillArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove a skill from a profile and delete its files."""
    homes = _homes(ctx)
    try:
        change = items.remove(homes.respec_home, homes.user_home, skill, profile)
    except RespecError as error:
        _fail(error)
    _report_change(change, as_json, _warn_unresolved(homes))


def _set_enabled(
    ctx: typer.Context, skill: str, enabled: bool, profile: str | None, as_json: bool
) -> None:
    homes = _homes(ctx)
    try:
        change = items.set_enabled(
            homes.respec_home, homes.user_home, skill, enabled, profile
        )
    except RespecError as error:
        _fail(error)
    _report_change(change, as_json, _warn_unresolved(homes))


@app.command("enable")
def enable(
    ctx: typer.Context,
    skill: SkillArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Enable a skill; an active profile links it right away."""
    _set_enabled(ctx, skill, True, profile, as_json)


@app.command("disable")
def disable(
    ctx: typer.Context,
    skill: SkillArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Disable a skill, keeping its files and metadata."""
    _set_enabled(ctx, skill, False, profile, as_json)


layer_app = typer.Typer(
    help="Group a profile's skills into layers.", no_args_is_help=True
)
app.add_typer(layer_app, name="layer")
LayerArgument = Annotated[str, typer.Argument(help="Layer name.")]


def _report_layer_change(
    change: layers.LayerChange, as_json: bool, warnings: list[dict[str, Any]]
) -> None:
    if as_json:
        _print_json({**change.to_dict(), "warnings": warnings})
        return
    for line in messages.layer_change(change):
        typer.echo(line)


def _layer_kind(layer: dict[str, Any]) -> str:
    kind = "exclusive" if layer["exclusive"] else "additive"
    if layer["builtin"]:
        kind += ", built-in"
    if not layer["active"]:
        kind += ", off"
    return kind


@layer_app.command("list")
def layer_list(
    ctx: typer.Context, profile: ProfileOption = None, as_json: JsonOption = False
) -> None:
    """List a profile's layers with their skills."""
    homes = _homes(ctx)
    try:
        rows = layers.list_layers(homes.respec_home, profile)
    except RespecError as error:
        _fail(error)
    if as_json:
        _print_json({"layers": rows})
        return
    width = max(len(row["name"]) for row in rows)
    for row in rows:
        members = ", ".join(
            skill["name"] + ("" if skill["enabled"] else " (disabled)")
            for skill in row["skills"]
        )
        typer.echo(
            f"{row['name']:<{width}}  [{_layer_kind(row)}]  {members or '(empty)'}"
        )


@layer_app.command("show")
def layer_show(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show a layer's rule, description and skills."""
    homes = _homes(ctx)
    try:
        row = layers.show(homes.respec_home, name, profile)
    except RespecError as error:
        _fail(error)
    if as_json:
        _print_json(row)
        return
    typer.echo(f"Layer {row['name']}  [{_layer_kind(row)}]  profile {row['profile']}")
    typer.echo(f"  {row['description']}")
    if not row["skills"]:
        typer.echo("Skills: none")
        return
    typer.echo("Skills:")
    for skill in row["skills"]:
        state = "enabled" if skill["enabled"] else "disabled"
        typer.echo(f"  {skill['name']}  {state}")


@layer_app.command("add")
def layer_add(
    ctx: typer.Context,
    name: LayerArgument,
    exclusive: Annotated[
        bool,
        typer.Option(
            "--exclusive/--additive",
            help="Exclusive: at most one enabled skill. Additive: any number.",
        ),
    ],
    description: Annotated[
        str,
        typer.Option(
            "--description", "-d", help="What belongs in this layer (required)."
        ),
    ],
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Create a custom layer."""
    homes = _homes(ctx)
    try:
        change = layers.add(homes.respec_home, name, exclusive, description, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json, _warn_unresolved(homes))


@layer_app.command("rm")
def layer_rm(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove a custom layer; its skills stay in the profile."""
    homes = _homes(ctx)
    try:
        change = layers.remove(homes.respec_home, name, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json, _warn_unresolved(homes))


def _layer_skill_command(ctx, function, name, skill, profile, as_json) -> None:
    homes = _homes(ctx)
    try:
        change = function(homes.respec_home, homes.user_home, name, skill, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json, _warn_unresolved(homes))


@layer_app.command("use")
def layer_use(
    ctx: typer.Context,
    name: LayerArgument,
    skill: SkillArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Enable a skill in a layer (adding it); exclusive layers disable the rest."""
    _layer_skill_command(ctx, layers.use, name, skill, profile, as_json)


@layer_app.command("add-skill")
def layer_add_skill(
    ctx: typer.Context,
    name: LayerArgument,
    skill: SkillArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Add a skill to a layer, keeping an exclusive layer's current choice."""
    _layer_skill_command(ctx, layers.add_skill, name, skill, profile, as_json)


@layer_app.command("remove-skill")
def layer_remove_skill(
    ctx: typer.Context,
    name: LayerArgument,
    skill: SkillArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Take a skill out of a layer; it stays in the profile."""
    _layer_skill_command(ctx, layers.remove_skill, name, skill, profile, as_json)


def _layer_flag_command(ctx, function, name, value, profile, as_json) -> None:
    homes = _homes(ctx)
    try:
        change = function(homes.respec_home, homes.user_home, name, value, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json, _warn_unresolved(homes))


@layer_app.command("enable")
def layer_enable(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Enable every skill of a layer."""
    _layer_flag_command(ctx, layers.set_enabled, name, True, profile, as_json)


@layer_app.command("disable")
def layer_disable(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Disable every skill of a layer, keeping their files."""
    _layer_flag_command(ctx, layers.set_enabled, name, False, profile, as_json)


@layer_app.command("on")
def layer_on(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Turn a layer's rules back on."""
    _layer_flag_command(ctx, layers.set_active, name, True, profile, as_json)


@layer_app.command("off")
def layer_off(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Turn a layer off: its skills become plain additive skills."""
    _layer_flag_command(ctx, layers.set_active, name, False, profile, as_json)


def _prompt_keep(skills: list[str]) -> str:
    """Ask which enabled skill of a conflicted exclusive layer to keep."""
    typer.echo("Enabled skills:")
    for number, skill in enumerate(skills, start=1):
        typer.echo(f"  {number}. {skill}")
    while True:
        answer = typer.prompt("Skill to keep (name or number)", default=skills[0])
        answer = answer.strip()
        if answer in skills:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(skills):
            return skills[int(answer) - 1]
        typer.echo(f"  please answer one of: {', '.join(skills)}")


@layer_app.command("repair")
def layer_repair(
    ctx: typer.Context,
    name: LayerArgument,
    keep: Annotated[
        Optional[str],
        typer.Option(
            "--keep",
            help=(
                "Skill to keep enabled. Without it, a terminal asks; other runs "
                "keep the first listed skill."
            ),
            show_default=False,
        ),
    ] = None,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Fix an exclusive layer with several enabled skills: keep one, disable the rest."""
    homes = _homes(ctx)
    choose = _prompt_keep if _interactive() and not as_json else None
    try:
        change = layers.repair(
            homes.respec_home, homes.user_home, name, keep, choose, profile
        )
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json, _warn_unresolved(homes))


def _selector_matches(selector: str, entry: unknown.Unknown) -> bool:
    if selector == entry.name or selector == entry.path:
        return True
    return unknown.real(Path(selector).expanduser().absolute()) == unknown.real(
        entry.path
    )


@app.command("adopt")
def adopt(
    ctx: typer.Context,
    add_entries: Annotated[
        list[str],
        typer.Option(
            "--add",
            help="Add this entry (name or path) to the active profile. Repeatable.",
        ),
    ] = [],
    remove_entries: Annotated[
        list[str],
        typer.Option(
            "--remove",
            help="Back up and remove this entry (name or path). Repeatable.",
        ),
    ] = [],
    all_choice: Annotated[
        Optional[UnknownChoice],
        typer.Option(
            "--all",
            help="Choice for every entry not named by --add or --remove.",
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Resolve unknown entries in folders respec owns: add or remove each.

    Add copies an entry into the active profile (an edited copy of one of its
    skills replaces the profile's copy). Remove backs it up first. Without
    choices, a terminal asks per entry; other runs only list them.
    """
    homes = _homes(ctx)
    done: list[adopt_entries.Resolution] = []
    try:
        entries = adopt_entries.unresolved(homes.respec_home)
        chosen: dict[str, str] = {}
        for choice, selectors in (("add", add_entries), ("remove", remove_entries)):
            for selector in selectors:
                matches = [e for e in entries if _selector_matches(selector, e)]
                if not matches:
                    raise RespecError(f"no unknown entry matches {selector!r}")
                for entry in matches:
                    if chosen.get(entry.path, choice) != choice:
                        raise RespecError(f"{entry.path} was given two choices")
                    chosen[entry.path] = choice
        prompt = _interactive() and not as_json
        active = load_state(homes.respec_home).active_profile

        def decide(entry: unknown.Unknown) -> str | None:
            if entry.path in chosen:
                return chosen[entry.path]
            if all_choice is not None:
                return all_choice.value
            return _prompt_choice(entry, active) if prompt else None

        result = adopt_entries.adopt(
            homes.respec_home, homes.user_home, decide, done=done
        )
    except PROMPT_ABORTED:
        typer.echo()  # end the interrupted prompt's line
        for resolution in done:
            _report_resolution(resolution)
        typer.echo(
            "warning: interrupted; the remaining entries stay as they are. "
            "Run 'respec adopt' again to resolve them.",
            err=True,
        )
        return
    except RespecError as error:
        _fail_after(done, error, as_json)
    if as_json:
        _print_json(
            {
                "resolved": [r.to_dict() for r in result.resolved],
                "linked": result.linked,
                "unknown": [e.to_dict() for e in result.unknown],
            }
        )
        return
    for resolution in result.resolved:
        _report_resolution(resolution)
    for path in result.linked:
        typer.echo(f"  linked {path}")
    if result.unknown:
        typer.echo("Unknown entries left as they are:")
        for entry in result.unknown:
            typer.echo(f"  {switch.describe(entry)}")
        typer.echo("Choose with --add or --remove <name>, or --all add|remove.")
    elif not result.resolved:
        typer.echo("No unknown entries.")


@app.command("restore")
def restore(
    ctx: typer.Context,
    backup: Annotated[
        Optional[str],
        typer.Argument(
            help="Backup run to restore (default: each folder's takeover backup).",
            show_default=False,
        ),
    ] = None,
    list_only: Annotated[
        bool, typer.Option("--list", help="List available backups and stop.")
    ] = False,
    on_unknown: Annotated[
        Optional[UnknownChoice],
        typer.Option(
            "--unknown",
            help=(
                "What to do with every unknown entry the backup would overwrite: "
                "add (to the active profile) or remove (after a backup)."
            ),
            show_default=False,
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Back up entries the backup would overwrite, then replace them.",
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Put a backup back and release every folder respec owns."""
    homes = _homes(ctx)
    if list_only:
        try:
            found = restore_backups.list_backups(homes.respec_home)
        except RespecError as error:
            _fail(error)
        if as_json:
            _print_json([b.to_dict() for b in found])
            return
        if not found:
            typer.echo("No backups.")
        for entry in found:
            kind = f"takeover of {', '.join(entry.takeover)}" if entry.takeover else ""
            typer.echo(f"{entry.name}  {', '.join(entry.targets)}  {kind}".rstrip())
        return
    interactive = _interactive() and not as_json
    resolutions: list[adopt_entries.Resolution] = []
    try:
        profile = load_state(homes.respec_home).active_profile
    except RespecError as error:
        _fail(error)
    decide: adopt_entries.Decide | None = None
    if on_unknown is not None:
        policy = on_unknown.value
        decide = lambda entry: policy  # noqa: E731
    elif interactive and not overwrite:
        decide = lambda entry: _prompt_choice(entry, profile)  # noqa: E731

    handler: switch.UnknownHandler | None = None
    if decide is not None:
        chosen = decide

        def handler(entries: list[unknown.Unknown]) -> None:
            adopt_entries.resolve(
                homes.respec_home, entries, chosen, profile, done=resolutions
            )

    try:
        result = restore_backups.restore(
            homes.respec_home,
            homes.user_home,
            backup,
            on_unknown=handler,
            overwrite=overwrite,
        )
    except PROMPT_ABORTED:
        _fail_after(
            resolutions,
            RespecError("interrupted; nothing was restored"),
            as_json,
        )
    except RespecError as error:
        _fail_after(resolutions, error, as_json)
    if as_json:
        _print_json(
            {
                "backup": result.backup,
                "restored": result.restored,
                "removed": [item.path for item in result.removed],
                "overwritten": [r.to_dict() for r in result.set_aside],
                "unknown": [r.to_dict() for r in resolutions],
                "released": result.released,
                "skipped": result.skipped,
                "left": result.left,
            }
        )
        return
    for resolution in resolutions + result.set_aside:
        _report_resolution(resolution)
    if result.removed:
        typer.echo(f"Removed {len(result.removed)} respec skills")
    for target, source in result.restored.items():
        origin = source if source else "nothing (folder did not exist)"
        typer.echo(f"Restored {target} from {origin}")
    for path in result.skipped:
        typer.echo(f"Skipped {path}: respec's own skill, not restored")
    for path in result.left:
        typer.echo(f"Left {path} in place: hidden, not in the backup")
    typer.echo("respec released its folders; no profile is active.")


@app.command("update")
def update(
    ctx: typer.Context,
    skill: Annotated[
        Optional[str],
        typer.Argument(help="Skill to update (default: every sourced skill)."),
    ] = None,
    profile: ProfileOption = None,
    check_only: Annotated[
        bool,
        typer.Option("--check", help="Only report which skills have newer commits."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Overwrite local edits without asking."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Check for or apply newer upstream commits of sourced skills."""
    homes = _homes(ctx)
    if check_only:
        _update_check(homes, profile, skill, as_json)
        return

    def confirm(name: str) -> bool:
        if yes:
            return True
        if as_json:
            return False
        return typer.confirm(
            f"{name!r} has local edits that the update would overwrite. Overwrite?",
            default=False,
        )

    try:
        result = sources.update(
            homes.respec_home, homes.user_home, profile, skill, confirm
        )
    except RespecError as error:
        _fail(error)
    failed = any(row["result"] == "error" for row in result.skills)
    warnings = _warn_unresolved(homes)
    if as_json:
        _print_json({**result.to_dict(), "warnings": warnings})
    else:
        if not result.skills:
            typer.echo(f"Profile {result.profile!r} has no skills with a source.")
        for row in result.skills:
            typer.echo(_update_line(row))
        for path in result.linked:
            typer.echo(f"  linked {path}")
    if failed:
        raise typer.Exit(code=1)


_short = messages.short


def _update_line(row: dict[str, Any]) -> str:
    name = row["skill"]
    outcome = row["result"]
    if outcome == "updated":
        return f"{name}  updated {_short(row['current'])} -> {_short(row['latest'])}"
    if outcome == "up-to-date":
        return f"{name}  up to date"
    if outcome == "skipped-local-edits":
        return f"{name}  skipped: local edits kept (use --yes to overwrite)"
    return f"{name}  error: {row['error']}"


def _update_check(
    homes: Homes, profile: str | None, skill: str | None, as_json: bool
) -> None:
    try:
        name, rows = sources.check(homes.respec_home, profile, skill)
    except RespecError as error:
        _fail(error)
    if as_json:
        _print_json({"profile": name, "skills": [row.to_dict() for row in rows]})
    else:
        if not rows:
            typer.echo(f"Profile {name!r} has no skills with a source.")
        for row in rows:
            edits = "  (local edits)" if row.modified else ""
            if row.error:
                state = f"error: {row.error}"
            elif row.update_available:
                state = (
                    f"update available {_short(row.current)} -> {_short(row.latest)}"
                )
            else:
                state = "up to date"
            typer.echo(f"{row.skill}  {state}{edits}")
    if any(row.error for row in rows):
        raise typer.Exit(code=1)


@profile_app.command("install")
def profile_install(
    ctx: typer.Context,
    source: Annotated[
        str,
        typer.Argument(
            help="'owner/repo[#path]' or a git URL[#path] of a profile folder "
            "(with profile.yaml).",
            metavar="REPO",
        ),
    ],
    name: Annotated[
        Optional[str],
        typer.Option("--name", help="Profile name (default: the repo or folder name)."),
    ] = None,
    ref: RefOption = None,
    as_json: JsonOption = False,
) -> None:
    """Copy a whole profile from a repository once; it is then owned locally."""
    homes = _homes(ctx)
    try:
        installed = sources.install_profile(homes.respec_home, source, name, ref)
    except RespecError as error:
        _fail(error)
    if as_json:
        _print_json({"name": installed.name, "path": str(installed.path)})
    else:
        typer.echo(
            f"Installed profile {installed.name!r} at {installed.path} "
            f"({len(installed.skills)} skills)"
        )
