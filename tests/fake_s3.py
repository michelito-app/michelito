"""A fake S3 server on loopback for the backup tests: path-style PUT, GET, DELETE and
ListObjectsV2 on one bucket, kept in memory. It checks what a real one would: the SigV4
`Authorization` header (recomputed with the test's throwaway secret), the signed payload hash
and `Content-MD5`. Throwaway credentials only; nothing leaves the machine."""

from __future__ import annotations

import base64
import hashlib
import threading
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

from michelito.hosted import s3

BUCKET = "michelito-test"
ACCESS = "TESTACCESSKEY0000000"
SECRET = "test-secret-key-not-real-0000000000000000"
CREDENTIALS = s3.Credentials(ACCESS, SECRET)


@dataclass
class FakeS3:
    objects: dict[str, bytes] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)  # (method, key)
    headers_seen: list[dict[str, str]] = field(default_factory=list)
    corrupt_reads: bool = False  # GET answers altered bytes (checksum tests)
    fail_puts: bool = False
    object_lock: bool = False  # like an R2 bucket lock: an existing key cannot be overwritten
    redirect_to: str = ""  # answer every request with a 307 there
    page_size: int = 1000
    endpoint: str = ""

    @property
    def bucket(self) -> s3.Bucket:
        return s3.Bucket(self.endpoint, BUCKET, CREDENTIALS)


def _handler(state: FakeS3) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # quiet
            return

        def _reply(self, code: int, body: bytes = b"", kind: str = "application/xml") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: int, name: str) -> None:
            self._reply(code, f"<Error><Code>{name}</Code></Error>".encode())

        def _check(self, body: bytes) -> tuple[str, dict[str, str]] | None:
            parsed = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            headers = {k.lower(): v for k, v in self.headers.items()}
            state.headers_seen.append(headers)
            given = headers.get("authorization", "")
            payload = headers.get("x-amz-content-sha256", "")
            if payload != hashlib.sha256(body).hexdigest():
                self._error(400, "XAmzContentSHA256Mismatch")
                return None
            signed = given.partition("SignedHeaders=")[2].partition(",")[0].split(";")
            mine = {name: headers.get(name, "") for name in signed}
            expected = s3.authorization(
                CREDENTIALS,
                "auto",
                self.command,
                parsed.path,
                query,
                mine,
                payload,
                headers.get("x-amz-date", ""),
            )
            if given != expected:
                self._error(403, "SignatureDoesNotMatch")
                return None
            prefix = f"/{BUCKET}"
            if not parsed.path.startswith(prefix):
                self._error(404, "NoSuchBucket")
                return None
            key = urllib.parse.unquote(parsed.path[len(prefix) :].lstrip("/"))
            state.requests.append((self.command, key))
            if state.redirect_to:
                self.send_response(307)
                self.send_header("Location", state.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return key, query

        def do_PUT(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            found = self._check(body)
            if found is None:
                return
            md5 = base64.b64encode(hashlib.md5(body).digest()).decode()  # noqa: S324
            if self.headers.get("Content-MD5") != md5:
                self._error(400, "BadDigest")
                return
            if state.fail_puts:
                self._error(500, "InternalError")
                return
            if state.object_lock and found[0] in state.objects:
                self._error(409, "ObjectLockedByBucketPolicy")
                return
            state.objects[found[0]] = body
            self._reply(200)

        def do_GET(self) -> None:  # noqa: N802
            found = self._check(b"")
            if found is None:
                return
            key, query = found
            if not key and query.get("list-type") == "2":
                self._list(query)
                return
            if key not in state.objects:
                self._error(404, "NoSuchKey")
                return
            body = state.objects[key]
            if state.corrupt_reads:
                body = body[:-1] + bytes([body[-1] ^ 1])
            self._reply(200, body, "application/octet-stream")

        def do_DELETE(self) -> None:  # noqa: N802
            found = self._check(b"")
            if found is None:
                return
            state.objects.pop(found[0], None)
            self._reply(204)

        def _list(self, query: dict[str, str]) -> None:
            prefix = query.get("prefix", "")
            keys = sorted(k for k in state.objects if k.startswith(prefix))
            start = int(query.get("continuation-token", "0") or 0)
            page = keys[start : start + state.page_size]
            more = start + state.page_size < len(keys)
            ns = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'
            items = "".join(f"<Contents><Key>{escape(k)}</Key></Contents>" for k in page)
            token = (
                f"<NextContinuationToken>{start + state.page_size}</NextContinuationToken>"
                if more
                else ""
            )
            body = (
                f"<ListBucketResult {ns}><IsTruncated>{str(more).lower()}</IsTruncated>"
                f"{items}{token}</ListBucketResult>"
            )
            self._reply(200, body.encode())

    return Handler


@contextmanager
def fake_s3() -> Iterator[FakeS3]:
    """A running fake on 127.0.0.1 (an ephemeral port), stopped afterwards."""
    state = FakeS3()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    state.endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
