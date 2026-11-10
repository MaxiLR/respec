"""Sources: add skills from a repository or a folder, check and apply updates,
and install a whole profile from a repository or a folder, which the profile
then remembers as its own source (see :func:`reference`).

A source is written as ``owner/repo`` (resolved against ``RESPEC_GIT_BASE_URL``,
default ``https://github.com``) or as a git URL, optionally followed by
``#path`` inside the repository. The item's ``source`` record in
``profile.yaml`` keeps the repository as written, the path, the ref asked for
(none means the remote's default branch), the resolved commit and a digest of
the files as fetched, so later local edits can be detected.

A skill added from a local folder records that folder instead (``folder``,
its absolute path, and the digest of the copy). respec only ever reads it.

Updates are explicit: :func:`check` only reads the remote or the folder;
:func:`update` replaces an item's folder with the newer upstream files. Items
without a source never change. Git runs as a subprocess with prompts disabled, a time
limit (``RESPEC_GIT_TIMEOUT`` seconds per git command, default 120) and, for
the TUI, a way to be cancelled (:func:`cancel_on`).
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from respec import global_skills, items, journal, profiles, trees
from respec.errors import RespecError
from respec.state import load_state

SHORTHAND = profiles.REPO_SHORTHAND
SCP_LIKE = profiles.REPO_SCP_LIKE
# Transports git may use: no remote helpers such as ``fd::`` or ``ext::``.
ALLOWED_PROTOCOLS = "file:git:http:https:ssh"
FULL_SHA = re.compile(r"^[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class Spec:
    """A parsed source argument."""

    repo: str  # as written by the user, recorded in profile.yaml
    url: str  # what git fetches from
    path: str | None = None


def base_url() -> str:
    return profiles.git_base_url()


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


# Commands that may contact a remote, and so may start ssh.
REMOTE_COMMANDS = ("fetch", "ls-remote")
BATCH_SSH = "ssh -o BatchMode=yes -o ConnectTimeout=15"
# Give up on an http(s) transfer slower than 1 KB/s for this many seconds.
LOW_SPEED = ("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30")

TIMEOUT_ENV = "RESPEC_GIT_TIMEOUT"
DEFAULT_TIMEOUT = 120.0

_cancel: ContextVar[threading.Event | None] = ContextVar("cancel", default=None)


@contextmanager
def cancel_on(event: threading.Event) -> Iterator[None]:
    """Stop git, in this thread or task, as soon as ``event`` is set.

    The running git command is killed and :class:`GitCancelled` is raised,
    so the operation rolls back like any other git failure.
    """
    token = _cancel.set(event)
    try:
        yield
    finally:
        _cancel.reset(token)


class GitCancelled(RespecError):
    """Raised when git was stopped through :func:`cancel_on`."""


def git_timeout() -> float:
    """Seconds one git command may take (``RESPEC_GIT_TIMEOUT``)."""
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not value > 0 or value == float("inf"):
        raise RespecError(
            f"{TIMEOUT_ENV}={raw!r} is not a number of seconds above zero"
        )
    return value


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run git without prompts and without the caller's repository variables.

    ``GIT_TERMINAL_PROMPT=0`` stops git's own credential prompts, but not
    ssh's host-key or password prompts, so remote commands run ssh in batch
    mode unless the user configured their own ssh command (``GIT_SSH_COMMAND``,
    ``GIT_SSH`` or ``core.sshCommand``). stdin is closed either way.

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
    env["GIT_ALLOW_PROTOCOL"] = ALLOWED_PROTOCOLS
    options: tuple[str, ...] = ()
    if args[0] in REMOTE_COMMANDS:
        options = LOW_SPEED
        if not _own_ssh(env, cwd):
            env["GIT_SSH_COMMAND"] = BATCH_SSH
    done = _run(["git", *options, *args], cwd, env, args[0])
    if done.returncode != 0:
        raise RespecError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def _run(
    command: list[str], cwd: Path | None, env: dict[str, str], name: str = ""
) -> subprocess.CompletedProcess[str]:
    """Run ``command``; stop it at the time limit or when cancelled."""
    limit = git_timeout()
    cancel = _cancel.get()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # Its own process group, so a stop also ends git's helpers
            # (git-remote-http, ssh) that hold the output pipes open.
            start_new_session=True,
        )
    except FileNotFoundError:
        raise RespecError("git is not installed or not on PATH") from None
    deadline = time.monotonic() + limit
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                _stop(process)
                raise GitCancelled(f"git {name} cancelled") from None
            if time.monotonic() >= deadline:
                _stop(process)
                raise RespecError(
                    f"git {name} timed out after {limit:g}s (set {TIMEOUT_ENV} "
                    "to allow longer)"
                ) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _stop(process: subprocess.Popen[str]) -> None:
    """Kill git and every helper it started, then reap it."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()
    process.communicate()


