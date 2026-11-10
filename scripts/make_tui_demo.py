"""Regenerate the README's TUI demo: ``docs/assets/tui-demo.svg``.

Drives the real TUI headless (Textual's Pilot) against a throwaway home with
a few made-up profiles, takes an SVG screenshot after each step and joins the
screenshots into one animated SVG. Nothing outside the throwaway home is
touched.

    uv run python scripts/make_tui_demo.py [--frames <folder>]

``--frames`` also writes each frame as its own SVG, to look at one by one.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import re
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "docs" / "assets" / "tui-demo.svg"
SIZE = (100, 30)
# The home folder the pictures show in place of the throwaway one.
SHOWN_HOME = "/Users/you"

# What the demo home holds: profile -> (targets, skills).
PROFILES = {
    "coding": (
        ["claude-code", "agents", "oh-my-pi"],
        ["tdd", "code-review", "systematic-debugging", "clean-design"],
    ),
    "writing": (["claude-code"], ["deslop", "style-guide"]),
    "research": (["claude-code", "agents"], ["literature-review", "cite-sources"]),
}

# Each step: (keys to press, seconds the resulting screen stays visible).
STEPS: list[tuple[tuple[str, ...], float]] = [
    ((), 2.5),  # the profile list, "coding" active
    (("down",), 1.2),  # move to "research"
    (("down",), 1.5),  # move to "writing"
    (("enter",), 3.0),  # activate it
    (("e",), 2.5),  # open the profile editor
    (("down", "space"), 2.5),  # turn a skill off
    (("escape",), 1.5),  # back to the list
    (("s",), 3.5),  # Sync: check the setup
    (("escape",), 1.5),
]


def build_home(home: Path) -> None:
    """Create the made-up skills and profiles through respec itself."""
    from respec import items, profiles, switch

    library = home / "skills-library"
    respec_home = home / ".respec"
    for name, (targets, skills) in PROFILES.items():
        profiles.create_profile(respec_home, name, targets)
        for skill in skills:
            folder = library / skill
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: Demo skill.\n---\n\n# {skill}\n"
            )
            items.add(respec_home, home, folder, profile_name=name)
    switch.use(respec_home, home, "coding")
    shutil.rmtree(library)


async def record(home: Path) -> list[str]:
    from respec.tui import RespecApp

    frames: list[str] = []
    app = RespecApp(respec_home=home / ".respec", user_home=home)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        for keys, _ in STEPS:
            if keys:
                await pilot.press(*keys)
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.pause()
            frames.append(app.export_screenshot(title="respec"))
    return frames


TEXT = re.compile(r'(<text [^>]*textLength=")([0-9.]+)("[^>]*>)([^<]*)(</text>)')


def tidy(frame: str, home: Path) -> str:
    """Show the throwaway home as ``SHOWN_HOME``, as a real home would look.

    Each run of text carries its width, so the width is scaled with the text
    to keep every character on its column.
    """

    def swap(match: re.Match[str]) -> str:
        before = html.unescape(match.group(4))
        if str(home) not in before:
            return match.group(0)
        after = before.replace(str(home), SHOWN_HOME)
        width = float(match.group(2)) * len(after) / len(before)
        shown = html.escape(after).replace(" ", "&#160;")
        return f"{match.group(1)}{width:.1f}{match.group(3)}{shown}{match.group(5)}"

    return TEXT.sub(swap, frame)


def animate(frames: list[str]) -> str:
    """One SVG that shows the frames in turn, forever."""
    opening = re.match(r"<svg[^>]*>", frames[0])
    assert opening is not None
    view_box = re.search(r'viewBox="([^"]+)"', opening.group(0))
    assert view_box is not None
    total = sum(seconds for _, seconds in STEPS)
    rules, body, start = [], [], 0.0
    for index, (frame, (_, seconds)) in enumerate(zip(frames, STEPS)):
        begin = 100 * start / total
        end = 100 * (start + seconds) / total
        rules.append(
            f"@keyframes show{index} {{ 0%, {begin:.3f}% {{ visibility: hidden }} "
            f"{begin + 0.001:.3f}%, {end:.3f}% {{ visibility: visible }} "
            f"{min(end + 0.001, 100):.3f}%, 100% {{ visibility: hidden }} }}\n"
            f".frame{index} {{ visibility: hidden; "
            f"animation: show{index} {total}s linear infinite }}"
        )
        inner = frame[frame.index(">", frame.index("<svg")) + 1 :]
        inner = inner[: inner.rindex("</svg>")]
        body.append(f'<g class="frame{index}">{inner}</g>')
        start += seconds
    return (
        f'<svg viewBox="{view_box.group(1)}" xmlns="http://www.w3.org/2000/svg">\n'
        "<title>respec terminal UI: switching profiles, editing one, Sync</title>\n"
        f"<style>\n{chr(10).join(rules)}\n</style>\n" + "\n".join(body) + "\n</svg>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, help="also write each frame here")
    args = parser.parse_args()

    # A short path, so folder names fit on one line as they do in a real home.
    with tempfile.TemporaryDirectory(prefix="rsp-", dir="/tmp") as folder:
        home = Path(folder).resolve() / "home"
        home.mkdir()
        os.environ["RESPEC_USER_HOME"] = str(home)
        os.environ["RESPEC_HOME"] = str(home / ".respec")
        build_home(home)
        frames = [tidy(frame, home) for frame in asyncio.run(record(home))]
    assert not any("rsp-" in frame for frame in frames), "a temp path is showing"

    if args.frames:
        args.frames.mkdir(parents=True, exist_ok=True)
        for index, frame in enumerate(frames):
            (args.frames / f"frame-{index}.svg").write_text(frame)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(animate(frames))
    print(f"Wrote {OUTPUT.relative_to(REPO)} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
