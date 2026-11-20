"""deploy/deploy.sh with a fake `docker` on the PATH: input validation, deploy by digest,
falling back when the health check fails, "rollback", feedback.db backups, the hosted app's
backup and health check (with the "hosted" profile) and image cleanup."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "deploy.sh"
IMAGE = "ghcr.io/michelito-app/michelito"
TOKEN = "ghs_" + "x" * 36
SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40
DIG_A, DIG_B, DIG_C, DIG_B2 = (f"sha256:{d * 64}" for d in "123e")
A, B, C = f"{SHA_A} {DIG_A}", f"{SHA_B} {DIG_B}", f"{SHA_C} {DIG_C}"
B2 = f"{SHA_B} {DIG_B2}"  # the same sha rebuilt: another image

# The fake docker: records every call in calls.log and simulates the bare minimum of compose and
# images. State in $FAKE_DIR: digests (images present), images ("tag digest" per line),
# running (the version `up` started), token-login.
FAKE_DOCKER = r"""#!/usr/bin/env bash
set -u
D=$FAKE_DIR
printf '%s\n' "$*" >>"$D/calls.log"
env_get() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2; }
touch "$D/digests" "$D/images"
case "$1" in
login) cat >"$D/token-login"; exit 0 ;;
logout) exit 0 ;;
image)
	case "$2" in
	inspect) grep -qxF "${3#*@}" "$D/digests"; exit ;;
	tag)
		tag=${4##*:}
		grep -v "^$tag " "$D/images" >"$D/i.tmp"
		echo "$tag ${3#*@}" >>"$D/i.tmp"
		mv "$D/i.tmp" "$D/images"
		exit 0 ;;
	ls) cut -d' ' -f1 "$D/images"; exit 0 ;;
	rm)
		tag=${3##*:}
		digest=$(grep "^$tag " "$D/images" | cut -d' ' -f2)
		grep -v "^$tag " "$D/images" >"$D/i.tmp"; mv "$D/i.tmp" "$D/images"
		if ! grep -q " $digest\$" "$D/images"; then
			grep -vxF "$digest" "$D/digests" >"$D/d.tmp"; mv "$D/d.tmp" "$D/digests"
		fi
		exit 0 ;;
	prune) exit 0 ;;
	esac ;;
compose)
	case "$2" in
	pull)
		[[ -n ${FAKE_PULL_FAILS:-} ]] && exit 1
		echo "$MICHELITO_DIGEST" >>"$D/digests"
		exit 0 ;;
	ps) [[ -f $D/running ]] && echo 0123abcd; exit 0 ;;
	up) echo "$(env_get MICHELITO_TAG) $(env_get MICHELITO_DIGEST)" >"$D/running"; exit 0 ;;
	run)
		# `compose run --rm -T backup backup ...`: the backup service, running or not.
		if [[ $3 == --rm && $4 == -T && $5 == backup && $6 == backup ]]; then
			[[ -n ${FAKE_HOSTED_BACKUP_FAILS:-} ]] && exit 1
			printf '%s\n' "$*" >>"$D/hosted-backups"
			exit 0
		fi
		exit 1 ;;
	exec)
		if [[ $4 == hosted ]]; then
			if [[ ${*: -1} == */api/health* ]]; then
				for bad in ${FAKE_HOSTED_BAD:-}; do
					[[ $(env_get MICHELITO_DIGEST) == "$bad" ]] && exit 1
				done
				exit 0
			fi
			exit 1
		fi
		code="${*: -1}"
		if [[ $code == *backup* ]]; then
			[[ -n ${FAKE_NO_FEEDBACK:-} ]] && exit 3
			printf 'SQLite format 3\0backup-of-%s' "$(env_get MICHELITO_TAG)"; exit 0
		fi
		if [[ $code == */api/health* ]]; then
			for bad in ${FAKE_BAD:-}; do
				[[ $(env_get MICHELITO_DIGEST) == "$bad" ]] && exit 1
			done
			exit 0
		fi
		exit 1 ;;
	esac ;;