def _own_ssh(env: dict[str, str], cwd: Path | None) -> bool:
    """Whether the user chose how git runs ssh."""
    if env.get("GIT_SSH_COMMAND") or env.get("GIT_SSH"):
        return True
    found = _run(["git", "config", "--get", "core.sshCommand"], cwd, env, "config")
    return found.returncode == 0 and bool(found.stdout.strip())


def remote_commit(url: str, ref: str | None, label: str) -> str:
    """The commit that ``ref`` (default: the remote's HEAD) points to."""
    if ref is not None and FULL_SHA.match(ref):
        return ref
    wanted = ref or "HEAD"
    try:
        output = _git("ls-remote", "--end-of-options", url, wanted)
    except GitCancelled:
        raise
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
        except GitCancelled:
            raise
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
        return trees.real(entry).relative_to(root).as_posix()
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

    Symlinks are never followed while copying out of the repository: the
    folder is first copied with links kept as links, then every link in that
    copy must resolve (through any chain) to a file strictly inside the
    copied folder. Only then is the checked copy written to ``destination``
    with links replaced by the files they point to, so the profile stays
    self-contained and a repository can never make respec copy local files
    (such as ``~/.ssh`` keys) into a profile.

    Links to folders are refused rather than expanded: nested folder links
    would copy their targets again at every level (a 100 kB repository could
    write gigabytes) and sibling folder links can form copy loops. Each file
    link adds at most one copy of one file, which a repository could also
    get from duplicate files at the same fetch cost.
    Every failure is a :class:`RespecError` and leaves no ``destination``.
    """
    root = tree.resolve()
    _within(root, source)
    _copy_checked(source, destination, f"{_label(root, source)!r} from the repository")


def _copy_checked(source: Path, destination: Path, what: str) -> None:
    """Copy ``source`` to ``destination`` by the link rules of
    :func:`copy_fetched`; ``what`` names the source in a failure."""
    if os.path.lexists(destination):
        raise RespecError(f"{destination} already exists")
    with tempfile.TemporaryDirectory(prefix="respec-check-") as scratch:
        checked = Path(scratch) / "item"
        try:
            shutil.copytree(source, checked, symlinks=True)
            _check_links(checked)
            shutil.copytree(checked, destination)
        except RespecError:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        except (OSError, shutil.Error) as error:
            shutil.rmtree(destination, ignore_errors=True)
            raise RespecError(f"could not copy {what}: {_reason(error)}") from None


class SourceMissing(RespecError):
    """A source folder is gone or no longer holds ``SKILL.md``."""


def copy_folder(folder: Path, destination: Path) -> None:
    """Copy the local source ``folder`` to ``destination`` by the rules for
    fetched content (:func:`copy_fetched`). The folder is only read."""
    if not folder.is_dir():
        raise SourceMissing(f"source folder {folder} no longer exists")
    if not (folder / items.SKILL_FILE).is_file():
        raise SourceMissing(
            f"source folder {folder} no longer holds {items.SKILL_FILE}"
        )
    _copy_checked(folder, destination, f"source folder {folder}")


def folder_digest(folder: str) -> str:
    """The digest a copy of the source ``folder`` made now would record."""
    with tempfile.TemporaryDirectory(prefix="respec-folder-") as scratch:
        copy = Path(scratch) / "skill"
        copy_folder(Path(folder), copy)
        return fetched_digest(copy)


def _reason(error: OSError | shutil.Error) -> str:
    """A one-line cause without the temporary paths ``shutil.Error`` lists."""
    if (
        isinstance(error, shutil.Error)
        and error.args
        and isinstance(error.args[0], list)
    ):
        failures = error.args[0]
        first = str(failures[0][-1]) if failures else "copy failed"
        more = f" (and {len(failures) - 1} more)" if len(failures) > 1 else ""
        return first + more
    if isinstance(error, OSError) and error.strerror:
        return error.strerror
    return str(error)


def _check_links(folder: Path) -> None:
    """Refuse symlinks in ``folder`` that leave it, dangle, loop, or name a
    folder."""
    base = folder.resolve()
    for current, dirs, files in os.walk(folder):
        for name in dirs + files:
            entry = Path(current) / name
            if not entry.is_symlink():
                continue
            label = entry.relative_to(folder).as_posix()
            try:
                target = entry.resolve(strict=True)
            except (OSError, RuntimeError):
                raise RespecError(
                    f"symlink {label!r} is broken, loops or points outside the "
                    "skill folder; refusing to copy it"
                ) from None
            if base not in target.parents:
                raise RespecError(
                    f"symlink {label!r} points outside the skill folder; "
                    "refusing to copy it"
                )
            if target.is_dir():
                raise RespecError(
                    f"symlink {label!r} points to a folder; only links to files "
                    "inside the skill folder are copied"
                )


# --- content -----------------------------------------------------------------


def fetched_digest(folder: Path) -> str:
    """A hash of the folder's tree: every entry's relative path and kind, file
    contents and executable bits, and symlink targets (symlinks are not
    followed), so added empty folders and symlinks count as edits too.

    This is ``source.digest`` in ``profile.yaml``: the profile's copy as
    fetched. It is not :func:`respec.unknown.digest`, which fingerprints
    installed copies in target folders; the two are never compared.
    """
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
    """Result of adding skills from a repository."""

    profile: str
    skills: list[str]
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
    journal.ready(respec_home, user_home)
    name = items.resolve_profile_name(respec_home, profile_name)
    before = profiles.load_profile(respec_home, name)
    with journal.begin(respec_home, "add", profile=name, phase="copy"):
        return _add(respec_home, user_home, spec, ref, name, before)


def _add(
    respec_home: Path,
    user_home: Path,
    spec: Spec,
    ref: str | None,
    name: str,
    before: profiles.Profile,
) -> SourceChange:
    """The changing part of :func:`add`, inside its journal."""
    with checkout(spec.url, ref, spec.repo) as (tree, commit):
        found = _find_skills(tree, spec)
        global_skills.refuse_reserved(respec_home, [item for item, _ in found], name)
        clashes = [item for item, _ in found if item in before.skills]
        if clashes:
            raise RespecError(
                f"profile {name!r} already has {', '.join(map(repr, clashes))}; "
                "nothing was added"
            )
        added: list[str] = []
        sources: dict[str, dict[str, str]] = {}
        journal.set_phase(respec_home, "copy")
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
                        digest=fetched_digest(staged),
                    )
                    folder = before.path / profiles.SKILLS_DIR / item
                    if not os.path.lexists(folder):
                        # Only folders this run makes are removed on rollback;
                        # add_local refuses one that is already there.
                        journal.note(respec_home, "created", item)
                    items.add_local(respec_home, name, staged, origin=source)
                    journal.checkpoint("added")
                    added.append(item)
                    sources[item] = source.to_dict()
        except RespecError:
            _forget(before, added)
            raise
        except (OSError, shutil.Error) as error:
            _forget(before, added)
            raise RespecError(f"could not add from {spec.repo}: {error}") from None

    change = SourceChange(profile=name, skills=added, sources=sources)
    journal.set_phase(respec_home, "refresh")
    items.refresh_active(respec_home, user_home, change, lambda: _forget(before, added))
    return change


def _forget(before: profiles.Profile, added: list[str]) -> None:
    profiles.restore_profile(before)
    for item in added:
        shutil.rmtree(before.path / profiles.SKILLS_DIR / item, ignore_errors=True)


# --- update --------------------------------------------------------------------


@dataclass
class Row:
    """One sourced skill of a check. A git source gives ``current`` and
    ``latest`` (commits); a folder source gives ``folder``, and
    ``source_missing`` (with ``message``) when that folder is gone. A skill
    the profile's source no longer lists is ``gone``; one it lists that the
    profile does not have is ``new`` (with ``enabled``, its starting state)."""

    skill: str
    current: str | None = None
    latest: str | None = None
    folder: str | None = None
    update_available: bool | None = None
    modified: bool | None = None
    source_missing: bool | None = None
    message: str | None = None
    error: str | None = None
    gone: bool | None = None
    new: bool | None = None
    enabled: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def _sourced(profile: profiles.Profile, item: str | None) -> list[str]:
    if item is None:
        return [name for name, entry in profile.skills.items() if entry.source]
    if item not in profile.skills:
        known = ", ".join(profile.skills) or "none"
        raise RespecError(
            f"profile {profile.name!r} has no skill {item!r} (skills: {known})"
        )
    if profile.skills[item].source is None:
        raise RespecError(
            f"skill {item!r} has no source; skills without a source never change"
        )
    return [item]


def _modified(profile: profiles.Profile, item: str) -> bool:
    """Whether the item's files differ from what was fetched (unknown: True)."""
    source = profile.skills[item].source
    folder = profile.path / profiles.SKILLS_DIR / item
    return source is None or source.digest != fetched_digest(folder)


