import json

from app.services.openapi_normalizer import load_spec, normalize_spec


def test_normalize_minimal_oas3():
    raw = {
        "openapi": "3.0.0",
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    b = json.dumps(raw).encode()
    spec = load_spec(b)
    eps = normalize_spec(spec)
    assert len(eps) == 1
    assert eps[0]["method"] == "GET"
    assert eps[0]["path"] == "/items"