esac
echo "fake docker: unexpected call: $*" >&2
exit 99
"""


@pytest.fixture
def server(tmp_path: Path) -> Path:
    if shutil.which("bash") is None or shutil.which("flock") is None:
        pytest.skip("needs bash and flock")
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
        "MICHELITO_WAIT": "1",
        "MICHELITO_INTERVAL": "0",
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
    log = root.parent / "calls.log"
    return log.read_text() if log.exists() else ""


def version(root: Path) -> str | None:
    """The "sha digest" in .env, or None if there is none yet."""
    values = dict(
        line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line
    )
    if "MICHELITO_TAG" not in values:
        return None
    return f"{values['MICHELITO_TAG']} {values['MICHELITO_DIGEST']}"


def running(root: Path) -> str:
    return (root.parent / "running").read_text().strip()


def previous(root: Path) -> str | None:
    path = root / "previous-tag"
    return path.read_text().strip() if path.exists() else None


def tags(root: Path) -> list[str]:
    path = root.parent / "images"
    if not path.exists():
        return []
    return sorted(line.split()[0] for line in path.read_text().splitlines())


def backups(root: Path) -> list[Path]:
    return sorted((root / "backups").glob("feedback-*.db"))


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "latest",
        "rollback ",
        " rollback",
        "rollback; id",
        SHA_A,  # no digest
        DIG_A,  # no sha
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
def test_rejects_anything_but_sha_and_digest_or_rollback(server: Path, command: str | None) -> None:
    result = run(server, command)
    assert result.returncode == 2
    assert "invalid request" in result.stderr
    assert calls(server) == ""
    assert version(server) is None


def test_no_token_does_not_deploy(server: Path) -> None:
    result = run(server, A, token=None)
    assert result.returncode == 2
    assert "token is missing" in result.stderr
    assert calls(server) == ""


@pytest.mark.parametrize(
    "token", ["ghs_" + "A1b2" * 10, "ghs_" + "x" * 40 + ".y-z_w", "eyJ" + "a" * 50 + ".b" * 3]
)
def test_current_github_tokens_are_accepted(server: Path, token: str) -> None:
    # GitHub changed the format of Actions tokens (longer, with dots and dashes).
    assert run(server, A, token=token).returncode == 0


@pytest.mark.parametrize("token", ["short", "ghs_" + "x" * 30 + " --x", "ghs_$(id)" + "x" * 20])
def test_oddly_shaped_token_is_rejected(server: Path, token: str) -> None:
    result = run(server, A, token=token)
    assert result.returncode == 2
    assert calls(server) == ""


def test_env_with_an_image_not_from_ghcr(server: Path) -> None:
    env = server / ".env"
    env.write_text(env.read_text().replace(IMAGE, "docker.io/other/image"))
    result = run(server, A)
    assert result.returncode == 2
    assert calls(server) == ""


def test_first_deploy_by_digest(server: Path) -> None:
    result = run(server, A)
    assert result.returncode == 0, result.stderr
    assert version(server) == A
    assert running(server) == A
    assert previous(server) is None
    # The token reaches `docker login` on stdin, never in the arguments.
    assert (server.parent / "token-login").read_text().strip() == TOKEN
    assert TOKEN not in calls(server)
    assert TOKEN not in result.stdout + result.stderr
    log = calls(server)
    assert "login ghcr.io -u michelito-bot --password-stdin" in log
    assert "compose pull --quiet app" in log
    assert f"image tag {IMAGE}@{DIG_A} {IMAGE}:{SHA_A}" in log  # local tag: not dangling
    assert "logout ghcr.io" in log
    # Without a previous container there is nothing to back up.
    assert not (server / "backups").exists()
    assert (server / ".env").stat().st_mode & 0o077 == 0
    assert f"MICHELITO_IMAGE={IMAGE}" in (server / ".env").read_text()


def test_second_deploy_backs_up_and_keeps_the_previous_one(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B)
    assert result.returncode == 0, result.stderr
    assert version(server) == B
    assert previous(server) == A
    [backup] = backups(server)
    assert backup.read_bytes().startswith(b"SQLite format 3\0")
    assert backup.name.endswith(f"-{SHA_A[:12]}.db")
    assert tags(server) == [SHA_A, SHA_B]


def test_old_images_are_removed(server: Path) -> None:
    for each in (A, B, C):
        assert run(server, each).returncode == 0
    assert tags(server) == [SHA_B, SHA_C]  # the current and the previous one
    assert DIG_A not in (server.parent / "digests").read_text()


def test_failed_health_goes_back_to_the_running_one(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_BAD=DIG_B)
    assert result.returncode == 1
    assert "going back to" in result.stdout
    assert version(server) == A
    assert running(server) == A
    assert previous(server) is None  # nothing changed: there is still no previous one
    assert SHA_A in tags(server)  # the good one is not removed
    assert "logout ghcr.io" in calls(server)


def test_redeploying_the_same_failing_sha_goes_back_to_the_previous_one(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    result = run(server, B, FAKE_BAD=DIG_B)
    assert result.returncode == 1
    assert version(server) == A
    assert running(server) == A


def test_the_same_sha_rebuilt_and_failing_goes_back_to_its_old_digest(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    result = run(server, B2, FAKE_BAD=DIG_B2)
    assert result.returncode == 1
    assert version(server) == B


def test_failed_health_on_the_first_deploy(server: Path) -> None:
    result = run(server, A, FAKE_BAD=DIG_A)
    assert result.returncode == 1
    assert "no other version" in result.stdout


def test_failed_pull_changes_nothing(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_PULL_FAILS="1")
    assert result.returncode != 0
    assert version(server) == A
    assert "compose up" not in calls(server).split("pull --quiet app")[-1]


def test_env_without_image_is_not_replaced(server: Path) -> None:
    """Without MICHELITO_IMAGE in .env nothing is deployed (set_version checks it too)."""
    assert run(server, A).returncode == 0
    env = server / ".env"
    env.write_text(env.read_text().replace(f"MICHELITO_IMAGE={IMAGE}\n", ""))
    result = run(server, B)
    assert result.returncode == 2  # caught earlier: the image in .env is not valid
    assert "MICHELITO_IMAGE" in result.stderr


def test_rollback_goes_back_to_the_previous_one_without_pulling(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    (server.parent / "calls.log").unlink()
    result = run(server, "rollback", token=None)
    assert result.returncode == 0, result.stderr
    assert version(server) == A
    assert running(server) == A
    assert previous(server) == B  # another "rollback" goes back to the one before
    assert "pull" not in calls(server)
    assert "login" not in calls(server)
    assert len(backups(server)) == 2
    assert run(server, "rollback", token=None).returncode == 0
    assert version(server) == B


def test_rollback_without_previous(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, "rollback")
    assert result.returncode == 1
    assert "no previous version" in result.stderr
    assert version(server) == A


def test_rollback_pulls_the_previous_one_if_it_is_gone(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    (server.parent / "digests").write_text(f"{DIG_B}\n")
    assert run(server, "rollback", token=None).returncode == 1
    result = run(server, "rollback")
    assert result.returncode == 0, result.stderr
    assert version(server) == A
    assert "compose pull --quiet app" in calls(server)


def _pre_rename_server(root: Path) -> None:
    """A server upgraded from the release before the English rename: .env names the version the
    old script deployed, its previous-version file exists, and this script's marker does not."""
    with (root / ".env").open("a") as env:
        env.write(f"MICHELITO_TAG={SHA_A}\nMICHELITO_DIGEST={DIG_A}\n")
    (root / "etiqueta-anterior").write_text(f"{C}\n")  # spanish-data: the old script's file
    (root.parent / "digests").write_text(f"{DIG_A}\n{DIG_C}\n")
    (root.parent / "images").write_text(f"{SHA_A} {DIG_A}\n{SHA_C} {DIG_C}\n")
    (root.parent / "running").write_text(f"{A}\n")