def _latest(source: profiles.Source, cache: dict[tuple[str, str | None], str]) -> str:
    """What the source holds now: the upstream commit, or for a folder source
    the digest of its files, to compare with :func:`_recorded`."""
    if source.folder is not None:
        return folder_digest(source.folder)
    assert source.repo is not None
    key = (repo_url(source.repo), source.ref)
    if key not in cache:
        cache[key] = remote_commit(key[0], source.ref, source.repo)
    return cache[key]


def _recorded(source: profiles.Source) -> str | None:
    """What ``profile.yaml`` says the copy was made from (see :func:`_latest`)."""
    return source.digest if source.folder is not None else source.commit


def _open_source(
    stack: contextlib.ExitStack, profile: profiles.Profile, item: str | None
) -> tuple[Reference | None, RespecError | None]:
    """The profile's source, opened (until ``stack`` closes) to compare its
    skills with the profile's, or the reason it cannot be read. Neither when
    one skill is named or the profile has no source."""
    if item is not None or profile.source is None:
        return None, None
    try:
        return stack.enter_context(reference(profile.source, profile.name)), None
    except GitCancelled:
        raise
    except RespecError as error:
        return None, error


def _gone(profile: profiles.Profile, found: Reference | None, item: str) -> bool:
    """Whether skill ``item`` came from the profile's source, which no longer
    lists it. Skills from anywhere else are never gone."""
    return (
        found is not None
        and item not in found.profile.skills
        and from_profile_source(profile, item)
    )


