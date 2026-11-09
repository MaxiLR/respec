"""Typer command-line interface for respec."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, NoReturn, Optional

import typer

from respec import adopt as adopt_entries
from respec import items, layers, paths, profiles, switch, targets, unknown
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
def main(
    ctx: typer.Context,
    home: Annotated[
        Optional[Path],
        typer.Option(
            "--home",
            envvar=paths.USER_HOME_ENV,
            help="Home directory that target skill folders resolve against.",
            show_default="~",
        ),
    ] = None,
) -> None:
    user_home = paths.user_home(home)
    ctx.obj = Homes(respec_home=paths.respec_home(), user_home=user_home)
    if ctx.invoked_subcommand is None:
        _open_tui(ctx.obj)


def _open_tui(homes: Homes) -> None:
    from respec.tui import RespecApp

    RespecApp(respec_home=homes.respec_home, user_home=homes.user_home).run()


@app.command("tui")
def tui(ctx: typer.Context) -> None:
    """Open the terminal UI (same as running respec without a command)."""
    _open_tui(_homes(ctx))


def _homes(ctx: typer.Context) -> Homes:
    return ctx.find_root().obj


def _fail(error: RespecError) -> NoReturn:
    typer.echo(f"error: {error}", err=True)
    raise typer.Exit(code=1)


def _print_json(data: Any) -> None:
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


def _source_label(source: profiles.Source) -> str:
    label = source.repo
    if source.path:
        label += f"#{source.path}"
    if source.ref:
        label += f"@{source.ref}"
    return label


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
    """Ask what to do with one unknown entry."""
    replaced = ", replaced an item respec installed" if entry.replaced else ""
    typer.echo(
        f"Unknown entry {entry.path} ({entry.kind} in "
        f"{', '.join(entry.targets)}{replaced})"
    )
    destination = f"profile {profile!r}" if profile else "profile (needs -p)"
    while True:
        answer = typer.prompt(
            f"  add: add to {destination} / backup: back up and remove / "
            "keep: keep unmanaged [add/backup/keep]"
        ).strip()
        if answer in adopt_entries.CHOICES:
            return answer
        typer.echo(f"  please answer one of: {', '.join(adopt_entries.CHOICES)}")


def _report_resolution(resolution: adopt_entries.Resolution) -> None:
    entry = resolution.entry
    if resolution.choice == "add":
        typer.echo(f"Added {entry.path} to profile {resolution.profile!r}")
    elif resolution.choice == "backup":
        typer.echo(f"Backed up {entry.path} to {resolution.backup} and removed it")
    else:
        typer.echo(f"Kept {entry.path} unmanaged")


class UnknownChoice(str, Enum):
    add = "add"
    backup = "backup"
    keep = "keep"


@app.command("use")
def use(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Profile to activate.")],
    on_unknown: Annotated[
        Optional[UnknownChoice],
        typer.Option(
            "--unknown",
            help=(
                "What to do with every unknown entry in owned folders: add "
                "(to this profile), backup (and remove) or keep (unmanaged). "
                "Without it, a terminal asks per entry; other runs stop."
            ),
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Activate a profile: remove the previous profile's items, install this one."""
    homes = _homes(ctx)
    resolutions: list[adopt_entries.Resolution] = []
    decide: adopt_entries.Decide | None = None
    if on_unknown is not None:
        policy = on_unknown.value
        decide = lambda entry: policy  # noqa: E731
    elif _interactive() and not as_json:
        decide = lambda entry: _prompt_choice(entry, name)  # noqa: E731

    handler: switch.UnknownHandler | None = None
    if decide is not None:
        chosen = decide

        def handler(entries: list[unknown.Unknown]) -> None:
            resolutions.extend(
                adopt_entries.resolve(homes.respec_home, entries, chosen, name)
            )

    try:
        result = switch.use(
            homes.respec_home, homes.user_home, name, on_unknown=handler
        )
    except RespecError as error:
        for resolution in resolutions:
            _report_resolution(resolution)
        _fail(error)
    if as_json:
        _print_json(
            {
                "active_profile": result.profile,
                "previous_profile": result.previous,
                "backups": result.backups,
                "removed": [item.path for item in result.removed],
                "installed": [vars(item) for item in result.installed],
                "unknown": [resolution.to_dict() for resolution in resolutions],
            }
        )
        return
    for resolution in resolutions:
        _report_resolution(resolution)
    for target, backup in result.backups.items():
        typer.echo(f"Backed up {target} folder to {backup}")
    if result.removed:
        previous = f" of profile {result.previous!r}" if result.previous else ""
        typer.echo(f"Removed {len(result.removed)} items{previous}")
    typer.echo(
        f"Switched to profile {result.profile!r}: "
        f"installed {len(result.installed)} items"
    )


