"""Pruebas de scripts/exportar_publico.sh.

La mayoría exporta un repositorio de origen pequeño armado en tmp_path (con copia del script y
de check_private.py); una exporta el HEAD real de este repositorio. Ninguna usa la
configuración de git de quien corre las pruebas: `GIT_CONFIG_GLOBAL` apunta a una falsa.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("exportar_publico.sh", "check_private.py")
IDENTITY = {"GIT_AUTHOR_NAME": "Prueba", "GIT_AUTHOR_EMAIL": "1+prueba@users.noreply.github.com"}
MESSAGE = "feat: versión inicial pública"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Entorno sin identidad de git propia; la global es un archivo con otra identidad."""
    fake_global = tmp_path / "gitconfig-global"
    fake_global.write_text("[user]\n\tname = Global Falso\n\temail = global@example.com\n")
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
    """Un repositorio de origen con los scripts, un archivo limpio y un commit."""
    repo = tmp_path / "origen"
    (repo / "scripts").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "limpio.txt").write_text("CTA CTE INVENTADA 123456789\n")
    (repo / ".gitignore").write_text("ignorado.txt\n")
    _git(repo, "init", "-q", "-b", "main", env=env)
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "inicio", env=env)
    return repo


def test_exports_head_as_a_single_commit_with_the_explicit_identity(
    origin: Path, tmp_path: Path, env: dict[str, str]
) -> None:
    (origin / "limpio.txt").write_text("cambio sin commit\n")
    (origin / "nuevo.txt").write_text("sin agregar\n")
    (origin / "ignorado.txt").write_text("ignorado\n")
    destination = tmp_path / "publico"
    result = _run(origin / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, str(destination))
    assert result.returncode == 0, result.stderr
    assert "cambios sin commit" in result.stderr
    log = _git(destination, "log", "--format=%an <%ae>|%cn <%ce>|%s").splitlines()
    identity = "Prueba <1+prueba@users.noreply.github.com>"
    assert log == [f"{identity}|{identity}|{MESSAGE}"]
    assert _git(destination, "branch", "--show-current").strip() == "main"
    assert _git(destination, "remote").strip() == ""
    files = set(_git(destination, "ls-files").splitlines())
    assert files == {".gitignore", "limpio.txt", *(f"scripts/{name}" for name in SCRIPTS)}
    assert (destination / "limpio.txt").read_text() == "CTA CTE INVENTADA 123456789\n"
    assert not (destination / "nuevo.txt").exists()
    assert not (destination / "ignorado.txt").exists()


def test_fails_closed_when_the_copy_looks_personal(
    origin: Path, tmp_path: Path, env: dict[str, str]
) -> None:
    (origin / "fuga.txt").write_text("cuenta " + "7319" + "42856\n")
    _git(origin, "add", "fuga.txt", env=env)
    _git(origin, "commit", "-q", "-m", "fuga", env=env)
    destination = tmp_path / "publico"
    result = _run(origin / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, str(destination))
    assert result.returncode == 1
    assert "no se hizo el commit" in result.stderr
    no_commit = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], capture_output=True, env=env
    )
    assert no_commit.returncode != 0


@pytest.mark.parametrize("missing", ["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"])
def test_requires_an_explicit_identity(
    origin: Path, tmp_path: Path, env: dict[str, str], missing: str
) -> None:
    identity = {k: v for k, v in IDENTITY.items() if k != missing}
    destination = tmp_path / "publico"
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
    expected = {"existing": "ya existe", "missing": "Uso:", "inside": "dentro del repositorio"}
    assert expected[case] in result.stderr
    assert not (origin / "sub").exists()


def test_this_repository_exports_cleanly(tmp_path: Path, env: dict[str, str]) -> None:
    destination = tmp_path / "publico"
    result = _run(ROOT / "scripts" / SCRIPTS[0], {**env, **IDENTITY}, str(destination))
    assert result.returncode == 0, result.stderr
    exported = set(_git(destination, "ls-files").splitlines())
    assert exported == set(_git(ROOT, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
