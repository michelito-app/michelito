"""What the AI connector hides (`hosted.redact`). Every number and address is made up."""

from __future__ import annotations

from michelito.hosted.redact import mask, mask_text, unmask_key


def test_long_numbers_keep_their_last_four_digits() -> None:
    assert mask_text("popular:savings:111111111") == "popular:savings:••1111"
    assert mask_text("4111 1111 1111 1234") == "••1234"
    assert mask_text("REF 11111111111111111111111 COLMADO") == "REF ••1111 COLMADO"
    assert mask_text("tel 999-999-9999") == "tel ••9999"
    assert mask_text("tel 999.999.9999") == "tel ••9999"
    assert mask_text("1111/1111/9999") == "••9999"


def test_a_number_that_starts_like_a_date_is_still_masked() -> None:
    assert mask_text("2026-11 1111 1111") == "••1111"
    assert mask_text("0000-11-1111111111") == "••1111"


def test_days_months_amounts_and_short_numbers_stay() -> None:
    for text in (
        "2026-11-23",
        "2026-11",
        "2026-11-23T10:00:00",
        "1,200.50",
        "12,345.67",
        "****-1234",
        "15/12",
        "15/12/2026",
        "del 2026-01-01 al 2026-01-31",
    ):
        assert mask_text(text) == text


def test_emails_are_hidden() -> None:
    assert mask_text("paid by ana@example.com") == "paid by [email]"


def test_mask_walks_json_and_keeps_fingerprints() -> None:
    given = {
        "fingerprint": "12345678abcdef",
        "email": "ana@example.com",
        "items": [{"account": "bhd:savings:987650000", "amount_cents": 123456789}],
    }

    found = mask(given)

    assert found == {
        "fingerprint": "12345678abcdef",
        "items": [{"account": "bhd:savings:••0000", "amount_cents": 123456789}],
    }
    assert given["email"] == "ana@example.com"  # the given value is not changed


def test_keys_are_masked_too() -> None:
    assert mask({"111111111": 5}) == {"••1111": 5}


def test_unmask_key_finds_the_one_real_key() -> None:
    keys = ["bhd:savings:987650000", "bhd:credit_card"]

    assert unmask_key("bhd:savings:••0000", keys) == "bhd:savings:987650000"
    assert unmask_key("bhd:credit_card", keys) == "bhd:credit_card"
    assert unmask_key("bhd:savings:••9999", keys) is None
    assert unmask_key("x:••1111", ["x:91111", "x:81111"]) is None  # ambiguous
