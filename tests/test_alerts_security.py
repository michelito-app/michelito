"""Bank alerts from untrusted senders: authentication, size and nesting limits, capped
failure fingerprints and per-message errors in the sync."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from michelito import alerts, charset, db, extract, gmail
from michelito.alerts import authres, inspect, popular_purchase
from michelito.alerts.common import (
    FIELD_MAX,
    FINGERPRINT_MAX,
    HTML_MAX,
    AlertEmail,
    AlertParseError,
    failure_fingerprint,
    failure_json,
    read_html,
)
from michelito.analysis import live_store
from michelito.config import DEFAULT_SOURCES, find_source
from michelito.gmail import MailMessage
from tests import alert_samples as samples
from tests.fakes import FakeClient
from tests.live_helpers import NOW, known_card


def _parse_with(auth: tuple[str, ...]) -> None:
    popular_purchase.parse(samples.alert_email(auth=auth))


@pytest.mark.parametrize(
    "auth",
    [
        (samples.SIGNED,),
        (samples.SIGNED_SUBDOMAIN,),
        (samples.SIGNED, samples.DKIM_FAILED),
        (samples.MULTIPLE_CLAUSES,),
    ],
    ids=["signed", "subdomain", "lower-header-ignored", "multiple-clauses"],
)
def test_an_alert_signed_by_the_bank_is_parsed(auth: tuple[str, ...]) -> None:
    _parse_with(auth)


@pytest.mark.parametrize(
    "auth",
    [
        (),
        (samples.DKIM_FAILED,),
        (samples.OTHER_SIGNER,),
        (samples.UNTRUSTED_RECEIVER,),
        # A sender can add a passing header below the receiver's: only the topmost counts.
        (samples.DKIM_FAILED, samples.FORGED),
        (samples.OTHER_SIGNER, samples.FORGED),
        # Only the topmost header is read: an untrusted one on top is a failure, even with a
        # (forged) header naming the trusted receiver below it.
        (samples.UNTRUSTED_RECEIVER, samples.FORGED),
        (samples.NO_DMARC,),
        (samples.DMARC_OTHER_FROM,),
        (samples.PASS_IN_COMMENT,),
        (samples.SEMICOLON_IN_COMMENT,),
        (samples.SEMICOLON_IN_QUOTES,),
        (samples.QUOTED_DOMAIN,),
        (samples.EVIL_WITH_COMMENT,),
        (samples.VERSIONED_METHOD,),
        (samples.ID_IN_COMMENT,),
        # Gmail's own header does not parse: never fall back to a lower (forgeable) one.
        (samples.UNCLOSED_COMMENT, samples.FORGED),
        (
            "mx.google.com; dkim=pass header.d=evilpopularenlinea.com; dmarc=pass "
            "header.from=evilpopularenlinea.com",
        ),  # fmt: skip
        (
            "mx.google.com; dkim=pass header.d=popularenlinea.com header.d=x.example; "
            "dmarc=pass header.from=popularenlinea.com",
        ),  # fmt: skip
    ],
    ids=[
        "missing",
        "fail",
        "other-domain",
        "untrusted-receiver",
        "forged-lower",
        "forged-other",
        "untrusted-top-forged-below",
        "no-dmarc",
        "dmarc-other-from",
        "pass-in-comment",
        "semicolon-in-comment",
        "semicolon-in-quotes",
        "quoted-domain",
        "evil-with-comment",
        "versioned-method",
        "id-in-comment",
        "unparsable-top",
        "look-alike",
        "repeated-property",
    ],
)
def test_without_the_banks_signature_it_is_never_parsed(auth: tuple[str, ...]) -> None:
    with pytest.raises(AlertParseError) as caught:
        _parse_with(auth)
    assert caught.value.field == "authentication"


def test_the_parser_reads_clauses_and_properties_strictly() -> None:
    found, verdict = authres.parse(samples.MULTIPLE_CLAUSES)
    assert found == "mx.google.com"
    assert verdict.dkim == ("other.example", "popularenlinea.com")
    assert verdict.dmarc_from == ("popularenlinea.com",)
    assert authres.parse(samples.PASS_IN_COMMENT)[1].dkim == ()
    assert authres.parse(samples.EVIL_WITH_COMMENT)[1].dkim == ("evil.example",)
    assert authres.parse(samples.UNCLOSED_COMMENT) == (None, authres.NONE)
    assert authres.authserv_id("(note) mx.google.com 1; none") == "mx.google.com"


def test_the_trusted_receiver_is_configurable() -> None:
    other = samples.UNTRUSTED_RECEIVER
    email = samples.alert_email(auth=(other,))
    trusting = AlertEmail(**{**email.__dict__, "trusted_authserv": ("mx.attacker.example",)})
    popular_purchase.parse(trusting)  # the hosted path names its own receiver


def test_the_hosted_path_passes_the_verifiers_verdict() -> None:
    email = samples.alert_email(auth=())
    both = authres.Verdict(dkim=("popularenlinea.com",), dmarc_from=("popularenlinea.com",))
    popular_purchase.parse(AlertEmail(**{**email.__dict__, "verified": both}))
    for partial in (authres.Verdict(dkim=("popularenlinea.com",)), authres.NONE):
        with pytest.raises(AlertParseError):
            popular_purchase.parse(AlertEmail(**{**email.__dict__, "verified": partial}))


def test_a_raw_message_keeps_its_headers_in_order() -> None:
    raw = samples.raw_alert(auth=(samples.DKIM_FAILED, samples.FORGED))
    email = alerts.from_bytes(raw)
    assert email.auth_results == (samples.DKIM_FAILED, samples.FORGED)
    report = inspect.describe(raw)
    assert report["parsed"] is False
    assert report["fields"]["authentication"] is False  # type: ignore[index]


def test_an_unsigned_alert_is_stored_as_an_auth_failure_only(tmp_path: Path) -> None:
    with db.connect(tmp_path / "m.db") as conn:
        known_card(conn)
        email = samples.alert_email("a1", auth=(samples.OTHER_SIGNER,))
        with conn:
            assert live_store.record(conn, email, "popular_alerts", NOW) == "failed"
        row = conn.execute("SELECT * FROM alerts").fetchone()
        assert json.loads(row["failure"])["failed_field"] == "authentication"
        assert row["amount_cents"] is None and row["merchant"] is None


def test_an_oversized_body_is_rejected_before_parsing() -> None:
    with pytest.raises(AlertParseError) as caught:
        read_html("<p>" + "x" * HTML_MAX + "</p>")
    assert caught.value.field == "size"
    big = samples.alert_email(html=samples.alert_html() + " " * HTML_MAX)
    with pytest.raises(AlertParseError):
        popular_purchase.parse(big)


def test_unclosed_cells_stay_linear() -> None:
    # Thousands of unclosed cells (and deep tables) must not make every text append grow.
    hostile = "<table><tr>" + "<td>x" * 20_000 + "</table>" + "<table><tr><td>" * 500
    start = time.perf_counter()
    document = read_html(hostile)
    assert time.perf_counter() - start < 2
    assert len(document.tables[0].rows[0]) == 20_000
    assert len(document.tables) <= 9


def test_implicitly_closed_cells_still_read_the_alert() -> None:
    html = samples.alert_html().replace("</td>", "").replace("</th>", "")
    found = popular_purchase.parse(samples.alert_email(html=html))
    assert found.merchant == "SUPERMERCADO FICTICIO"


def test_fingerprint_fields_and_size_are_capped() -> None:
    sender = "x@" + "a" * 5000 + ".example.com"
    email = samples.alert_email(sender=sender, html="<p></p>")
    found = failure_fingerprint(email, "t" * 5000, AlertParseError("table"))
    assert all(len(value) <= FIELD_MAX for value in found.values())
    assert len(failure_json(found)) <= FINGERPRINT_MAX
    escapes = {"k": '"' * FIELD_MAX, "j": "\u0001" * FIELD_MAX, "l": "\\" * FIELD_MAX}
    assert len(failure_json(escapes)) <= FINGERPRINT_MAX


class _Broken(FakeClient):
    def get_message(self, message_id: str) -> MailMessage:
        if message_id == "bad":
            raise RuntimeError("boom")
        return super().get_message(message_id)


def test_one_bad_message_does_not_stop_the_sync(tmp_path: Path) -> None:
    good = MailMessage(
        message_id="good",
        sender=samples.SENDER,
        subject=samples.SUBJECT,
        received_at=datetime(2026, 2, 14, 15, tzinfo=UTC),
        body_text="",
        attachments=(),
        body_html=samples.alert_html(),
        auth_results=(samples.SIGNED,),
    )
    bad = MailMessage("bad", "", "", good.received_at, "", ())
    source = find_source("popular_alerts", DEFAULT_SOURCES)
    with db.connect(tmp_path / "m.db") as conn:
        known_card(conn)
        client = _Broken((bad, {}), (good, {}))
        stats = extract.extract_source(conn, client, source, tmp_path / "raw")
        assert stats.new_messages == 2
        rows = dict(conn.execute("SELECT message_id, status FROM alerts").fetchall())
        assert rows == {"bad": "failed", "good": "provisional"}
        failure = json.loads(
            conn.execute("SELECT failure FROM alerts WHERE message_id = 'bad'").fetchone()[0]
        )
        assert failure == {
            "alert_type": "unknown",
            "error": "RuntimeError",
            "failed_field": "error",
        }


# spanish-data: begin (accented bank wording in a windows-1252 part)
_ACCENTED = {"currency": samples.DOLLARS, "merchant": "CAFÉ ÑAME FICTICIO"}
# spanish-data: end


@pytest.mark.parametrize("declared", ["windows-1252", None, "utf-8"])
def test_a_windows_1252_part_is_decoded_without_replacement_characters(
    declared: str | None,
) -> None:
    raw = samples.raw_mislabeled(samples.alert_html(**_ACCENTED), declared)
    email = alerts.from_bytes(raw)
    assert "\ufffd" not in email.html
    found = popular_purchase.parse(email)
    assert found.currency == "USD"
    assert found.merchant == _ACCENTED["merchant"]


def test_both_parts_in_windows_1252_are_read_with_their_charset() -> None:
    raw = samples.raw_alert(charset="windows-1252", **_ACCENTED)
    email = alerts.from_bytes(raw)
    assert "\ufffd" not in email.html + email.text
    assert popular_purchase.parse(email).merchant == _ACCENTED["merchant"]
    assert inspect.describe(raw)["parsed"] is True


def test_the_gmail_part_uses_its_declared_charset() -> None:
    import base64  # noqa: PLC0415

    html = samples.alert_html(**_ACCENTED)
    data = base64.urlsafe_b64encode(html.encode("cp1252")).decode().rstrip("=")
    part = {
        "mimeType": "text/html",
        "headers": [{"name": "Content-Type", "value": 'text/html; charset="windows-1252"'}],
        "body": {"data": data},
    }
    message = gmail.message_from_api(
        {"id": "x", "internalDate": "1792005355000", "payload": {"headers": [], "parts": [part]}}
    )
    assert message.body_html == html
    undeclared = {**part, "headers": []}
    again = gmail.message_from_api(
        {"id": "x", "internalDate": "1792005355000", "payload": {"parts": [undeclared]}}
    )
    assert again.body_html == html  # not UTF-8: falls back to windows-1252, no "\ufffd"


def test_decode_never_inserts_replacement_characters() -> None:
    assert charset.decode("Dólar".encode("cp1252")) == "Dólar"  # spanish-data
    assert charset.decode("Dólar".encode()) == "Dólar"  # spanish-data
    assert charset.decode("Dólar".encode("cp1252"), "utf-8") == "Dólar"  # spanish-data
    assert charset.decode(b"\x81\x8d", "bogus-charset") == "\x81\x8d"
