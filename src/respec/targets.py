"""Target registry loaded from the bundled ``targets.yaml`` data file."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Target:
    name: str
    display_name: str
    global_skills_dir: str

    def skills_dir(self, home: Path) -> Path:
        """Absolute skills folder for this target under ``home``."""
        raw = self.global_skills_dir
        if raw == "~" or raw.startswith("~/"):
            return home / raw[2:]
        return Path(raw)


@cache
def registry() -> dict[str, Target]:
    """All known targets keyed by name, in registry order."""
    text = resources.files("respec").joinpath("targets.yaml").read_text("utf-8")
    entries = yaml.safe_load(text)["targets"]
    return {entry["name"]: Target(**entry) for entry in entries}


def known_names() -> str:
    return ", ".join(sorted(registry()))
