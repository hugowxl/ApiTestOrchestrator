from fastapi.testclient import TestClient

from app.db.models import MockDataTable, MockDataTableRuntimeState, MockEndpointMapping, MockScenario
from app.db.session import SessionLocal
from app.main import app


client = TestClient(app)


def _get_rows_from_db(table_id: str):
    db = SessionLocal()
    try:
        tbl = db.get(MockDataTable, table_id)
        runtime = db.get(MockDataTableRuntimeState, table_id)
        return tbl.rows_json, runtime.rows_json if runtime else None
    finally:
        db.close()


def test_endpoint_mapping_required_body_fields_and_overlay_update():
    scenario = client.post(
        "/api/v1/mock/scenarios",
        json={"name": "pytest-mapped-overlay", "description": None},
    ).json()
    scenario_id = scenario["id"]

    try:
        table = client.post(
            f"/api/v1/mock/scenarios/{scenario_id}/tables",
            json={
                "table_name": "user_deposit",
                "description": "deposit",
                "schema_json": [{"name": "account_id", "type": "string"}, {"name": "amount", "type": "number"}],
                "rows_json": [{"account_id": "u1", "amount": 100}],
            },
        ).json()
        table_id = table["id"]

        mapping = client.post(
            f"/api/v1/mock/scenarios/{scenario_id}/mappings",
            json={
                "method": "PUT",
                "path": "/api/deposits/{account_id}",
                "action": "update",
                "table_id": table_id,
                "key_field": "account_id",
                "required_body_fields": ["amount"],
                "response_template_json": None,
            },
        ).json()
        mapping_id = mapping["id"]
        assert mapping_id

        # 1) 缺少 required field：400
        r1 = client.put(
            f"/mock-mapped/{scenario_id}/api/deposits/u1",
            json={},
        )
        assert r1.status_code == 400

        # 2) 正确：200，并更新 overlay
        r2 = client.put(
            f"/mock-mapped/{scenario_id}/api/deposits/u1",
            json={"amount": 999},
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["amount"] == 999

        base_rows, runtime_rows = _get_rows_from_db(table_id)
        assert base_rows == [{"account_id": "u1", "amount": 100}]
        assert runtime_rows == [{"account_id": "u1", "amount": 999}]

        # 3) reset：overlay 恢复初始
        client.post(f"/api/v1/mock/scenarios/{scenario_id}/reset")
        _, runtime_rows2 = _get_rows_from_db(table_id)
        assert runtime_rows2 == [{"account_id": "u1", "amount": 100}]
    finally:
        client.delete(f"/api/v1/mock/scenarios/{scenario_id}")

