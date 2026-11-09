"""Git sources: add skills from a repository, check and apply updates, and
install a whole profile from a repository once (modpack-style).

A source is written as ``owner/repo`` (resolved against ``RESPEC_GIT_BASE_URL``,
default ``https://github.com``) or as a git URL, optionally followed by
``#path`` inside the repository. The item's ``source`` record in
``profile.yaml`` keeps the repository as written, the path, the ref asked for
(none means the remote's default branch), the resolved commit and a digest of
the files as fetched, so later local edits can be detected.

Updates are explicit: :func:`check` only reads the remote; :func:`update`
replaces an item's folder with the newer upstream files. Items without a
source never change. Git runs as a subprocess with prompts disabled.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from respec import items, profiles
from respec.errors import RespecError

BASE_URL_ENV = "RESPEC_GIT_BASE_URL"
DEFAULT_BASE_URL = "https://github.com"
SHORTHAND = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCP_LIKE = re.compile(r"^[\w.-]+@[\w.-]+:")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Spec:
    """A parsed source argument."""

    repo: str  # as written by the user, recorded in profile.yaml
    url: str  # what git fetches from
    path: str | None = None


def base_url() -> str:
    return os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL


def is_git_spec(text: str) -> bool:
    repo = text.split("#", 1)[0]
    return bool(SHORTHAND.match(repo) or "://" in repo or SCP_LIKE.match(repo))


def repo_url(repo: str) -> str:
    if SHORTHAND.match(repo):
        return f"{base_url().rstrip('/')}/{repo}"
    return repo


def check_value(key: str, value: str | None) -> None:
    """Refuse a repo, ref or path that git could read as an option or escape."""
    if value is not None:
        problem = profiles.source_value_problem(key, value)
        if problem:
            raise RespecError(problem)


def parse_spec(text: str, ref: str | None = None) -> Spec:
    repo, _, path = text.partition("#")
    check_value("repo", repo)
    check_value("ref", ref)
    if not is_git_spec(repo):
        raise RespecError(
            f"{text!r} is neither 'owner/repo[#path]' nor a git URL nor a local folder"
        )
    path = path.rstrip("/") or None
    check_value("path", path)
    return Spec(repo=repo, url=repo_url(repo), path=path)


def repo_name(repo: str) -> str:
    name = repo.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return name.removesuffix(".git")


# --- git ---------------------------------------------------------------------


# Repository-local variables (``git rev-parse --local-env-vars``): inherited from
# a caller such as a git hook, they would point git at the caller's repository.
LOCAL_GIT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run git with prompts off and without the caller's repository variables.

    Callers pass ``--end-of-options`` before any user-controlled value.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in LOCAL_GIT_ENV
        and not key.startswith("GIT_CONFIG_KEY_")
        and not key.startswith("GIT_CONFIG_VALUE_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RespecError("git is not installed or not on PATH") from None
    if done.returncode != 0:
        raise RespecError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def remote_commit(url: str, ref: str | None, label: str) -> str:
    """The commit that ``ref`` (default: the remote's HEAD) points to."""
    if ref is not None and FULL_SHA.match(ref):
        return ref
    wanted = ref or "HEAD"
    try:
        output = _git("ls-remote", "--end-of-options", url, wanted)
    except RespecError as error:
        raise RespecError(f"cannot read {label}: {error}") from None
    found = dict(
        reversed(line.split("\t", 1)) for line in output.splitlines() if "\t" in line
    )
    for name in (
        wanted,
        f"refs/heads/{wanted}",
        f"refs/tags/{wanted}^{{}}",
        f"refs/tags/{wanted}",
    ):
        if name in found:
            return found[name]
    raise RespecError(f"{label} has no ref {wanted!r}")


@contextmanager
def checkout(url: str, ref: str | None, label: str) -> Iterator[tuple[Path, str]]:
    """Fetch ``ref`` of ``url`` into a temporary work tree; yield (tree, commit)."""
    with tempfile.TemporaryDirectory(prefix="respec-git-") as temporary:
        tree = Path(temporary).resolve() / "repo"
        try:
            _git("init", "-q", str(tree))
            if ref is not None and FULL_SHA.match(ref):
                _git("fetch", "-q", "--end-of-options", url, cwd=tree)
                _git("checkout", "-q", "--detach", ref, cwd=tree)
            else:
                _git(
                    "fetch",
                    "-q",
                    "--depth",
                    "1",
                    "--end-of-options",
                    url,
                    ref or "HEAD",
                    cwd=tree,
                )
                _git("checkout", "-q", "FETCH_HEAD", cwd=tree)
            commit = _git("rev-parse", "HEAD", cwd=tree).strip()
        except RespecError as error:
            raise RespecError(f"cannot fetch {label}: {error}") from None
        shutil.rmtree(tree / ".git")
        yield tree, commit


def inside(tree: Path, path: str | None) -> Path:
    """``tree / path``, refusing anything that resolves outside ``tree``."""
    if path is None:
        return tree
    check_value("path", path)
    root = tree.resolve()
    target = (tree / path).resolve()
    if target != root and root not in target.parents:
        raise RespecError(f"source path {path!r} must stay inside the repository")
    return tree / path


def _label(root: Path, entry: Path) -> str:
    """``entry`` relative to the repository root, for messages."""
    try:
        return (entry.parent.resolve() / entry.name).relative_to(root).as_posix()
    except ValueError:
        return entry.name


def _within(root: Path, entry: Path) -> None:
    target = entry.resolve()
    if target != root and root not in target.parents:
        raise RespecError(
            f"symlink {_label(root, entry)!r} points outside the repository; "
            "refusing to copy it"
        )


def copy_fetched(tree: Path, source: Path, destination: Path) -> None:
    """Copy ``source`` (inside the fetched ``tree``) to ``destination``.

    Symlinks are refused unless they resolve inside ``tree`` and do not point
    at a folder containing them, so a repository cannot make respec copy local
    files (such as ``~/.ssh`` keys) into a profile. Links that pass are copied
    as the files and folders they point to, keeping the profile self-contained.
    """
    root = tree.resolve()
    _within(root, source)
    for folder, dirs, files in os.walk(source):
        for name in dirs + files:
            entry = Path(folder) / name
            if not entry.is_symlink():
                continue
            _within(root, entry)
            target, parent = entry.resolve(), entry.parent.resolve()
            if target == parent or target in parent.parents:
                raise RespecError(
                    f"symlink {_label(root, entry)!r} points at a " "folder holding it"
                )
    shutil.copytree(source, destination)


# --- content -----------------------------------------------------------------


def digest(folder: Path) -> str:
    """A hash of the folder's tree: every entry's relative path and kind, file
    contents and executable bits, and symlink targets (symlinks are not
    followed), so added empty folders and symlinks count as edits too."""
    hasher = hashlib.sha256()
    entries: list[Path] = []
    for root, dirs, files in os.walk(folder):
        entries.extend(Path(root) / name for name in dirs + files)
    for entry in sorted(entries):
        relative = entry.relative_to(folder).as_posix()
        if entry.is_symlink():
            hasher.update(f"l\0{relative}\0{os.readlink(entry)}\0".encode())
        elif entry.is_dir():
            hasher.update(f"d\0{relative}\0".encode())
        else:
            executable = "x" if os.access(entry, os.X_OK) else "-"
            hasher.update(f"f\0{relative}\0{executable}\0".encode())
            hasher.update(hashlib.sha256(entry.read_bytes()).digest())
    return f"sha256:{hasher.hexdigest()}"


def _find_skills(tree: Path, spec: Spec) -> list[tuple[str, str | None]]:
    """Skills under the spec's path as (item name, path in the repository)."""
    base = inside(tree, spec.path)
    where = f"{spec.repo}#{spec.path}" if spec.path else spec.repo
    if not base.is_dir():
        raise RespecError(f"{where}: no such folder in the repository")
    if (base / items.SKILL_FILE).is_file():
        name = base.name if spec.path else repo_name(spec.repo)
        return [(name, spec.path)]
    candidates = [base] + ([base / "skills"] if (base / "skills").is_dir() else [])
    for folder in candidates:
        found = sorted(
            child
            for child in folder.iterdir()
            if child.is_dir() and (child / items.SKILL_FILE).is_file()
        )
        if found:
            return [(child.name, child.relative_to(tree).as_posix()) for child in found]
    raise RespecError(
        f"{where} has no {items.SKILL_FILE}, and no folder in it holds one"
    )


# --- add -----------------------------------------------------------------------


@dataclass
class SourceChange:
    """Result of adding items from a repository."""

    profile: str
    items: list[str]
    sources: dict[str, dict[str, str]]
    action: str = "add"
    active: bool = False
    linked: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def add(
    respec_home: Path,
    user_home: Path,
    text: str,
    profile_name: str | None = None,
    ref: str | None = None,
) -> SourceChange:
    """Fetch the skill(s) named by ``text`` into a profile and record sources."""
    spec = parse_spec(text, ref)
    name = items.resolve_profile_name(respec_home, profile_name)
    before = profiles.load_profile(respec_home, name)
    with checkout(spec.url, ref, spec.repo) as (tree, commit):
        found = _find_skills(tree, spec)
        clashes = [item for item, _ in found if item in before.skills]
        if clashes:
            raise RespecError(
                f"profile {name!r} already has {', '.join(map(repr, clashes))}; "
                "nothing was added"
            )
        added: list[str] = []
        sources: dict[str, dict[str, str]] = {}
        try:
            with tempfile.TemporaryDirectory(prefix="respec-stage-") as staging:
                for item, path in found:
                    staged = Path(staging) / item
                    copy_fetched(tree, inside(tree, path), staged)
                    source = profiles.Source(
                        repo=spec.repo,
                        path=path,
                        ref=ref,
                        commit=commit,
                        digest=digest(staged),
                    )
                    items.add_local(respec_home, name, staged, origin=source)
                    added.append(item)
                    sources[item] = source.to_dict()
        except (RespecError, OSError, shutil.Error):
            _forget(before, added)
            raise

    change = SourceChange(profile=name, items=added, sources=sources)
    items.refresh_active(respec_home, user_home, change, lambda: _forget(before, added))
    return change


def _forget(before: profiles.Profile, added: list[str]) -> None:
    profiles.save_profile(before)
    for item in added:
        shutil.rmtree(before.path / profiles.SKILLS_DIR / item, ignore_errors=True)


# --- update --------------------------------------------------------------------


@dataclass
class Row:
    item: str
    current: str | None
    latest: str | None = None
    update_available: bool | None = None
    modified: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def _sourced(profile: profiles.Profile, item: str | None) -> list[str]:
    if item is None:
        return [name for name, entry in profile.skills.items() if entry.source]
    if item not in profile.skills:
        known = ", ".join(profile.skills) or "none"
        raise RespecError(
            f"profile {profile.name!r} has no item {item!r} (items: {known})"
        )
    if profile.skills[item].source is None:
        raise RespecError(
            f"item {item!r} has no source; items without a source never change"
        )
    return [item]


def _modified(profile: profiles.Profile, item: str) -> bool:
    """Whether the item's files differ from what was fetched (unknown: True)."""
    source = profile.skills[item].source
    folder = profile.path / profiles.SKILLS_DIR / item
    return source is None or source.digest != digest(folder)


def _latest(source: profiles.Source, cache: dict[tuple[str, str | None], str]) -> str:
    key = (repo_url(source.repo), source.ref)
    if key not in cache:
        cache[key] = remote_commit(key[0], source.ref, source.repo)
    return cache[key]


def check(
    respec_home: Path, profile_name: str | None = None, item: str | None = None
) -> tuple[str, list[Row]]:
    """Report, per sourced item, whether a newer upstream commit exists."""
    profile = profiles.load_profile(
        respec_home, items.resolve_profile_name(respec_home, profile_name)
    )
    cache: dict[tuple[str, str | None], str] = {}
    rows: list[Row] = []
    for name in _sourced(profile, item):
        source = profile.skills[name].source
        assert source is not None
        row = Row(item=name, current=source.commit, modified=_modified(profile, name))
        try:
            row.latest = _latest(source, cache)
            row.update_available = row.latest != source.commit
        except RespecError as error:
            row.error = str(error)
        rows.append(row)
    return profile.name, rows


@dataclass
class UpdateResult:
    profile: str
    items: list[dict[str, object]] = field(default_factory=list)
    active: bool = False
    linked: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


Confirm = Callable[[str], bool]


def update(
    respec_home: Path,
    user_home: Path,
    profile_name: str | None = None,
    item: str | None = None,
    overwrite_edits: Confirm = lambda item: False,
) -> UpdateResult:
    """Apply newer upstream commits to sourced items.

    An item whose files were edited locally is replaced only when
    ``overwrite_edits(item)`` returns true; otherwise it is skipped.
    """
    profile = profiles.load_profile(
        respec_home, items.resolve_profile_name(respec_home, profile_name)
    )
    result = UpdateResult(profile=profile.name)
    skills = dict(profile.skills)
    replaced: list[tuple[Path, Path]] = []  # (live folder, kept old folder)
    cache: dict[tuple[str, str | None], str] = {}
    try:
        for name in _sourced(profile, item):
            source = skills[name].source
            assert source is not None
            row: dict[str, object] = {"item": name, "current": source.commit}
            result.items.append(row)
            try:
                latest = _latest(source, cache)
            except RespecError as error:
                row.update({"result": "error", "error": str(error)})
                continue
            row["latest"] = latest
            if latest == source.commit:
                row["result"] = "up-to-date"
                continue
            if _modified(profile, name) and not overwrite_edits(name):
                row["result"] = "skipped-local-edits"
                continue
            try:
                new_source = _replace(profile, name, source, replaced)
            except (RespecError, OSError, shutil.Error) as error:
                row.update({"result": "error", "error": str(error)})
                continue
            row.update({"result": "updated", "latest": new_source.commit})
            skills[name] = dataclasses.replace(skills[name], source=new_source)
        if not replaced:
            return result
        profiles.save_profile(dataclasses.replace(profile, skills=skills))
    except BaseException:
        _restore(profile, replaced)
        raise

    try:
        items.refresh_active(
            respec_home, user_home, result, lambda: _restore(profile, replaced)
        )
    finally:
        # A refused refresh has moved the old folders back already; after any
        # other failure the new files and profile.yaml agree, so drop the rest.
        for _, old in replaced:
            shutil.rmtree(old, ignore_errors=True)
    return result


def _replace(
    profile: profiles.Profile,
    item: str,
    source: profiles.Source,
    replaced: list[tuple[Path, Path]],
) -> profiles.Source:
    """Swap the item's folder for the upstream files; keep the old folder."""
    skills_dir = profile.path / profiles.SKILLS_DIR
    live = skills_dir / item
    incoming = skills_dir / f".{item}.incoming"
    old = skills_dir / f".{item}.old"
    for leftover in (incoming, old):
        shutil.rmtree(leftover, ignore_errors=True)
    with checkout(repo_url(source.repo), source.ref, source.repo) as (tree, commit):
        upstream = inside(tree, source.path)
        if not (upstream / items.SKILL_FILE).is_file():
            raise RespecError(
                f"{source.repo} at {commit[:12]} has no {items.SKILL_FILE} "
                f"in {source.path or 'its root'}"
            )
        copy_fetched(tree, upstream, incoming)
    os.replace(live, old)
    try:
        os.replace(incoming, live)
    except OSError as error:
        os.replace(old, live)
        shutil.rmtree(incoming, ignore_errors=True)
        raise RespecError(f"could not replace {live}: {error}") from None
    replaced.append((live, old))
    return dataclasses.replace(source, commit=commit, digest=digest(live))


def _restore(profile: profiles.Profile, replaced: list[tuple[Path, Path]]) -> None:
    profiles.save_profile(profile)
    for live, old in reversed(replaced):
        shutil.rmtree(live, ignore_errors=True)
        os.replace(old, live)


# --- profile install -----------------------------------------------------------


def install_profile(
    respec_home: Path,
    text: str,
    name: str | None = None,
    ref: str | None = None,
) -> profiles.Profile:
    """Copy a whole profile from a repository once; it is then owned locally."""
    spec = parse_spec(text, ref)
    name = name or (spec.path.rsplit("/", 1)[-1] if spec.path else repo_name(spec.repo))
    profiles.validate_name(name)
    destination = profiles.profiles_dir(respec_home) / name
    if os.path.lexists(destination):
        raise RespecError(
            f"profile {name!r} already exists at {destination}; "
            "choose another name with '--name'"
        )
    where = f"{spec.repo}#{spec.path}" if spec.path else spec.repo
    with checkout(spec.url, ref, spec.repo) as (tree, _commit):
        folder = inside(tree, spec.path)
        file = folder / profiles.PROFILE_FILE
        if not file.is_file():
            raise RespecError(f"{where} has no {profiles.PROFILE_FILE}")
        _within(tree.resolve(), file)
        try:
            data = yaml.safe_load(file.read_text("utf-8"))
        except yaml.YAMLError as error:
            raise profiles.ProfileError(file, [f"not valid YAML: {error}"]) from None
        # Validate against the fetched file so errors name it, then relocate.
        profile = dataclasses.replace(
            profiles.parse_profile(name, folder, data), path=destination
        )
        missing = [
            item
            for item in profile.skills
            if not (folder / profiles.SKILLS_DIR / item / items.SKILL_FILE).is_file()
        ]
        if missing:
            raise RespecError(
                f"{where} lists items without a {profiles.SKILLS_DIR}/<item>/"
                f"{items.SKILL_FILE}: {', '.join(missing)}"
            )
        try:
            (destination / profiles.SKILLS_DIR).mkdir(parents=True)
            for item in profile.skills:
                copy_fetched(
                    tree,
                    folder / profiles.SKILLS_DIR / item,
                    destination / profiles.SKILLS_DIR / item,
                )
            profiles.save_profile(profile)
        except RespecError:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        except (OSError, shutil.Error) as error:
            shutil.rmtree(destination, ignore_errors=True)
            raise RespecError(f"could not install profile {name!r}: {error}") from None
    return profile
