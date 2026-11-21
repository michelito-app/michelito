"""Tests for scripts/export_public.sh.

Most export a small source repository built in tmp_path (with a copy of the script and of
check_private.py); one exports this repository's real HEAD. None uses the git configuration of
whoever runs the tests: `GIT_CONFIG_GLOBAL` points to a fake one.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("export_public.sh", "check_private.py")
IDENTITY = {"GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "1+tester@users.noreply.github.com"}
MESSAGE = "feat: initial public release"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """An environment without its own git identity; the global one is a file with another one."""
    fake_global = tmp_path / "gitconfig-global"
    fake_global.write_text("[user]\n\tname = Fake Global\n\temail = global@example.com\n")
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**clean, "GIT_CONFIG_GLOBAL": str(fake_global), "GIT_CONFIG_NOSYSTEM": "1"}


def _run(script: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=env)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    ).stdout


@pytest.fixture
def origin(tmp_path: Path, env: dict[str, str]) -> Path:
    """A source repository with the scripts, a clean file and one commit."""
    repo = tmp_path / "origin"
    (repo / "scripts").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "clean.txt").write_text("CTA CTE INVENTADA 123456789\n")
    (repo / ".gitignore").write_text("ignored.txt\n")
    _git(repo, "init", "-q", "-b", "main", env=env)
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "start", env=env)
    return repo


def test_exports_head_as_a_single_commit_with_the_explicit_identity(
    origin: Path, tmp_path: Path, env: dict[str, str]
) -> None:
    (origin / "clean.txt").write_text("uncommitted change\n")
    (origin / "new.txt").write_text("not added\n")
    (origin / "ignored.txt").write_text("ignored\n")
    destination = tmp_path / "public"
    result = _run(origin / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, str(destination))
    assert result.returncode == 0, result.stderr
    assert "uncommitted changes" in result.stderr
    log = _git(destination, "log", "--format=%an <%ae>|%cn <%ce>|%s").splitlines()
    identity = "Tester <1+tester@users.noreply.github.com>"
    assert log == [f"{identity}|{identity}|{MESSAGE}"]
    assert _git(destination, "branch", "--show-current").strip() == "main"
    assert _git(destination, "remote").strip() == ""
    files = set(_git(destination, "ls-files").splitlines())
    assert files == {".gitignore", "clean.txt", *(f"scripts/{name}" for name in SCRIPTS)}
    assert (destination / "clean.txt").read_text() == "CTA CTE INVENTADA 123456789\n"
    assert not (destination / "new.txt").exists()
    assert not (destination / "ignored.txt").exists()


def test_fails_closed_when_the_copy_looks_personal(
    origin: Path, tmp_path: Path, env: dict[str, str]
) -> None:
    (origin / "leak.txt").write_text("account " + "7319" + "42856\n")
    _git(origin, "add", "leak.txt", env=env)
    _git(origin, "commit", "-q", "-m", "leak", env=env)
    destination = tmp_path / "public"
    result = _run(origin / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, str(destination))
    assert result.returncode == 1
    assert "no commit was made" in result.stderr
    no_commit = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], capture_output=True, env=env
    )
    assert no_commit.returncode != 0


@pytest.mark.parametrize("missing", ["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"])
def test_requires_an_explicit_identity(
    origin: Path, tmp_path: Path, env: dict[str, str], missing: str
) -> None:
    identity = {k: v for k, v in IDENTITY.items() if k != missing}
    destination = tmp_path / "public"
    result = _run(origin / "scripts" / SCRIPTS[0], {**env, **identity}, str(destination))
    assert result.returncode == 2
    assert "users.noreply.github.com" in result.stderr
    assert not destination.exists()


@pytest.mark.parametrize("case", ["existing", "missing", "inside"])
def test_refuses_bad_destinations(
    origin: Path, tmp_path: Path, env: dict[str, str], case: str
) -> None:
    args = {"existing": [str(tmp_path)], "missing": [], "inside": [str(origin / "sub" / "pub")]}
    result = _run(origin / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, *args[case])
    assert result.returncode == 2
    expected = {
        "existing": "already exists",
        "missing": "Usage:",
        "inside": "inside the source repository",
    }
    assert expected[case] in result.stderr
    assert not (origin / "sub").exists()


def test_this_repository_exports_cleanly(tmp_path: Path, env: dict[str, str]) -> None:
    destination = tmp_path / "public"
    result = _run(ROOT / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, str(destination))
    assert result.returncode == 0, result.stderr
    exported = set(_git(destination, "ls-files").splitlines())
    tracked = _git(ROOT, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    # Files marked export-ignore (.gitattributes) live in the private working repo only.
    marks = _git(ROOT, "check-attr", "export-ignore", "--", *tracked).splitlines()
    private = {line.split(": ")[0] for line in marks if line.endswith(": set")}
    assert not {"CLAUDE.md", ".gitattributes"} & exported  # absent in the public tree itself
    assert exported == set(tracked) - private
