"""deploy/docker-compose.yml and deploy/Caddyfile: the demo and the hosted app are separate
containers with separate volumes (the demo never mounts the hosted one, has no way out and no
secrets), the hosted app gets its secrets as Docker secrets, and Caddy routes each host to its
own container with the same strict headers. The compose file is read with `docker compose
config` (skipped where Docker is not installed)."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
DIGEST = "sha256:" + "1" * 64


def _config(profiles: str) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("needs docker compose")
    env = {
        **os.environ,
        "MICHELITO_IMAGE": "ghcr.io/michelito-app/michelito",
        "MICHELITO_DIGEST": DIGEST,
        "COMPOSE_PROFILES": profiles,
    }
    done = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(DEPLOY / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("needs the compose plugin")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _volumes(service: dict) -> set[str]:
    return {v.get("source", "") for v in service.get("volumes", [])}


def test_without_the_profile_only_the_demo_and_caddy_run() -> None:
    config = _config("")
    assert set(config["services"]) == {"app", "caddy"}


def test_the_demo_never_mounts_the_hosted_volume() -> None:
    config = _config("hosted")
    demo, hosted = config["services"]["app"], config["services"]["hosted"]
    assert _volumes(demo) == {"data"}
    assert _volumes(hosted) == {"hosted_data", "pdf_socket"}
    assert config["volumes"]["hosted_data"]["name"] != config["volumes"]["data"]["name"]
    assert "secrets" not in demo
    assert set(demo["networks"]) == {"internal"}  # no way out, and not the hosted network
    assert set(hosted["networks"]) == {"hosted_internal", "egress"}
    assert config["networks"]["hosted_internal"]["internal"] is True
    assert demo["image"] == hosted["image"]  # one build, one digest


def test_the_hosted_app_gets_its_secrets_as_files() -> None:
    hosted = _config("hosted")["services"]["hosted"]
    names = {s["source"] for s in hosted["secrets"]}
    assert names == {
        "master_key",
        "hosted_secret",
        "resend_api_key",
        "inbound_secret",
    }
    env = hosted["environment"]
    assert not any(k.startswith("MICHELITO_R2") for k in env)  # no R2 credentials here
    assert env["MICHELITO_MODE"] == "hosted"
    assert env["MICHELITO_MASTER_KEY_FILE"] == "/run/secrets/master_key"
    assert env["MICHELITO_HOSTED_SECRET_FILE"] == "/run/secrets/hosted_secret"
    assert env["RESEND_API_KEY_FILE"] == "/run/secrets/resend_api_key"
    assert env["MICHELITO_INBOUND_SECRET_FILE"] == "/run/secrets/inbound_secret"
    assert env["MICHELITO_HOSTED_PROXIES"] == "172.30.54.2"
    assert env["MICHELITO_HOSTED_HOST"] == "michelito.app"
    assert "ports" not in hosted
    assert hosted["read_only"] is True
    # No secret value is written into the compose file or the environment.
    assert not any(k.endswith(("_KEY", "_SECRET")) for k in env)


def test_caddy_routes_each_host_to_its_own_container_with_the_same_headers() -> None:
    text = (DEPLOY / "Caddyfile").read_text()
    blocks = dict(
        re.findall(r"^(\{\$MICHELITO_(?:APP_)?HOST\}) \{\n(.*?)^\}", text, re.MULTILINE | re.DOTALL)
    )
    assert "reverse_proxy app:8600" in blocks["{$MICHELITO_HOST}"]
    assert "reverse_proxy hosted:8620" in blocks["{$MICHELITO_APP_HOST}"]
    for block in blocks.values():
        assert "import strict_headers" in block and "import app_proxy" in block
    assert "Content-Security-Policy \"default-src 'none'" in text
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "trusted_proxies" not in code  # Caddy keeps replacing X-Forwarded-For


def test_the_hosted_app_trusts_only_caddys_single_address() -> None:
    config = _config("hosted")
    caddy, hosted = config["services"]["caddy"], config["services"]["hosted"]
    proxy = hosted["environment"]["MICHELITO_HOSTED_PROXIES"]
    assert "," not in proxy and "/" not in proxy  # one address, not a network
    assert caddy["networks"]["hosted_internal"]["ipv4_address"] == proxy
    ipam = config["networks"]["hosted_internal"]["ipam"]["config"][0]
    subnet = ipam["subnet"]
    assert ipaddress.ip_address(proxy) in ipaddress.ip_network(subnet)
    # No automatic address can be Caddy's (the hosted app could otherwise take it first).
    assert ipaddress.ip_address(proxy) not in ipaddress.ip_network(ipam["ip_range"])
    demo_subnet = config["networks"]["internal"]["ipam"]["config"][0]["subnet"]
    assert not ipaddress.ip_network(subnet).overlaps(ipaddress.ip_network(demo_subnet))


def test_backups_run_in_their_own_service_with_the_r2_credentials() -> None:
    config = _config("hosted")
    assert "backup" not in config["services"]  # never started by `up`: only `compose run`
    backup = _config("hosted,ops")["services"]["backup"]
    assert {s["source"] for s in backup["secrets"]} == {
        "master_key",
        "r2_access_key_id",
        "r2_secret_access_key",
    }
    assert _volumes(backup) == {"hosted_data"}
    assert set(backup["networks"]) == {"egress"}  # neither app is reachable from it
    assert "ports" not in backup and backup["read_only"] is True
    assert backup["environment"]["MICHELITO_MODE"] == "hosted"
    assert backup["command"] == ["backup"]


def test_caddy_marks_the_hosted_api_no_store() -> None:
    text = (DEPLOY / "Caddyfile").read_text()
    block = text.split("{$MICHELITO_APP_HOST} {", 1)[1]
    assert 'header /api/* Cache-Control "no-store"' in block


def test_the_pdf_worker_container_holds_nothing_and_reaches_nothing() -> None:
    config = _config("hosted")
    worker, hosted = config["services"]["pdfworker"], config["services"]["hosted"]
    assert "secrets" not in worker
    assert _volumes(worker) == {"pdf_socket"}  # no data volume
    assert worker.get("network_mode") == "none" and "networks" not in worker
    assert worker["read_only"] is True and worker["cap_drop"] == ["ALL"]
    assert sorted(worker["cap_add"]) == ["CHOWN", "KILL", "SETGID", "SETUID"]
    command = worker["command"]
    ids = {command[i]: command[i + 1] for i in range(3, len(command), 2)}
    assert ids == {
        "--server-uid": "10002",
        "--child-uid": "10003",
        "--client-gid": "10001",
        "--slots": "2",
    }
    pool = {str(10003 + n) for n in range(int(ids["--slots"]))}
    assert not pool & {"10001", "10002"}  # the worker uids are nobody else's
    assert hosted["environment"]["MICHELITO_PDF_WORKER_UID"] == ids["--server-uid"]
    assert len({"10001", ids["--server-uid"], ids["--child-uid"]}) == 3  # three identities
    assert "no-new-privileges:true" in worker["security_opt"]
    assert worker["command"][:3] == ["pdf-worker", "--socket", "/run/michelito-pdf/worker.sock"]
    assert not any("KEY" in k or "SECRET" in k for k in worker.get("environment", {}))
    # The hosted app sends it the PDFs over that socket; the demo is not part of it.
    socket_env = hosted["environment"]["MICHELITO_PDF_WORKER_SOCKET"]
    assert socket_env == "/run/michelito-pdf/worker.sock"
    assert "pdf_socket" in _volumes(hosted)
    assert "pdf_socket" not in _volumes(config["services"]["app"])