def check(
    respec_home: Path, profile_name: str | None = None, item: str | None = None
) -> tuple[str, list[Row], dict[str, object] | None]:
    """Report, per sourced item, whether a newer upstream commit exists, and
    (when no item is named) the skills that are new in the profile's source
    or gone from it. Returns the profile's name, the rows and the state of
    the profile's source (None when it has none or an item is named): its
    record, ``latest`` for git, and ``source_missing`` with ``message`` or
    ``error`` when it could not be read."""
    profile = profiles.load_profile(
        respec_home, items.resolve_profile_name(respec_home, profile_name)
    )
    cache: dict[tuple[str, str | None], str] = {}
    rows: list[Row] = []
    with contextlib.ExitStack() as stack:
        found, failure = _open_source(stack, profile, item)
        for name in _sourced(profile, item):
            source = profile.skills[name].source
            assert source is not None
            row = Row(
                skill=name,
                current=source.commit,
                folder=source.folder,
                modified=_modified(profile, name),
            )
            rows.append(row)
            if _gone(profile, found, name):
                row.gone = True
                continue
            try:
                if failure is not None and from_profile_source(profile, name):
                    raise failure  # an unreadable source changes nothing
                latest = _latest(source, cache)
                row.update_available = latest != _recorded(source)
                if source.folder is None:
                    row.latest = latest
            except GitCancelled:
                raise
            except SourceMissing as error:
                row.source_missing, row.message = True, str(error)
            except RespecError as error:
                row.error = str(error)
        state: dict[str, object] | None = None
        if item is None and profile.source is not None:
            state = dict(profile.source.to_dict())
        if found is not None and state is not None:
            if found.source.commit is not None:
                state["latest"] = found.source.commit
            rows += [
                Row(skill=name, new=True, enabled=entry.enabled)
                for name, entry in found.profile.skills.items()
                if name not in profile.skills
            ]
        elif isinstance(failure, SourceMissing) and state is not None:
            state.update(source_missing=True, message=str(failure))
        elif failure is not None and state is not None:
            state["error"] = str(failure)
    return profile.name, rows, state


@dataclass
class UpdateResult:
    profile: str
    skills: list[dict[str, object]] = field(default_factory=list)
    active: bool = False
    linked: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)
    # The profile's source as recorded after the run, or with the ``result``
    # of a failed read; None when it has none or one skill was named.
    source: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


Confirm = Callable[[str], bool]


