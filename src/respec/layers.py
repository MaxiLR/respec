"""Layers: named groups of items inside one profile.

A layer only decides which items are enabled; it never changes where items are
installed. Built-in layers (``design-principles`` and ``output-style``) are
exclusive and cannot be removed, only turned off. Custom layers carry their own
``exclusive`` flag and ``description``. An active exclusive layer keeps at most
one item enabled. A layer that is turned off keeps its member list, but its
rules lapse and its items behave as plain additive items.

Every change is written through :func:`respec.profiles.save_profile` and an
active profile is re-applied through the switching engine (via
:func:`respec.items.commit`), so the target folders and ``state.json`` follow.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from respec import items, profiles
from respec.errors import RespecError
from respec.state import load_state


@dataclass
class LayerChange:
    profile: str
    layer: str
    action: str
    item: str | None = None
    active: bool = False
    linked: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def _load(respec_home: Path, profile_name: str | None) -> profiles.Profile:
    return profiles.load_profile(
        respec_home, items.resolve_profile_name(respec_home, profile_name)
    )


def _layer(profile: profiles.Profile, name: str) -> profiles.Layer:
    if name not in profile.layers:
        known = ", ".join(profile.layers)
        raise RespecError(
            f"profile {profile.name!r} has no layer {name!r} (layers: {known})"
        )
    return profile.layers[name]


def _with_layer(
    profile: profiles.Profile, name: str, layer: profiles.Layer | None
) -> profiles.Profile:
    layers = dict(profile.layers)
    if layer is None:
        del layers[name]
    else:
        layers[name] = layer
    return dataclasses.replace(profile, layers=layers)


def _apply(
    respec_home: Path,
    user_home: Path,
    before: profiles.Profile,
    after: profiles.Profile,
    change: LayerChange,
) -> LayerChange:
    change.active = load_state(respec_home).active_profile == before.name
    if after != before:
        items.commit(respec_home, user_home, before, after, change)
    return change


def describe(layer_name: str, layer: profiles.Layer, profile: profiles.Profile):
    return {
        "name": layer_name,
        "profile": profile.name,
        "exclusive": layer.exclusive,
        "description": layer.description,
        "builtin": layer.builtin,
        "active": layer.active,
        "items": [
            {"name": item, "enabled": profile.skills[item].enabled}
            for item in layer.items
        ],
    }


def list_layers(respec_home: Path, profile_name: str | None = None) -> list[dict]:
    profile = _load(respec_home, profile_name)
    return [describe(name, layer, profile) for name, layer in profile.layers.items()]


def show(respec_home: Path, name: str, profile_name: str | None = None) -> dict:
    profile = _load(respec_home, profile_name)
    return describe(name, _layer(profile, name), profile)


def add(
    respec_home: Path,
    name: str,
    exclusive: bool,
    description: str,
    profile_name: str | None = None,
) -> LayerChange:
    """Create an empty custom layer; target folders are not touched."""
    profile = _load(respec_home, profile_name)
    if not profiles.NAME_PATTERN.match(name):
        raise RespecError(f"invalid layer name {name!r}: {profiles.NAME_RULE}")
    if name in profile.layers:
        raise RespecError(f"profile {profile.name!r} already has a layer {name!r}")
    layer = profiles.Layer(exclusive=exclusive, description=description)
    profiles.save_profile(_with_layer(profile, name, layer))
    return LayerChange(profile=profile.name, layer=name, action="add")


def remove(respec_home: Path, name: str, profile_name: str | None = None):
    """Delete a custom layer; its items stay in the profile unchanged."""
    profile = _load(respec_home, profile_name)
    if _layer(profile, name).builtin:
        raise RespecError(
            f"{name!r} is a built-in layer and cannot be removed; "
            f"turn it off with 'respec layer off {name}'"
        )
    profiles.save_profile(_with_layer(profile, name, None))
    return LayerChange(profile=profile.name, layer=name, action="rm")


def _check_accepts_items(name: str) -> None:
    if name == profiles.OUTPUT_STYLE:
        raise RespecError(profiles.OUTPUT_STYLE_UNSUPPORTED)


def _with_member(
    profile: profiles.Profile, name: str, item: str
) -> tuple[profiles.Profile, profiles.Layer]:
    """``profile`` with ``item`` listed in layer ``name`` (validated)."""
    layer = _layer(profile, name)
    _check_accepts_items(name)
    if item not in profile.skills:
        known = ", ".join(profile.skills) or "none"
        raise RespecError(
            f"profile {profile.name!r} has no item {item!r} (items: {known})"
        )
    current = profile.layer_of(item)
    if current == name:
        return profile, layer
    if current is not None:
        raise RespecError(
            f"{item!r} is already in layer {current!r}; an item belongs to at most "
            f"one layer (remove it with 'respec layer remove-item {current} {item}')"
        )
    layer = dataclasses.replace(layer, items=layer.items + (item,))
    return _with_layer(profile, name, layer), layer


def add_item(
    respec_home: Path,
    user_home: Path,
    name: str,
    item: str,
    profile_name: str | None = None,
) -> LayerChange:
    """List ``item`` in a layer without changing the layer's current choice.

    In an active exclusive layer that already has an enabled item, the added
    item is disabled; choose it with ``respec layer use``.
    """
    before = _load(respec_home, profile_name)
    after, layer = _with_member(before, name, item)
    if layer.exclusive and layer.active:
        others = [
            other
            for other in layer.items
            if other != item and after.skills[other].enabled
        ]
        if others and after.skills[item].enabled:
            after = profiles.with_enabled(after, [item], False)
    change = LayerChange(profile=before.name, layer=name, action="add-item", item=item)
    return _apply(respec_home, user_home, before, after, change)


def remove_item(
    respec_home: Path,
    user_home: Path,
    name: str,
    item: str,
    profile_name: str | None = None,
) -> LayerChange:
    """Take ``item`` out of a layer; it stays in the profile as a plain item."""
    before = _load(respec_home, profile_name)
    layer = _layer(before, name)
    if item not in layer.items:
        raise RespecError(f"layer {name!r} does not list {item!r}")
    layer = dataclasses.replace(
        layer, items=tuple(member for member in layer.items if member != item)
    )
    after = _with_layer(before, name, layer)
    change = LayerChange(
        profile=before.name, layer=name, action="remove-item", item=item
    )
    return _apply(respec_home, user_home, before, after, change)


def use(
    respec_home: Path,
    user_home: Path,
    name: str,
    item: str,
    profile_name: str | None = None,
) -> LayerChange:
    """Enable ``item`` in a layer (adding it first if needed).

    In an active exclusive layer every other item of the layer is disabled.
    """
    before = _load(respec_home, profile_name)
    after, _ = _with_member(before, name, item)
    after = profiles.with_enabled(after, [item], True)
    change = LayerChange(profile=before.name, layer=name, action="use", item=item)
    return _apply(respec_home, user_home, before, after, change)


def set_enabled(
    respec_home: Path,
    user_home: Path,
    name: str,
    enabled: bool,
    profile_name: str | None = None,
) -> LayerChange:
    """Enable or disable every item of a layer as a group."""
    before = _load(respec_home, profile_name)
    layer = _layer(before, name)
    if enabled and layer.exclusive and layer.active and len(layer.items) > 1:
        raise RespecError(
            f"layer {name!r} is exclusive; choose one item with "
            f"'respec layer use {name} <item>'"
        )
    after = profiles.with_enabled(before, list(layer.items), enabled)
    action = "enable" if enabled else "disable"
    change = LayerChange(profile=before.name, layer=name, action=action)
    return _apply(respec_home, user_home, before, after, change)


def set_active(
    respec_home: Path,
    user_home: Path,
    name: str,
    active: bool,
    profile_name: str | None = None,
) -> LayerChange:
    """Turn a layer's rules on or off; which items are enabled is unchanged."""
    before = _load(respec_home, profile_name)
    after = _with_layer(
        before, name, dataclasses.replace(_layer(before, name), active=active)
    )
    problems = profiles.exclusivity_problems(after)
    if problems:
        raise RespecError(
            f"cannot turn layer {name!r} on: {problems[0]} "
            "(disable the others first)"
        )
    change = LayerChange(
        profile=before.name, layer=name, action="on" if active else "off"
    )
    return _apply(respec_home, user_home, before, after, change)