@app.command("status")
def status(ctx: typer.Context, as_json: JsonOption = False) -> None:
    """Show the active profile, its targets and the items in each folder."""
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
        if not folder["items"]:
            typer.echo("  (no managed items)")
        for item in folder["items"]:
            typer.echo(f"  {item['name']}  {item['mode']}")
        for entry in folder["unknown"]:
            any_unknown = True
            replaced = ", replaced a managed item" if entry["replaced"] else ""
            typer.echo(f"  {entry['name']}  unknown {entry['kind']}{replaced}")
        for entry in folder["unmanaged"]:
            typer.echo(f"  {entry['name']}  unmanaged (kept)")
    if any_unknown:
        typer.echo(
            "Unknown entries were not placed by respec. Resolve them with "
            "'respec adopt' (add to profile, back up and remove, or keep)."
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
ItemArgument = Annotated[str, typer.Argument(help="Item (skill) name.")]


def _report_change(change: items.ItemChange, as_json: bool) -> None:
    if as_json:
        _print_json(change.to_dict())
        return
    messages = {
        "add": f"Added {change.item!r} to profile {change.profile!r}",
        "remove": f"Removed {change.item!r} from profile {change.profile!r}",
        "enable": f"Enabled {change.item!r} in profile {change.profile!r}",
        "disable": f"Disabled {change.item!r} in profile {change.profile!r}",
    }
    typer.echo(messages[change.action])
    for path in change.linked:
        typer.echo(f"  linked {path}")
    for path in change.unlinked:
        typer.echo(f"  unlinked {path}")


@app.command("add")
def add(
    ctx: typer.Context,
    path: Annotated[
        Path, typer.Argument(help="Local skill folder (must contain SKILL.md).")
    ],
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Copy a local skill folder into a profile and enable it."""
    homes = _homes(ctx)
    try:
        change = items.add(homes.respec_home, homes.user_home, path, profile)
    except RespecError as error:
        _fail(error)
    _report_change(change, as_json)


@app.command("remove")
def remove(
    ctx: typer.Context,
    item: ItemArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove an item from a profile and delete its files."""
    homes = _homes(ctx)
    try:
        change = items.remove(homes.respec_home, homes.user_home, item, profile)
    except RespecError as error:
        _fail(error)
    _report_change(change, as_json)


def _set_enabled(
    ctx: typer.Context, item: str, enabled: bool, profile: str | None, as_json: bool
) -> None:
    homes = _homes(ctx)
    try:
        change = items.set_enabled(
            homes.respec_home, homes.user_home, item, enabled, profile
        )
    except RespecError as error:
        _fail(error)
    _report_change(change, as_json)


@app.command("enable")
def enable(
    ctx: typer.Context,
    item: ItemArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Enable an item; an active profile links it right away."""
    _set_enabled(ctx, item, True, profile, as_json)


@app.command("disable")
def disable(
    ctx: typer.Context,
    item: ItemArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Disable an item, keeping its files and metadata."""
    _set_enabled(ctx, item, False, profile, as_json)


layer_app = typer.Typer(
    help="Group a profile's items into layers.", no_args_is_help=True
)
app.add_typer(layer_app, name="layer")
LayerArgument = Annotated[str, typer.Argument(help="Layer name.")]


def _report_layer_change(change: layers.LayerChange, as_json: bool) -> None:
    if as_json:
        _print_json(change.to_dict())
        return
    where = f"layer {change.layer!r} of profile {change.profile!r}"
    messages = {
        "add": f"Added {where}",
        "rm": f"Removed {where}; its items stay in the profile",
        "add-item": f"Added {change.item!r} to {where}",
        "remove-item": f"Removed {change.item!r} from {where}",
        "use": f"Using {change.item!r} in {where}",
        "enable": f"Enabled the items of {where}",
        "disable": f"Disabled the items of {where}",
        "on": f"Turned on {where}",
        "off": f"Turned off {where}; its rules no longer apply",
    }
    typer.echo(messages[change.action])
    for path in change.linked:
        typer.echo(f"  linked {path}")
    for path in change.unlinked:
        typer.echo(f"  unlinked {path}")


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
    """List a profile's layers with their items."""
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
            item["name"] + ("" if item["enabled"] else " (disabled)")
            for item in row["items"]
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
    """Show a layer's rule, description and items."""
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
    if not row["items"]:
        typer.echo("Items: none")
        return
    typer.echo("Items:")
    for item in row["items"]:
        state = "enabled" if item["enabled"] else "disabled"
        typer.echo(f"  {item['name']}  {state}")


@layer_app.command("add")
def layer_add(
    ctx: typer.Context,
    name: LayerArgument,
    exclusive: Annotated[
        bool,
        typer.Option(
            "--exclusive/--additive",
            help="Exclusive: at most one enabled item. Additive: any number.",
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
    _report_layer_change(change, as_json)


@layer_app.command("rm")
def layer_rm(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove a custom layer; its items stay in the profile."""
    homes = _homes(ctx)
    try:
        change = layers.remove(homes.respec_home, name, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json)


def _layer_item_command(ctx, function, name, item, profile, as_json) -> None:
    homes = _homes(ctx)
    try:
        change = function(homes.respec_home, homes.user_home, name, item, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json)


@layer_app.command("use")
def layer_use(
    ctx: typer.Context,
    name: LayerArgument,
    item: ItemArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Enable an item in a layer (adding it); exclusive layers disable the rest."""
    _layer_item_command(ctx, layers.use, name, item, profile, as_json)


@layer_app.command("add-item")
def layer_add_item(
    ctx: typer.Context,
    name: LayerArgument,
    item: ItemArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Add an item to a layer, keeping an exclusive layer's current choice."""
    _layer_item_command(ctx, layers.add_item, name, item, profile, as_json)


@layer_app.command("remove-item")
def layer_remove_item(
    ctx: typer.Context,
    name: LayerArgument,
    item: ItemArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Take an item out of a layer; it stays in the profile."""
    _layer_item_command(ctx, layers.remove_item, name, item, profile, as_json)


def _layer_flag_command(ctx, function, name, value, profile, as_json) -> None:
    homes = _homes(ctx)
    try:
        change = function(homes.respec_home, homes.user_home, name, value, profile)
    except RespecError as error:
        _fail(error)
    _report_layer_change(change, as_json)


@layer_app.command("enable")
def layer_enable(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Enable every item of a layer."""
    _layer_flag_command(ctx, layers.set_enabled, name, True, profile, as_json)


@layer_app.command("disable")
def layer_disable(
    ctx: typer.Context,
    name: LayerArgument,
    profile: ProfileOption = None,
    as_json: JsonOption = False,
) -> None:
    """Disable every item of a layer, keeping their files."""
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
    """Turn a layer off: its items become plain additive items."""
    _layer_flag_command(ctx, layers.set_active, name, False, profile, as_json)


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
            "--add", help="Add this entry (name or path) to the profile. Repeatable."
        ),
    ] = [],
    backup_entries: Annotated[
        list[str],
        typer.Option(
            "--backup", help="Back up and remove this entry (name or path). Repeatable."
        ),
    ] = [],
    keep_entries: Annotated[
        list[str],
        typer.Option(
            "--keep", help="Keep this entry (name or path) unmanaged. Repeatable."
        ),
    ] = [],
    all_choice: Annotated[
        Optional[UnknownChoice],
        typer.Option(
            "--all",
            help="Choice for every entry not named by --add, --backup or --keep.",
            show_default=False,
        ),
    ] = None,
    profile: Annotated[
        Optional[str],
        typer.Option(
            "--profile",
            "-p",
            help="Profile that --add copies into (default: the active profile).",
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Resolve unknown entries in folders respec owns.

    Without choices, a terminal asks per entry; other runs only list them.
    """
    homes = _homes(ctx)
    try:
        entries = adopt_entries.find(homes.respec_home)
        chosen: dict[str, str] = {}
        for choice, selectors in (
            ("add", add_entries),
            ("backup", backup_entries),
            ("keep", keep_entries),
        ):
            for selector in selectors:
                matches = [e for e in entries if _selector_matches(selector, e)]
                if not matches:
                    raise RespecError(f"no unknown entry matches {selector!r}")
                for entry in matches:
                    if chosen.get(entry.path, choice) != choice:
                        raise RespecError(f"{entry.path} was given two choices")
                    chosen[entry.path] = choice
        prompt = _interactive() and not as_json
        label = profile or load_state(homes.respec_home).active_profile

        def decide(entry: unknown.Unknown) -> str | None:
            if entry.path in chosen:
                return chosen[entry.path]
            if all_choice is not None:
                return all_choice.value
            return _prompt_choice(entry, label) if prompt else None

        result = adopt_entries.adopt(
            homes.respec_home, homes.user_home, decide, profile
        )
    except RespecError as error:
        _fail(error)
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
            typer.echo(f"  {entry.path}  ({entry.kind})")
        typer.echo("Choose with --add, --backup or --keep <name>, or --all <choice>.")
    elif not result.resolved:
        typer.echo("No unknown entries.")