def test_rollback_to_a_pre_rename_version_is_refused(server: Path) -> None:
    _pre_rename_server(server)
    result = run(server, "rollback", token=None)
    assert result.returncode == 1
    assert "predates the English rename" in result.stderr
    assert version(server) == A
    assert "compose up" not in calls(server)


def test_a_failed_deploy_does_not_fall_back_to_a_pre_rename_version(server: Path) -> None:
    _pre_rename_server(server)
    result = run(server, B, FAKE_BAD=DIG_B)
    assert result.returncode == 1
    assert "not going back to it" in result.stdout
    assert running(server) == B  # left for a manual fix, never the old image with this compose
    assert previous(server) is None


def test_the_first_deploy_after_the_rename_does_not_record_the_old_version(server: Path) -> None:
    _pre_rename_server(server)
    result = run(server, B)
    assert result.returncode == 0, result.stderr
    assert version(server) == B
    assert previous(server) is None
    assert SHA_A in tags(server)  # the pre-rename image stays for a manual rollback
    assert run(server, "rollback", token=None).returncode == 1  # nothing to go back to yet
    assert run(server, C).returncode == 0
    assert previous(server) == B
    assert run(server, "rollback", token=None).returncode == 0
    assert version(server) == B


def test_invalid_previous_is_rejected(server: Path) -> None:
    assert run(server, A).returncode == 0
    (server / "previous-tag").write_text(f"{SHA_B} latest\n")
    result = run(server, "rollback")
    assert result.returncode == 2
    assert version(server) == A


