"""Sync check: one manual look at the setup and every profile.

:func:`check` reads, and never changes anything. It collects:

- unknown entries, and edited or replaced copies of installed skills, in the
  folders respec owns (:func:`respec.adopt.unresolved`);
- exclusive layers with more than one enabled skill, in every profile
  (:func:`respec.profiles.exclusivity_conflicts`);
- links respec placed that are missing or broken, and skills the active
  profile enables that are not linked (or are linked but no longer enabled),
  as recorded in ``state.json``;
- profiles whose ``profile.yaml`` does not load.

Fixes go through the same core paths as the CLI: ``respec adopt``
(:func:`respec.adopt.adopt`), ``respec layer repair`` and re-applying the
active profile with the switching engine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from respec import adopt, profiles, switch, unknown
from respec.errors import RespecError
from respec.state import load_state

MISSING = "missing"
BROKEN = "broken"
NOT_LINKED = "not linked"
NOT_ENABLED = "no longer enabled"


@dataclass(frozen=True)
class LinkProblem:
    target: str
    skill: str
    path: str
    problem: str  # one of MISSING, BROKEN, NOT_LINKED, NOT_ENABLED

    def describe(self) -> str:
        what = {
            MISSING: "is missing",
            BROKEN: "is a broken link (its skill folder is gone)",
            NOT_LINKED: "is enabled in the active profile but not linked",
            NOT_ENABLED: "is linked but no longer enabled in the active profile",
        }[self.problem]
        return f"{self.skill} ({self.target}) {what}: {self.path}"


@dataclass
class SyncReport:
    active_profile: str | None = None
    unknown: list[unknown.Unknown] = field(default_factory=list)
    conflicts: list[profiles.LayerConflict] = field(default_factory=list)
    links: list[LinkProblem] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.unknown or self.conflicts or self.links or self.invalid)


def _link_problems(
    respec_home: Path, user_home: Path, active: profiles.Profile | None
) -> list[LinkProblem]:
    state = load_state(respec_home)
    problems: list[LinkProblem] = []
    for item in state.installed:
        path = Path(item.path)
        if not os.path.lexists(path):
            problems.append(LinkProblem(item.target, item.name, item.path, MISSING))
        elif item.mode == "symlink" and path.is_symlink() and not path.exists():
            problems.append(LinkProblem(item.target, item.name, item.path, BROKEN))
    if active is None:
        return problems
    recorded = {unknown.real(item.path): item for item in state.installed}
    # What the switching engine would install for the active profile.
    expected = {
        unknown.real(destination): (target, skill)
        for target, skill, _, destination in switch._plan(active, user_home)
    }
    for key, (target, skill) in expected.items():
        if key not in recorded and not os.path.lexists(key):
            problems.append(LinkProblem(target, skill, str(key), NOT_LINKED))
    for key, item in recorded.items():
        if key not in expected and os.path.lexists(key):
            problems.append(LinkProblem(item.target, item.name, item.path, NOT_ENABLED))
    return problems


def check(respec_home: Path, user_home: Path) -> SyncReport:
    """Everything that needs a decision now; reads only."""
    state = load_state(respec_home)
    report = SyncReport(active_profile=state.active_profile)
    report.unknown = adopt.unresolved(respec_home)
    active: profiles.Profile | None = None
    for name in profiles.list_profile_names(respec_home):
        try:
            profile = profiles.load_profile(respec_home, name)
        except RespecError as error:
            detail = " ".join(line.strip() for line in str(error).splitlines())
            report.invalid.append(f"profile {name!r}: {detail}")
            continue
        report.conflicts.extend(profiles.exclusivity_conflicts(profile))
        if name == state.active_profile:
            active = profile
    report.links = _link_problems(respec_home, user_home, active)
    return report


def reapply(respec_home: Path, user_home: Path) -> switch.SwitchResult:
    """Re-apply the active profile, so its links match ``profile.yaml`` again."""
    active = load_state(respec_home).active_profile
    if active is None:
        raise RespecError(
            "no active profile to re-apply; activate one with 'respec use <profile>'"
        )
    return switch.use(respec_home, user_home, active, action="refresh")
