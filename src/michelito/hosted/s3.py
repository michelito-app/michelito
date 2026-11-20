"""A minimal S3 client (AWS Signature Version 4) for the backups in Cloudflare R2.

Four operations are all the backups need: put, get, delete and list (ListObjectsV2), path-style
(`<endpoint>/<bucket>/<key>`), with the standard library only. Why not boto3: it brings
botocore (tens of MB, its own release cadence) for these four calls; SigV4 is a short, fully
specified algorithm and the tests check it against AWS's published example.

- Every PUT carries `Content-MD5` and the SHA-256 of its body (`x-amz-content-sha256`, signed),
  so a body damaged on the way is refused by the server.
- Credentials never appear in `repr`, in a message or in a log; errors name the operation, the
  HTTP status and the S3 error code only.
- The endpoint must be `https`, except a loopback address (the tests' fake server), and no
  redirect is ever followed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_SAFE = "-_.~"

ENDPOINT_ENV = "MICHELITO_R2_ENDPOINT"
BUCKET_ENV = "MICHELITO_R2_BUCKET"
ACCESS_KEY_ENV = "MICHELITO_R2_ACCESS_KEY_ID"
SECRET_KEY_ENV = "MICHELITO_R2_SECRET_ACCESS_KEY"
REGION_ENV = "MICHELITO_R2_REGION"


class S3Error(Exception):
    """A request failed (the message: operation, status and S3 code; never a credential)."""


@dataclass(frozen=True)
class Credentials:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)


@dataclass(frozen=True)
class Bucket:
    endpoint: str  # https://<account>.r2.cloudflarestorage.com
    name: str
    credentials: Credentials = field(repr=False)
    region: str = "auto"  # what R2 expects


def _env_or_file(name: str) -> str:
    """`$NAME`, or the content of the file named by `$NAME_FILE` (a Docker secret)."""
    named = os.environ.get(f"{name}_FILE", "").strip()
    if named:
        try:
            return Path(named).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise S3Error(f"cannot read {name}_FILE: {error.strerror}") from None
    return os.environ.get(name, "").strip()


def bucket_from_environment() -> Bucket:
    """The R2 bucket from the environment (`MICHELITO_R2_*`, the keys also as `*_FILE`)."""
    endpoint = os.environ.get(ENDPOINT_ENV, "").strip()
    name = os.environ.get(BUCKET_ENV, "").strip()
    access, secret = _env_or_file(ACCESS_KEY_ENV), _env_or_file(SECRET_KEY_ENV)
    missing = [
        label
        for label, value in (
            (ENDPOINT_ENV, endpoint),
            (BUCKET_ENV, name),
            (ACCESS_KEY_ENV, access),
            (SECRET_KEY_ENV, secret),
        )
        if not value
    ]
    if missing:
        raise S3Error(f"missing {', '.join(missing)} (or its _FILE)")
    region = os.environ.get(REGION_ENV, "").strip() or "auto"
    return Bucket(endpoint, name, Credentials(access, secret), region)


# Signature Version 4.


def _encode(text: str, keep_slash: bool = False) -> str:
    return urllib.parse.quote(text, safe=_SAFE + ("/" if keep_slash else ""))


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def signing_key(secret_key: str, day: str, region: str, service: str = SERVICE) -> bytes:
    key = _hmac(f"AWS4{secret_key}".encode(), day)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def canonical_query(query: dict[str, str]) -> str:
    return "&".join(f"{_encode(k)}={_encode(v)}" for k, v in sorted(query.items()))


def authorization(
    credentials: Credentials,
    region: str,
    method: str,
    path: str,
    query: dict[str, str],
    headers: dict[str, str],
    payload_sha256: str,
    stamp: str,
) -> str:
    """The `Authorization` header for a request (`headers` must include host and x-amz-date;
    every header given is signed). `path` is already URI-encoded; `stamp` is YYYYMMDDTHHMMSSZ."""
    lowered = {k.lower(): " ".join(v.strip().split()) for k, v in headers.items()}
    names = sorted(lowered)
    canonical = "\n".join(
        [
            method,
            path,
            canonical_query(query),
            "".join(f"{n}:{lowered[n]}\n" for n in names),
            ";".join(names),
            payload_sha256,
        ]
    )
    day = stamp[:8]
    scope = f"{day}/{region}/{SERVICE}/aws4_request"
    to_sign = "\n".join([ALGORITHM, stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signature = hmac.new(
        signing_key(credentials.secret_key, day, region), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return (
        f"{ALGORITHM} Credential={credentials.access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )


# The client.


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the signed request (and its credentials' signature) must only
    go to the configured endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201, PLR0913
        raise S3Error(f"{req.get_method()} was redirected ({code}): refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


class Client:
    def __init__(self, bucket: Bucket, timeout: float = 60.0) -> None:
        parsed = urllib.parse.urlsplit(bucket.endpoint)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in LOOPBACK
        ):
            raise S3Error("the endpoint must use https")
        if not parsed.hostname:
            raise S3Error("the endpoint has no host")
        self.bucket = bucket
        self.timeout = timeout
        self._base = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc

    def __repr__(self) -> str:
        return f"s3.Client(bucket={self.bucket.name!r})"

    def _request(
        self,
        method: str,
        key: str = "",
        query: dict[str, str] | None = None,
        body: bytes = b"",
        extra: dict[str, str] | None = None,
    ) -> bytes:
        query = query or {}
        path = (
            "/" + _encode(self.bucket.name) + ("/" + _encode(key, keep_slash=True) if key else "")
        )
        payload = hashlib.sha256(body).hexdigest()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "host": self._host,
            "x-amz-content-sha256": payload,
            "x-amz-date": stamp,
            **(extra or {}),
        }
        headers["authorization"] = authorization(
            self.bucket.credentials,
            self.bucket.region,
            method,
            path,
            query,
            headers,
            payload,
            stamp,
        )
        url = self._base + path + (f"?{canonical_query(query)}" if query else "")
        sent = {k: v for k, v in headers.items() if k != "host"}
        request = urllib.request.Request(  # noqa: S310 (https, or loopback for the tests)
            url, data=body if method == "PUT" else None, headers=sent, method=method
        )
        try:
            with _OPENER.open(request, timeout=self.timeout) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            raise S3Error(f"{method} answered {error.code} {_error_code(error)}".rstrip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", None) or type(error).__name__
            raise S3Error(f"{method} failed: {reason}") from None

    def put(self, key: str, body: bytes) -> None:
        md5 = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()
        self._request(
            "PUT",
            key,
            body=body,
            extra={"content-md5": md5, "content-type": "application/octet-stream"},
        )

    def get(self, key: str) -> bytes:
        return self._request("GET", key)

    def delete(self, key: str) -> None:
        self._request("DELETE", key)

    def list(self, prefix: str) -> list[str]:
        """Every key that starts with `prefix` (all pages)."""
        keys: list[str] = []
        token = ""
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            root = ElementTree.fromstring(self._request("GET", query=query))
            keys += [e.text or "" for e in root.iter(f"{_NS}Key")]
            truncated = (root.findtext(f"{_NS}IsTruncated") or "false") == "true"
            token = root.findtext(f"{_NS}NextContinuationToken") or ""
            if not truncated or not token:
                return keys


def _error_code(error: urllib.error.HTTPError) -> str:
    try:
        root = ElementTree.fromstring(error.read(4096))
    except (ElementTree.ParseError, OSError):
        return ""
    code = root.findtext("Code") or root.findtext(f"{_NS}Code") or ""
    return code if code.isalnum() else ""
