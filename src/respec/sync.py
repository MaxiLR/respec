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

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path

from respec import global_skills, profiles, switch, trees, unknown
from respec.errors import RespecError
from respec.state import State, load_state

MISSING = "missing"
BROKEN = "broken"
NOT_LINKED = "not linked"
NOT_ENABLED = "no longer enabled"


PROFILE = global_skills.PROFILE


@dataclass(frozen=True)
class LinkProblem:
    target: str
    skill: str
    path: str
    problem: str  # one of MISSING, BROKEN, NOT_LINKED, NOT_ENABLED
    # The active profile's folder of this skill, when it is enabled there but
    # the folder is gone: re-applying cannot work until it is restored or the
    # skill is disabled.
    folder_gone: str | None = None
    # Where the skill comes from: PROFILE, or global_skills.SHIPPED / GLOBAL.
    origin: str = PROFILE
    # For a global skill: the config.yaml that lists (or listed) it, and its
    # folder there when that folder is missing.
    config: str | None = None
    source_gone: str | None = None

    def describe(self) -> str:
        if self.problem == NOT_LINKED:
            what = {
                PROFILE: "is enabled in the active profile but not linked",
                global_skills.SHIPPED: "is a skill respec ships but is not linked",
                global_skills.GLOBAL: (
                    f"is a global skill listed in {self.config} but is not linked"
                ),
            }[self.origin]
        elif self.problem == NOT_ENABLED:
            what = {
                PROFILE: "is linked but no longer enabled in the active profile",
                global_skills.SHIPPED: "is linked but respec no longer ships it",
                global_skills.GLOBAL: (
                    "is linked but no longer listed as a global skill in "
                    f"{self.config}"
                ),
            }[self.origin]
        else:
            what = {MISSING: "is missing", BROKEN: "is a broken link"}[self.problem]
        text = f"{self.skill} ({self.target}) {what}: {self.path}"
        if self.folder_gone:
            text += f"\n  its skill folder {self.folder_gone} is gone"
        if self.source_gone:
            text += (
                f"\n  its folder {self.source_gone} is missing; add it there, or "
                f"take {self.skill!r} out of {self.config}"
            )
        return text


@dataclass
class SyncReport:
    active_profile: str | None = None
    unknown: list[unknown.Unknown] = field(default_factory=list)
    conflicts: list[profiles.LayerConflict] = field(default_factory=list)
    links: list[LinkProblem] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    @property
    def folders_gone(self) -> dict[str, str]:
        """Skills of the active profile whose folder is gone, with the folder."""
        return {
            problem.skill: problem.folder_gone
            for problem in self.links
            if problem.folder_gone is not None
        }

    @property
    def clean(self) -> bool:
        return not (self.unknown or self.conflicts or self.links or self.invalid)


def _link_problems(
    respec_home: Path,
    user_home: Path,
    active: profiles.Profile | None,
    state: State,
) -> list[LinkProblem]:
    problems: list[LinkProblem] = []
    for item in state.installed:
        path = Path(item.path)
        if not os.path.lexists(path):
            problems.append(LinkProblem(item.target, item.name, item.path, MISSING))
        elif item.mode == "symlink" and path.is_symlink() and not path.exists():
            problems.append(LinkProblem(item.target, item.name, item.path, BROKEN))
    if active is None:
        return problems
    gone = {
        skill: str(folder)
        for skill, entry in active.skills.items()
        if entry.enabled
        and not (folder := active.path / profiles.SKILLS_DIR / skill).is_dir()
    }
    config = str(global_skills.config_path(respec_home))
    lasting = global_skills.lasting_or_shipped(respec_home)
    recorded = {trees.real(item.path): item for item in state.installed}
    # What the switching engine would install for the active profile.
    expected = {
        trees.real(destination): (target, skill, source)
        for target, skill, source, destination in switch.plan(
            respec_home, user_home, active
        )
    }
    for key, (target, skill, source) in expected.items():
        if key not in recorded and not os.path.lexists(key):
            origin = lasting.get(skill, PROFILE)
            problems.append(
                LinkProblem(
                    target,
                    skill,
                    str(key),
                    NOT_LINKED,
                    origin=origin,
                    config=config if origin == global_skills.GLOBAL else None,
                    source_gone=(
                        str(source)
                        if origin == global_skills.GLOBAL and not source.is_dir()
                        else None
                    ),
                )
            )
    for key, item in recorded.items():
        if key not in expected and os.path.lexists(key):
            origin = global_skills.origin(respec_home, Path(item.path), item.name)
            problems.append(
                LinkProblem(
                    item.target,
                    item.name,
                    item.path,
                    NOT_ENABLED,
                    origin=origin,
                    config=config if origin == global_skills.GLOBAL else None,
                )
            )
    return [
        dataclasses.replace(
            problem,
            folder_gone=gone.get(problem.skill) if problem.origin == PROFILE else None,
        )
        for problem in problems
    ]


def check(respec_home: Path, user_home: Path) -> SyncReport:
    """Everything that needs a decision now; reads only."""
    state = load_state(respec_home)
    report = SyncReport(active_profile=state.active_profile)
    report.unknown = unknown.find_unknown(respec_home, state)
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
    report.links = _link_problems(respec_home, user_home, active, state)
    return report


def reapply(respec_home: Path, user_home: Path) -> switch.SwitchResult:
    """Re-apply the active profile, so its links match ``profile.yaml`` again."""
    active = load_state(respec_home).active_profile
    if active is None:
        raise RespecError(
            "no active profile to re-apply; activate one with 'respec use <profile>'"
        )
    return switch.use(respec_home, user_home, active, action="refresh")
