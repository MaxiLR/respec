"""Copy and compare entries of skill folders: folders, files and symlinks.

Every helper treats a symlink as itself: its target is recorded, copied or
compared, never followed. ``.DS_Store`` files (written by the macOS Finder
when a folder is opened) are left out of fingerprints unless a caller asks
for an exact comparison.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Collection
from pathlib import Path

IGNORED_FILES = frozenset({".DS_Store"})


def real(path: Path | str) -> Path:
    """``path`` with its parent folders' symlinks resolved (not the entry itself)."""
    path = Path(path)
    return path.parent.resolve() / path.name


def digest(path: Path | str, ignore: Collection[str] = IGNORED_FILES) -> str:
    """Fingerprint of an entry's content: names, file bytes and link targets.

    Symlinks are recorded by target and never followed. Files named in
    ``ignore`` (by default ``.DS_Store``) are left out.
    """
    root = Path(path)
    hasher = hashlib.sha256()

    def add(relative: str, entry: Path) -> None:
        if entry.is_symlink():
            hasher.update(b"L\0" + relative.encode() + b"\0")
            hasher.update(os.readlink(entry).encode() + b"\0")
        elif entry.is_dir():
            hasher.update(b"D\0" + relative.encode() + b"\0")
            for child in sorted(entry.iterdir(), key=lambda c: c.name):
                if child.name in ignore:
                    continue
                add(f"{relative}/{child.name}", child)
        else:
            content = entry.read_bytes()
            hasher.update(b"F\0" + relative.encode() + b"\0")
            hasher.update(str(len(content)).encode() + b"\0" + content)

    add(".", root)
    return "sha256:" + hasher.hexdigest()


def modes(path: Path) -> list[tuple[str, int]]:
    """Permission bits of an entry and everything below it (links not followed)."""
    found = [(".", os.lstat(path).st_mode)]
    if path.is_dir() and not path.is_symlink():
        for root, subdirs, files in os.walk(path):
            for name in sorted(subdirs + files):
                child = os.path.join(root, name)
                found.append((os.path.relpath(child, path), os.lstat(child).st_mode))
    return sorted(found)


def same_content(
    left: Path, right: Path, ignore: Collection[str] = IGNORED_FILES
) -> bool:
    """Same names, file bytes and link targets (see :func:`digest`); False
    when either cannot be read."""
    try:
        return digest(left, ignore) == digest(right, ignore)
    except OSError:
        return False


def same_entry(left: Path, right: Path) -> bool:
    """:func:`same_content`, and the same permission bits throughout."""
    try:
        return digest(left) == digest(right) and modes(left) == modes(right)
    except OSError:
        return False


def copy_entry(source: Path, destination: Path) -> None:
    """Copy one entry as it is (links stay links), creating missing parents.

    On failure a partly copied folder is removed again, ``source`` is left as
    it was, and ``OSError`` is raised.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.is_symlink():
            os.symlink(os.readlink(source), destination)
        elif source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination)
    except (OSError, shutil.Error) as error:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination, ignore_errors=True)
        raise OSError(str(error)) from None
