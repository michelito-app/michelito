"""The Cloudflare Email Worker (`deploy/email-worker/`), run locally with Node: its own tests,
and a cross-check that a request it signs is accepted by the hosted app end to end (synthetic
message, throwaway secret, nothing leaves the machine). Skipped without `node`."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db
from michelito.hosted import forwarding
from tests import forwarding_helpers as mail
from tests.hosted_helpers import WRITE, Hosted, hosted

WORKER = Path(__file__).resolve().parent.parent / "deploy" / "email-worker"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

SIGN = """
import { cloudflareVerdict, settings, signedRequest } from './worker.js'
import { signer } from './fixtures/arc.js'
const input = JSON.parse(await new Promise((done) => {
  let text = ''
  process.stdin.on('data', (chunk) => { text += chunk })
  process.stdin.on('end', () => done(text))
}))
const config = settings({ INBOUND_SECRET: input.secret })
const arc = await signer()
// input.seal: a Cloudflare ARC set sealed with the throwaway key; else the verdict line is
// only written into the message (what a forger can do).
const lines = input.seal
  ? await arc.headers([{ aar: input.verdict }])
  : [`ARC-Authentication-Results: i=1; ${input.verdict}`]
const head = new TextEncoder().encode(lines.join('\\r\\n') + '\\r\\n')
const message = new Uint8Array(Buffer.from(input.raw, 'base64'))
const raw = new Uint8Array(head.length + message.length)
raw.set(head)
raw.set(message, head.length)
const { auth } = await cloudflareVerdict(raw, config, arc.resolver)
const request = await signedRequest(config, input.recipient, raw, auth, input.now * 1000)
process.stdout.write(JSON.stringify({
  body: Buffer.from(request.body).toString('base64'),
  headers: request.headers,
  verdict: auth,
}))
"""


def test_the_workers_own_tests_pass() -> None:
    assert NODE is not None
    done = subprocess.run(
        [NODE, "--test"], cwd=WORKER, capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode == 0, done.stdout[-2000:]


def _signed_by_the_worker(h: Hosted, address: str, message: bytes, seal: bool) -> dict:
    assert NODE is not None
    verdict = mail.worker_auth("popularenlinea.com")
    payload = {
        "secret": mail.SECRET.decode(),
        "recipient": address,
        "raw": base64.b64encode(message).decode(),
        "verdict": verdict,
        "seal": seal,
        "now": h.clock(),
    }
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", SIGN],
        cwd=WORKER,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(done.stdout)


@pytest.mark.parametrize("seal", [True, False])
def test_a_request_the_worker_signs_is_accepted_by_the_app(tmp_path: Path, seal: bool) -> None:
    secret = tmp_path / "inbound.key"
    secret.write_bytes(mail.SECRET)
    h = hosted(tmp_path, inbound_secret=secret, inbox_background=False)
    alice = h.sign_in("alice@example.com")
    address = alice.post("/api/forwarding/address", headers=WRITE).json()["address"]
    account = h.service.store.account_by_email("alice@example.com")
    assert account is not None
    workspace = h.service.workspace_of(account)
    with closing(db.connect(workspace.database, workspace.key)) as conn:
        mail.know_accounts(conn, *mail.EVERY_ACCOUNT)
    message = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    signed = _signed_by_the_worker(h, address, message, seal)
    body = base64.b64decode(signed["body"])
    headers = signed["headers"]
    assert forwarding.verify(
        mail.SECRET,
        headers[forwarding.TIMESTAMP_HEADER],
        headers[forwarding.NONCE_HEADER],
        headers[forwarding.SIGNATURE_HEADER],
        body,
        h.clock(),
    )
    # The Worker's pre-authentication tag is the one the app checks before reading the body.
    assert forwarding.precheck(
        mail.SECRET,
        headers[forwarding.TIMESTAMP_HEADER],
        headers[forwarding.NONCE_HEADER],
        headers[forwarding.SIGNATURE_HEADER],
        headers[forwarding.PREAUTH_HEADER],
        len(body),
        h.clock(),
    )
    assert headers["Content-Length"] == str(len(body))
    answer = h.client().post("/api/inbound-email", content=body, headers=headers)
    assert answer.status_code == 202, answer.text
    found = alice.get("/api/forwarding").json()
    if seal:  # Cloudflare's sealed verdict: the statement goes in
        assert signed["verdict"].startswith("mx.cloudflare.net;")
        assert [a["bank"] for a in found["arrivals"]] == ["popular"]
    else:  # a verdict line the sender wrote: no verdict, quarantine
        assert signed["verdict"] == ""
        assert found["arrivals"] == []
        assert [q["reason"] for q in found["quarantine"]] == ["unauthenticated"]