def update(
    respec_home: Path,
    user_home: Path,
    profile_name: str | None = None,
    item: str | None = None,
    overwrite_edits: Confirm = lambda item: False,
    remove_edits: Confirm | None = None,
) -> UpdateResult:
    """Apply newer upstream commits, or a source folder's newer files, to
    sourced items. With no item named, the profile is also put in line with
    the skills of its own source: new ones are added, in the state the source
    gives them, and the ones that came from it and are gone are removed.

    An item whose files were edited locally is replaced only when
    ``overwrite_edits(item)`` returns true, and removed only when
    ``remove_edits(item)`` does (default: the same answer); otherwise it is
    skipped.
    """
    journal.ready(respec_home, user_home)
    profile = profiles.load_profile(
        respec_home, items.resolve_profile_name(respec_home, profile_name)
    )
    with journal.begin(
        respec_home,
        "update",
        profile=profile.name,
        # Whether profile.yaml was saved yet: recovery compares against this.
        profile_digest=journal.file_digest(profile.path / profiles.PROFILE_FILE),
        phase="copy",
    ):
        return _update(
            respec_home,
            user_home,
            profile,
            item,
            overwrite_edits,
            remove_edits or overwrite_edits,
        )


def _update(
    respec_home: Path,
    user_home: Path,
    profile: profiles.Profile,
    item: str | None,
    overwrite_edits: Confirm,
    remove_edits: Confirm,
) -> UpdateResult:
    """The changing part of :func:`update`, inside its journal."""
    # Whether the profile is the active one, also when nothing is swapped
    # (a refresh below fills it in again).
    active = load_state(respec_home).active_profile == profile.name
    result = UpdateResult(profile=profile.name, active=active)
    skills = dict(profile.skills)
    replaced: list[tuple[Path, Path]] = []  # (live folder, kept old folder)
    removing: list[str] = []  # gone from the profile's source
    added: list[str] = []  # new in the profile's source
    cache: dict[tuple[str, str | None], str] = {}
    try:
        with contextlib.ExitStack() as stack:
            found, failure = _open_source(stack, profile, item)
            for name in _sourced(profile, item):
                source = skills[name].source
                assert source is not None
                _put_back_old(profile, name)
                row = _row(name, source)
                result.skills.append(row)
                if _gone(profile, found, name):
                    row["gone"] = True
                    if _modified(profile, name) and not remove_edits(name):
                        row["result"] = "skipped-local-edits"
                        continue
                    # Journaled before profile.yaml is saved without it:
                    # recovery deletes the folder once it is not listed.
                    journal.note(respec_home, "removing", name)
                    removing.append(name)
                    del skills[name]
                    row["result"] = "removed"
                    continue
                try:
                    if failure is not None and from_profile_source(profile, name):
                        raise failure  # an unreadable source changes nothing
                    latest = _latest(source, cache)
                except GitCancelled:
                    raise
                except RespecError as error:
                    row.update(_failure(error))
                    continue
                if source.folder is None:
                    row["latest"] = latest
                if latest == _recorded(source):
                    row["result"] = "up-to-date"
                    continue
                if _modified(profile, name) and not overwrite_edits(name):
                    row["result"] = "skipped-local-edits"
                    continue
                try:
                    new_source = _replace(respec_home, profile, name, source, replaced)
                except GitCancelled:
                    raise
                except (RespecError, OSError, shutil.Error) as error:
                    row.update(_failure(error))
                    continue
                row["result"] = "updated"
                if source.folder is None:
                    row["latest"] = new_source.commit
                skills[name] = dataclasses.replace(skills[name], source=new_source)
            for name in found.profile.skills if found is not None else ():
                if name in profile.skills:
                    continue
                try:
                    entry = _add_new(respec_home, profile, found, name, added)
                except (RespecError, OSError, shutil.Error) as error:
                    result.skills.append({"skill": name, **_failure(error)})
                    continue
                assert entry.source is not None
                row = _row(name, entry.source)
                row.update(result="added", enabled=entry.enabled)
                result.skills.append(row)
                skills[name] = entry
        after = dataclasses.replace(
            profile,
            skills=skills,
            source=found.source if found is not None else profile.source,
            layers={
                name: dataclasses.replace(
                    layer,
                    items=tuple(m for m in layer.items if m not in removing),
                )
                for name, layer in profile.layers.items()
            },
        )
        if item is None and after.source is not None:
            result.source = {
                **after.source.to_dict(),
                **(_failure(failure) if failure is not None else {}),
            }
        if not (replaced or removing or added or after.source != profile.source):
            return result
        profiles.save_profile(after)
        journal.checkpoint("profile-saved")
        journal.set_phase(respec_home, "refresh")
    except BaseException:
        _restore(profile, replaced, added)
        raise

    undone: list[bool] = []

    def undo() -> None:
        undone.append(True)
        _restore(profile, replaced, added)

    try:
        items.refresh_active(respec_home, user_home, result, undo)
    finally:
        # A refused refresh has moved the old folders back already; after any
        # other failure the new files and profile.yaml agree, so drop the rest.
        for _, old in replaced:
            shutil.rmtree(old, ignore_errors=True)
        if not undone:
            # profile.yaml no longer lists them and their links are gone.
            for name in removing:
                shutil.rmtree(
                    profile.path / profiles.SKILLS_DIR / name, ignore_errors=True
                )
    return result