def test_no_feedback_does_not_fail(server: Path) -> None:
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_NO_FEEDBACK="1")
    assert result.returncode == 0, result.stderr
    assert backups(server) == []


def test_keeps_the_last_ten_backups(server: Path) -> None:
    folder = server / "backups"
    folder.mkdir()
    for day in range(1, 13):
        (folder / f"feedback-202601{day:02d}T000000Z-{'0' * 12}.db").write_bytes(b"x")
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    kept = backups(server)
    assert len(kept) == 10
    assert kept[-1].name.endswith(f"-{SHA_A[:12]}.db")  # the new one stays
    assert not (folder / f"feedback-20260101T000000Z-{'0' * 12}.db").exists()


def test_ignores_sighup(server: Path) -> None:
    """If SSH drops, the deploy goes on: the script ignores HUP from the start."""
    assert "trap '' HUP" in SCRIPT.read_text().split("DIR=")[0]


# The hosted app (COMPOSE_PROFILES=hosted in .env).


def _enable_hosted(root: Path) -> None:
    env = root / ".env"
    env.write_text(env.read_text() + "COMPOSE_PROFILES=hosted\n")


def hosted_backups(root: Path) -> list[str]:
    path = root.parent / "hosted-backups"
    return path.read_text().splitlines() if path.exists() else []


def test_without_the_profile_the_hosted_app_is_not_touched(server: Path) -> None:
    assert run(server, A).returncode == 0
    assert run(server, B).returncode == 0
    assert " hosted " not in calls(server)


def test_with_the_profile_the_hosted_app_is_backed_up_and_checked(server: Path) -> None:
    _enable_hosted(server)
    assert run(server, A).returncode == 0
    assert hosted_backups(server) == []  # the first deploy: nothing to back up yet
    result = run(server, B)
    assert result.returncode == 0, result.stderr
    [line] = hosted_backups(server)
    assert line.startswith("compose run --rm -T backup backup --to /data/deploy-backups")
    assert f"--keep 10 --label {SHA_A[:12]} --skip-empty" in line
    assert "exec -T hosted python -c" in calls(server)
    assert running(server) == B


def test_a_failed_hosted_backup_does_not_deploy(server: Path) -> None:
    _enable_hosted(server)
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_HOSTED_BACKUP_FAILS="1")
    assert result.returncode != 0
    assert "could not back up the hosted app" in result.stderr
    assert running(server) == A and version(server) == A


def test_an_unhealthy_hosted_app_goes_back(server: Path) -> None:
    _enable_hosted(server)
    assert run(server, A).returncode == 0
    result = run(server, B, FAKE_HOSTED_BAD=DIG_B)
    assert result.returncode == 1
    assert running(server) == A


def test_the_hosted_backup_runs_even_when_the_hosted_app_is_stopped(server: Path) -> None:
    _enable_hosted(server)
    assert run(server, A).returncode == 0
    (server.parent / "running").unlink()  # nothing running (crashed, stopped by hand)
    result = run(server, B)
    assert result.returncode == 0, result.stderr
    assert len(hosted_backups(server)) == 1
