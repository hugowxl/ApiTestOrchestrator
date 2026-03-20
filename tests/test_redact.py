from app.utils.redact import redact_headers, redact_for_log


def test_redact_authorization():
    h = redact_headers({"Authorization": "Bearer secret-token-value", "X-Other": "ok"})
    assert "***" in h["Authorization"]
    assert h["X-Other"] == "ok"


def test_redact_log():
    s = redact_for_log('{"password":"secret123"}')
    assert "secret123" not in s