def _row(name: str, source: profiles.Source) -> dict[str, object]:
    """How an update row names a skill and where it comes from."""
    if source.folder is None:
        return {"skill": name, "current": source.commit}
    return {"skill": name, "folder": source.folder}


def _add_new(
    respec_home: Path,
    profile: profiles.Profile,
    found: Reference,
    item: str,
    added: list[str],
) -> profiles.SkillEntry:
    """Copy a skill that is new in the profile's source into the profile.
    A name a shipped or global skill has is refused, as ``add`` does."""
    global_skills.refuse_reserved(respec_home, [item], profile.name)
    folder = profile.path / profiles.SKILLS_DIR / item
    if os.path.lexists(folder):
        raise RespecError(
            f"{folder} already exists but is not listed in "
            f"{profiles.PROFILE_FILE}; move it out of the way first"
        )
    # Journaled before it is made: only folders this run makes are removed
    # when it is rolled back.
    journal.note(respec_home, "created", item)
    entry = found.take(item, folder)
    added.append(item)
    journal.checkpoint("added")
    return entry


def _failure(error: Exception) -> dict[str, object]:
    """How an update row reports ``error``: a source folder that is gone is
    ``source-missing`` (reported, not a failure), anything else an error."""
    if isinstance(error, SourceMissing):
        return {"result": "source-missing", "message": str(error)}
    return {"result": "error", "error": str(error)}


