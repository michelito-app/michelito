"""deploy/desplegar.sh con un `docker` falso en el PATH: validación de la entrada, despliegue por
digest, vuelta atrás si falla la salud, «rollback», respaldos de opiniones.db y limpieza de
imágenes."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "desplegar.sh"
IMAGE = "ghcr.io/michelito-app/michelito"
TOKEN = "ghs_" + "x" * 36
SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40
DIG_A, DIG_B, DIG_C, DIG_B2 = (f"sha256:{d * 64}" for d in "123e")
A, B, C = f"{SHA_A} {DIG_A}", f"{SHA_B} {DIG_B}", f"{SHA_C} {DIG_C}"
B2 = f"{SHA_B} {DIG_B2}"  # el mismo sha reconstruido: otra imagen

# El docker falso: anota cada llamada en llamadas.log y simula lo mínimo de compose e imágenes.
# Estado en $FAKE_DIR: digests (imágenes presentes), imagenes («etiqueta digest» por línea),
# en-marcha (la versión que levantó `up`), token-login.
FAKE_DOCKER = r"""#!/usr/bin/env bash
set -u
D=$FAKE_DIR
printf '%s\n' "$*" >>"$D/llamadas.log"
env_get() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2; }
touch "$D/digests" "$D/imagenes"
case "$1" in
login) cat >"$D/token-login"; exit 0 ;;
logout) exit 0 ;;
image)
	case "$2" in
	inspect) grep -qxF "${3#*@}" "$D/digests"; exit ;;
	tag)
		etiqueta=${4##*:}
		grep -v "^$etiqueta " "$D/imagenes" >"$D/i.tmp"
		echo "$etiqueta ${3#*@}" >>"$D/i.tmp"
		mv "$D/i.tmp" "$D/imagenes"
		exit 0 ;;
	ls) cut -d' ' -f1 "$D/imagenes"; exit 0 ;;
	rm)
		etiqueta=${3##*:}
		digest=$(grep "^$etiqueta " "$D/imagenes" | cut -d' ' -f2)
		grep -v "^$etiqueta " "$D/imagenes" >"$D/i.tmp"; mv "$D/i.tmp" "$D/imagenes"
		if ! grep -q " $digest\$" "$D/imagenes"; then
			grep -vxF "$digest" "$D/digests" >"$D/d.tmp"; mv "$D/d.tmp" "$D/digests"
		fi
		exit 0 ;;
	prune) exit 0 ;;
	esac ;;
compose)
	case "$2" in
	pull)
		[[ -n ${FAKE_PULL_FALLA:-} ]] && exit 1
		echo "$MICHELITO_DIGEST" >>"$D/digests"
		exit 0 ;;
	ps) [[ -f $D/en-marcha ]] && echo 0123abcd; exit 0 ;;
	up) echo "$(env_get MICHELITO_TAG) $(env_get MICHELITO_DIGEST)" >"$D/en-marcha"; exit 0 ;;
	exec)
		code="${*: -1}"
		if [[ $code == *backup* ]]; then
			[[ -n ${FAKE_SIN_OPINIONES:-} ]] && exit 3
			printf 'SQLite format 3\0respaldo-de-%s' "$(env_get MICHELITO_TAG)"; exit 0
		fi
		if [[ $code == */api/health* ]]; then
			for mala in ${FAKE_MALAS:-}; do
				[[ $(env_get MICHELITO_DIGEST) == "$mala" ]] && exit 1
			done
			exit 0
		fi
		exit 1 ;;
	esac ;;
