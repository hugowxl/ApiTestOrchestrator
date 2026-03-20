from app.schemas.test_case_schema import (
    normalize_llm_test_design,
    validate_llm_test_design,
    validate_llm_test_design_normalized,
)


def test_validate_llm_ok():
    obj = {
        "endpoint_summary": "x",
        "dependencies": [],
        "test_cases": [
            {
                "id": "1",
                "name": "n",
                "steps": [
                    {
                        "method": "GET",
                        "path": "/p",
                        "assertions": [{"type": "status_code", "value": 200}],
                    }
                ],
            }
        ],
    }
    ok, errs = validate_llm_test_design(obj)
    assert ok and not errs


def test_validate_llm_fail():
    ok, errs = validate_llm_test_design({"endpoint_summary": "x"})
    assert not ok
    assert errs


def test_validate_empty_test_cases_fail():
    ok, errs = validate_llm_test_design(
        {"endpoint_summary": "x", "dependencies": ["u"], "test_cases": []},
    )
    assert not ok
    assert errs and "test_cases" in errs[0]


def test_normalize_dependencies_string_then_valid():
    raw = {
        "endpoint_summary": "s",
        "dependencies": "auth",
        "test_cases": [
            {
                "id": "1",
                "name": "n",
                "variables": {"x": 42, "y": True},
                "steps": [
                    {
                        "method": "GET",
                        "path": "/p",
                        "body_type": "JSON",
                        "assertions": [{"type": "StatusCode", "value": 200}],
                    }
                ],
            }
        ],
    }
    ok, errs, n = validate_llm_test_design_normalized(raw)
    assert ok, errs
    assert n["dependencies"] == ["auth"]
    assert n["test_cases"][0]["variables"] == {"x": "42", "y": "True"}
    assert n["test_cases"][0]["steps"][0]["body_type"] == "json"
    assert n["test_cases"][0]["steps"][0]["assertions"][0]["type"] == "status_code"


def test_normalize_extract_from_alias():
    raw = {
        "endpoint_summary": "s",
        "dependencies": ["x"],
        "test_cases": [
            {
                "id": "1",
                "name": "n",
                "steps": [
                    {
                        "method": "GET",
                        "path": "/p",
                        "extract": [{"name": "t", "from": "response_body", "path": "$.id"}],
                        "assertions": [{"type": "status_code", "value": 200}],
                    }
                ],
            }
        ],
    }
    n = normalize_llm_test_design(raw)
    assert n["test_cases"][0]["steps"][0]["extract"][0]["from"] == "json_body"
    ok, errs = validate_llm_test_design(n)
    assert ok, errs
