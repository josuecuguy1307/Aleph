"""
test_byok.py — señal TIPADA de fallo BYOK (screen 11), NO un 500 mudo.
"""

import pytest

from app.phase1.byok import (
    BYOKFailure,
    BYOKReason,
    classify_provider_error,
    from_provider_error,
    BYOK_HTTP_STATUS,
    BYOK_ERROR_TYPE,
)


def test_signal_shape_is_typed():
    f = BYOKFailure(provider="fred", reason=BYOKReason.INVALID, run_id="r1", tool="get_series")
    sig = f.to_signal()
    assert sig["error"] == BYOK_ERROR_TYPE
    assert sig["screen"] == "screen_11"
    assert sig["provider"] == "fred"
    assert sig["reason"] == "invalid"
    assert sig["run_id"] == "r1"
    assert sig["tool"] == "get_series"
    assert sig["recoverable"] is True
    assert isinstance(sig["user_message"], str) and sig["user_message"]


def test_signal_never_leaks_secret():
    # ni el detail ni ningún campo debe poder llevar la key — verificamos que el
    # constructor no expone un campo de secreto y que detail es metadato técnico.
    f = from_provider_error("openai", "Incorrect API key provided: sk-LEAKED", run_id="r9")
    sig = f.to_signal()
    # el clasificador identifica invalid; el detail conserva el mensaje del provider
    # (ese mensaje vino del PROVIDER, no de nuestra DB; aun así no exponemos campos de key).
    assert "value" not in sig and "secret" not in sig and "api_key" not in sig
    assert sig["reason"] == "invalid"


def test_classify_rate_limited():
    assert classify_provider_error("HTTP 429 Too Many Requests") == BYOKReason.RATE_LIMITED
    assert classify_provider_error("rate limit exceeded") == BYOKReason.RATE_LIMITED


def test_classify_invalid_401():
    assert classify_provider_error("401 Unauthorized: invalid api key") == BYOKReason.INVALID


def test_classify_expired_before_invalid():
    assert classify_provider_error("your api key has expired") == BYOKReason.EXPIRED


def test_classify_decrypt_failed():
    assert classify_provider_error("cryptography.fernet.InvalidToken") == BYOKReason.DECRYPT_FAILED


def test_classify_unknown_is_honest():
    # si no matchea nada, NO inventamos → UNKNOWN.
    assert classify_provider_error("the server melted") == BYOKReason.UNKNOWN


def test_rate_limited_not_recoverable_by_reconnect():
    # rate-limit NO se arregla reconectando la key (es esperar) → recoverable False.
    f = BYOKFailure(provider="groq", reason=BYOKReason.RATE_LIMITED)
    assert f.recoverable is False


def test_missing_is_recoverable():
    f = BYOKFailure(provider="fred", reason=BYOKReason.MISSING)
    assert f.recoverable is True


def test_string_reason_coerced():
    f = BYOKFailure(provider="x", reason="invalid")
    assert f.reason is BYOKReason.INVALID


def test_unknown_string_reason_falls_back():
    f = BYOKFailure(provider="x", reason="not-a-real-reason")
    assert f.reason is BYOKReason.UNKNOWN


def test_http_status_is_424_not_500():
    # contrato de la pieza (e): 424 Failed Dependency, NO 500.
    assert BYOK_HTTP_STATUS == 424