esac
echo "docker falso: llamada inesperada: $*" >&2
exit 99
"""


@pytest.fixture
def server(tmp_path: Path) -> Path:
    if shutil.which("bash") is None or shutil.which("flock") is None:
        pytest.skip("hace falta bash y flock")
    root = tmp_path / "michelito"
    root.mkdir()
    (root / ".env").write_text(
        f"MICHELITO_HOST=demo.example.com\nMICHELITO_IMAGE={IMAGE}\nGHCR_USER=michelito-bot\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return root


def run(
    root: Path, command: str | None, token: str | None = TOKEN, **fake: str
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(root.parent),
        "MICHELITO_DIR": str(root),
        "MICHELITO_ESPERA": "1",
        "MICHELITO_INTERVALO": "0",
        "FAKE_DIR": str(root.parent),
        **fake,
    }
    if command is not None:
        env["SSH_ORIGINAL_COMMAND"] = command
    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=f"{token}\n" if token is not None else "",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def calls(root: Path) -> str:
    log = root.parent / "llamadas.log"
    return log.read_text() if log.exists() else ""


def version(root: Path) -> str | None:
    """«sha digest» de .env, o None si todavía no hay."""
    values = dict(
        line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line
    )
    if "MICHELITO_TAG" not in values:
        return None
    return f"{values['MICHELITO_TAG']} {values['MICHELITO_DIGEST']}"


def running(root: Path) -> str:
    return (root.parent / "en-marcha").read_text().strip()


def previous(root: Path) -> str | None:
    path = root / "etiqueta-anterior"
    return path.read_text().strip() if path.exists() else None


def tags(root: Path) -> list[str]:
    path = root.parent / "imagenes"
    if not path.exists():
        return []
    return sorted(line.split()[0] for line in path.read_text().splitlines())


def backups(root: Path) -> list[Path]:
    return sorted((root / "respaldos").glob("opiniones-*.db"))


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "latest",
        "rollback ",
        " rollback",
        "rollback; id",
        SHA_A,  # sin digest
        DIG_A,  # sin sha
        f"{SHA_A}  {DIG_A}",
        f"{DIG_A} {SHA_A}",
        f"{'a' * 39} {DIG_A}",
        f"{'A' * 40} {DIG_A}",
        f"{SHA_A} sha256:{'1' * 63}",
        f"{SHA_A} sha512:{'1' * 64}",
        f"{SHA_A} {DIG_A}\n",
        f"{SHA_A} {DIG_A} && id",
        f"{SHA_A} {DIG_A};id",
        "$(id)",
    ],
)
def test_rechaza_lo_que_no_es_sha_y_digest_o_rollback(server: Path, command: str | None) -> None:
    result = run(server, command)
    assert result.returncode == 2
    assert "pedido no válido" in result.stderr
    assert calls(server) == ""
    assert version(server) is None


def test_sin_token_no_despliega(server: Path) -> None:
    result = run(server, A, token=None)
    assert result.returncode == 2
    assert "falta el token" in result.stderr
    assert calls(server) == ""


@pytest.mark.parametrize(
    "token", ["ghs_" + "A1b2" * 10, "ghs_" + "x" * 40 + ".y-z_w", "eyJ" + "a" * 50 + ".b" * 3]
)
def test_tokens_actuales_de_github_se_aceptan(server: Path, token: str) -> None:
    # GitHub cambió el formato de los tokens de Actions (más largos, con puntos y guiones).
    assert run(server, A, token=token).returncode == 0


@pytest.mark.parametrize("token", ["corto", "ghs_" + "x" * 30 + " --x", "ghs_$(id)" + "x" * 20])
def test_token_con_forma_rara_se_rechaza(server: Path, token: str) -> None:
    result = run(server, A, token=token)
    assert result.returncode == 2
    assert calls(server) == ""


def test_env_con_imagen_que_no_es_de_ghcr(server: Path) -> None:
    env = server / ".env"
    env.write_text(env.read_text().replace(IMAGE, "docker.io/otro/imagen"))
    result = run(server, A)
    assert result.returncode == 2
    assert calls(server) == ""


def test_primer_despliegue_por_digest(server: Path) -> None:
    result = run(server, A)
    assert result.returncode == 0, result.stderr
    assert version(server) == A
    assert running(server) == A
    assert previous(server) is None
    # El token entra por stdin a `docker login`, nunca en los argumentos.
    assert (server.parent / "token-login").read_text().strip() == TOKEN
    assert TOKEN not in calls(server)
    assert TOKEN not in result.stdout + result.stderr
    log = calls(server)
    assert "login ghcr.io -u michelito-bot --password-stdin" in log
    assert "compose pull --quiet app" in log
    assert f"image tag {IMAGE}@{DIG_A} {IMAGE}:{SHA_A}" in log  # etiqueta local: no es huérfana
    assert "logout ghcr.io" in log
    # Sin contenedor previo no hay nada que respaldar.
    assert not (server / "respaldos").exists()
    assert (server / ".env").stat().st_mode & 0o077 == 0
    assert f"MICHELITO_IMAGE={IMAGE}" in (server / ".env").read_text()


def test_segundo_despliegue_respalda_y_guarda_la_anterior(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B)
    assert result.returncode == 0, result.stderr
    assert version(server) == B
    assert previous(server) == A
    [backup] = backups(server)
    assert backup.read_bytes().startswith(b"SQLite format 3\0")
    assert backup.name.endswith(f"-{SHA_A[:12]}.db")
    assert tags(server) == [SHA_A, SHA_B]


def test_las_imagenes_viejas_se_borran(server: Path) -> None:
    for each in (A, B, C):
        assert run(server, each).returncode == 0
    assert tags(server) == [SHA_B, SHA_C]  # la actual y la anterior
    assert DIG_A not in (server.parent / "digests").read_text()


def test_salud_falla_vuelve_a_la_que_estaba(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_MALAS=DIG_B)
    assert result.returncode == 1
    assert "vuelvo a" in result.stdout
    assert version(server) == A
    assert running(server) == A
    assert previous(server) is None  # nada cambió: la anterior sigue sin existir
    assert SHA_A in tags(server)  # la buena no se borra
    assert "logout ghcr.io" in calls(server)


def test_redesplegar_el_mismo_sha_que_falla_vuelve_a_la_anterior(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    result = run(server, B, FAKE_MALAS=DIG_B)
    assert result.returncode == 1
    assert version(server) == A
    assert running(server) == A


def test_el_mismo_sha_reconstruido_que_falla_vuelve_a_su_digest_anterior(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    result = run(server, B2, FAKE_MALAS=DIG_B2)
    assert result.returncode == 1
    assert version(server) == B


def test_salud_falla_en_el_primer_despliegue(server: Path) -> None:
    result = run(server, A, FAKE_MALAS=DIG_A)
    assert result.returncode == 1
    assert "no hay otra versión" in result.stdout


def test_si_no_baja_la_imagen_no_toca_nada(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_PULL_FALLA="1")
    assert result.returncode != 0
    assert version(server) == A
    assert "compose up" not in calls(server).split("pull --quiet app")[-1]


def test_env_sin_imagen_no_se_reemplaza(server: Path) -> None:
    """Sin MICHELITO_IMAGE en .env no se despliega (set_version también lo revisa)."""
    assert run(server, A).returncode == 0
    env = server / ".env"
    env.write_text(env.read_text().replace(f"MICHELITO_IMAGE={IMAGE}\n", ""))
    result = run(server, B)
    assert result.returncode == 2  # se nota antes: la imagen de .env no es válida
    assert "MICHELITO_IMAGE" in result.stderr


def test_rollback_vuelve_a_la_anterior_sin_bajar_nada(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    (server.parent / "llamadas.log").unlink()
    result = run(server, "rollback", token=None)
    assert result.returncode == 0, result.stderr
    assert version(server) == A
    assert running(server) == A
    assert previous(server) == B  # otro «rollback» vuelve a la de antes
    assert "pull" not in calls(server)
    assert "login" not in calls(server)
    assert len(backups(server)) == 2
    assert run(server, "rollback", token=None).returncode == 0
    assert version(server) == B


def test_rollback_sin_anterior(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, "rollback")
    assert result.returncode == 1
    assert "no hay versión anterior" in result.stderr
    assert version(server) == A


def test_rollback_baja_la_anterior_si_ya_no_esta(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    (server.parent / "digests").write_text(f"{DIG_B}\n")
    assert run(server, "rollback", token=None).returncode == 1
    result = run(server, "rollback")
    assert result.returncode == 0, result.stderr
    assert version(server) == A
    assert "compose pull --quiet app" in calls(server)


def test_anterior_invalida_se_rechaza(server: Path) -> None:
    assert run(server, A).returncode == 0
    (server / "etiqueta-anterior").write_text(f"{SHA_B} latest\n")
    result = run(server, "rollback")
    assert result.returncode == 2
    assert version(server) == A


def test_sin_opiniones_no_falla(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_SIN_OPINIONES="1")
    assert result.returncode == 0, result.stderr
    assert backups(server) == []


def test_conserva_los_ultimos_diez_respaldos(server: Path) -> None:
    folder = server / "respaldos"
    folder.mkdir()
    for day in range(1, 13):
        (folder / f"opiniones-202601{day:02d}T000000Z-{'0' * 12}.db").write_bytes(b"x")
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    kept = backups(server)
    assert len(kept) == 10
    assert kept[-1].name.endswith(f"-{SHA_A[:12]}.db")  # el nuevo se queda
    assert not (folder / f"opiniones-20260101T000000Z-{'0' * 12}.db").exists()


def test_ignora_sighup(server: Path) -> None:
    """Si se corta el SSH, el despliegue sigue: el script ignora HUP desde el principio."""
    assert "trap '' HUP" in SCRIPT.read_text().split("DIR=")[0]
