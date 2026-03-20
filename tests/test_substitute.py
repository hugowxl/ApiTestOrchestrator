import os

from app.services.test_executor import substitute_object, substitute_vars


def test_substitute_vars_context():
    assert substitute_vars("/api/{{id}}", {"id": "1"}) == "/api/1"


def test_substitute_vars_env(monkeypatch):
    monkeypatch.setenv("TOKEN", "abc")
    assert substitute_vars("Bearer {{TOKEN}}", {}) == "Bearer abc"


def test_substitute_object_nested():
    ctx = {"a": "x"}
    assert substitute_object({"q": "{{a}}", "n": 1}, ctx) == {"q": "x", "n": 1}