def _replace(
    respec_home: Path,
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
    dropping = skills_dir / f".{item}.dropping"
    if os.path.lexists(dropping):
        if (
            dropping.is_dir()
            and not dropping.is_symlink()
            and _redundant(respec_home, profile, item, dropping, live)
        ):
            shutil.rmtree(dropping)  # its content is held elsewhere
        else:
            raise RespecError(
                f"{dropping} is left from an interrupted change and its content "
                "is neither in the live folder nor in a backup, so it may hold "
                f"the only copy of something; move it out of the way first. "
                f"{item!r} was not updated."
            )
    if os.path.lexists(old):
        _settle_foreign_old(respec_home, profile, item, live, old)
    shutil.rmtree(incoming, ignore_errors=True)  # fetched files only
    # Journaled before anything is made, with the identity of the live folder,
    # so recovery puts back only what this run moved (see respec.journal).
    swap = {"skill": item, "live": trees.digest(live), "old": str(old)}
    journal.note(respec_home, "swaps", swap)
    commit = source.commit
    if source.folder is not None:
        copy_folder(Path(source.folder), incoming)
    else:
        assert source.repo is not None
        with checkout(repo_url(source.repo), source.ref, source.repo) as (
            tree,
            commit,
        ):
            upstream = inside(tree, source.path)
            if not (upstream / items.SKILL_FILE).is_file():
                raise RespecError(
                    f"{source.repo} at {commit[:12]} has no {items.SKILL_FILE} "
                    f"in {source.path or 'its root'}"
                )
            copy_fetched(tree, upstream, incoming)
    journal.note(
        respec_home, "fetched", {"skill": item, "digest": trees.digest(incoming)}
    )
    os.replace(live, old)
    journal.checkpoint("swapped-out")
    try:
        os.replace(incoming, live)
    except OSError as error:
        os.replace(old, live)
        shutil.rmtree(incoming, ignore_errors=True)
        raise RespecError(f"could not replace {live}: {error}") from None
    replaced.append((live, old))
    journal.checkpoint("swapped-in")
    return dataclasses.replace(source, commit=commit, digest=fetched_digest(live))


def _put_back_old(profile: profiles.Profile, item: str) -> None:
    """A ``.<skill>.old`` whose skill folder is gone is that folder: put it
    back first, so the update compares and replaces the right files."""
    skills_dir = profile.path / profiles.SKILLS_DIR
    live, old = skills_dir / item, skills_dir / f".{item}.old"
    if not os.path.lexists(live) and old.is_dir() and not old.is_symlink():
        os.replace(old, live)


def _redundant(
    respec_home: Path, profile: profiles.Profile, item: str, folder: Path, live: Path
) -> bool:
    """Whether ``folder``'s content is verifiably held by the live skill folder
    or by a backup run (fix-6's test for leftovers)."""
    from respec import adopt

    return (os.path.lexists(live) and trees.same_content(folder, live)) or (
        adopt._backed_up(respec_home, profile.name, item, folder)
    )


def _settle_foreign_old(
    respec_home: Path, profile: profiles.Profile, item: str, live: Path, old: Path
) -> None:
    """A ``.<skill>.old`` that no running update made (the journal settles its
    own first), handled by the same rules as adopt's staging folders (fix-6):
    put back when the live folder is gone, dropped when its content is
    verifiably held by the live folder or a backup run, otherwise kept and the
    skill is refused, as it may hold the only copy of something."""
    if old.is_dir() and not old.is_symlink():
        if not os.path.lexists(live):
            os.replace(old, live)
            return
        if _redundant(respec_home, profile, item, old, live):
            # Renamed before the delete: a kill part way leaves a .dropping
            # folder, verified redundant already, which the next update removes.
            dropping = old.with_name(f".{item}.dropping")
            journal.note(respec_home, "dropping", str(dropping))
            os.replace(old, dropping)
            shutil.rmtree(dropping)
            return
    raise RespecError(
        f"{old} is left from an interrupted change and its content is neither "
        "in the live folder nor in a backup, so it may hold the only copy of "
        f"earlier content; move it out of the way first. {item!r} was not "
        "updated."
    )


def _restore(
    profile: profiles.Profile,
    replaced: list[tuple[Path, Path]],
    added: list[str],
) -> None:
    profiles.restore_profile(profile)
    for live, old in reversed(replaced):
        shutil.rmtree(live, ignore_errors=True)
        os.replace(old, live)
    for item in added:  # copies of the profile's source, made by this run
        shutil.rmtree(profile.path / profiles.SKILLS_DIR / item, ignore_errors=True)


# --- a profile's source -----------------------------------------------------------


def _skill_source(source: profiles.Source, item: str) -> profiles.Source:
    """Where skill ``item`` is inside the profile source ``source``."""
    if source.folder is not None:
        return profiles.Source(
            folder=str(Path(source.folder) / profiles.SKILLS_DIR / item)
        )
    path = f"{profiles.SKILLS_DIR}/{item}"
    return profiles.Source(
        repo=source.repo,
        path=f"{source.path}/{path}" if source.path else path,
        ref=source.ref,
    )


def from_profile_source(profile: profiles.Profile, item: str) -> bool:
    """Whether the skill's recorded source points into the profile's source."""
    source = profile.skills[item].source
    if profile.source is None or source is None:
        return False
    place = dataclasses.replace(source, commit=None, digest=None)
    return place == _skill_source(profile.source, item)


@dataclass(frozen=True)
class Reference:
    """A profile's source, opened for reading: the folder that holds its
    ``profile.yaml`` and ``skills/``, and the profile that file describes."""

    source: profiles.Source  # with the commit that was fetched, for git
    tree: Path | None  # the fetched repository; None for a local folder
    folder: Path
    profile: profiles.Profile

    def take(self, item: str, destination: Path) -> profiles.SkillEntry:
        """Copy skill ``item`` to ``destination`` and return its entry for the
        copy's ``profile.yaml``: enabled as the source says, with its own git
        source when it has one, otherwise a source pointing into this one. A
        folder named by the source's own ``profile.yaml`` is never trusted: a
        later update would copy from whatever local path it names."""
        skill = self.folder / profiles.SKILLS_DIR / item
        if self.tree is None:
            copy_folder(skill, destination)
        else:
            copy_fetched(self.tree, skill, destination)
        entry = self.profile.skills[item]
        if entry.source is not None and entry.source.folder is None:
            return entry
        source = dataclasses.replace(
            _skill_source(self.source, item),
            commit=self.source.commit,
            digest=fetched_digest(destination),
        )
        return dataclasses.replace(entry, source=source)


@contextmanager
def reference(source: profiles.Source, name: str) -> Iterator[Reference]:
    """Open the profile source ``source`` (of profile ``name``) for reading.

    A folder that is gone or no longer holds ``profile.yaml`` is
    :class:`SourceMissing`; a repository that cannot be fetched, a
    ``profile.yaml`` that is not valid or one that lists a skill without its
    folder is a :class:`RespecError`. Nothing is ever written to the source.
    """
    if source.folder is not None:
        folder = Path(source.folder)
        if not folder.is_dir():
            raise SourceMissing(f"source folder {folder} no longer exists")
        if not (folder / profiles.PROFILE_FILE).is_file():
            raise SourceMissing(
                f"source folder {folder} no longer holds {profiles.PROFILE_FILE}"
            )
        yield _read_reference(source, None, folder, source.folder, name)
        return
    assert source.repo is not None
    where = f"{source.repo}#{source.path}" if source.path else source.repo
    with checkout(repo_url(source.repo), source.ref, source.repo) as (tree, commit):
        fetched = dataclasses.replace(source, commit=commit)
        yield _read_reference(fetched, tree, inside(tree, source.path), where, name)


def _read_reference(
    source: profiles.Source, tree: Path | None, folder: Path, where: str, name: str
) -> Reference:
    file = folder / profiles.PROFILE_FILE
    if not file.is_file():
        raise RespecError(f"{where} has no {profiles.PROFILE_FILE}")
    if tree is not None:
        _within(tree.resolve(), file)
    try:
        data = yaml.safe_load(file.read_text("utf-8"))
    except yaml.YAMLError as error:
        raise profiles.ProfileError(file, [f"not valid YAML: {error}"]) from None
    except (OSError, UnicodeDecodeError) as error:
        raise RespecError(f"cannot read {file}: {error}") from None
    profile = profiles.parse_profile(name, folder, data)
    missing = [
        item
        for item in profile.skills
        if not (folder / profiles.SKILLS_DIR / item / items.SKILL_FILE).is_file()
    ]
    if missing:
        raise RespecError(
            f"{where} lists skills without a {profiles.SKILLS_DIR}/<skill>/"
            f"{items.SKILL_FILE}: {', '.join(missing)}"
        )
    return Reference(source=source, tree=tree, folder=folder, profile=profile)


# --- profile install -----------------------------------------------------------


def install_profile(
    respec_home: Path,
    text: str,
    name: str | None = None,
    ref: str | None = None,
) -> profiles.Profile:
    """Copy a whole profile from a local folder or a repository and record
    where it came from. An existing local folder wins; it is only read."""
    local = items.user_path(text)
    if local.exists():
        if ref is not None:
            raise RespecError("--ref only applies to git sources")
        folder = local.resolve()
        if not folder.is_dir():
            raise RespecError(
                f"{folder} is not a folder; give the path of a profile folder"
            )
        if not (folder / profiles.PROFILE_FILE).is_file():
            raise RespecError(f"{folder} has no {profiles.PROFILE_FILE}")
        source = profiles.Source(folder=str(folder))
        name = name or folder.name
    else:
        spec = parse_spec(text, ref)
        source = profiles.Source(repo=spec.repo, path=spec.path, ref=ref)
        name = name or (
            spec.path.rsplit("/", 1)[-1] if spec.path else repo_name(spec.repo)
        )
    profiles.validate_name(name)
    destination = profiles.profiles_dir(respec_home) / name
    if os.path.lexists(destination):
        raise RespecError(
            f"profile {name!r} already exists at {destination}; "
            "choose another name with '--name'"
        )
    journal.ready(respec_home)
    with journal.begin(respec_home, "install", profile=name, path=str(destination)):
        return _install_profile(respec_home, source, name, destination)


def _install_profile(
    respec_home: Path,
    source: profiles.Source,
    name: str,
    destination: Path,
) -> profiles.Profile:
    """The changing part of :func:`install_profile`, inside its journal."""
    with reference(source, name) as found:
        global_skills.refuse_reserved(respec_home, found.profile.skills, name)
        skills: dict[str, profiles.SkillEntry] = {}
        try:
            (destination / profiles.SKILLS_DIR).mkdir(parents=True)
            for item in found.profile.skills:
                skills[item] = found.take(
                    item, destination / profiles.SKILLS_DIR / item
                )
                journal.checkpoint("copied")
            profile = dataclasses.replace(
                found.profile, path=destination, source=found.source, skills=skills
            )
            profiles.save_profile(profile)
        except RespecError:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        except (OSError, shutil.Error) as error:
            shutil.rmtree(destination, ignore_errors=True)
            raise RespecError(f"could not install profile {name!r}: {error}") from None
    return profile
