from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_mock_scenario_reset_restores_initial_rows_json():
    # 1) 创建场景
    scenario = client.post(
        "/api/v1/mock/scenarios",
        json={"name": "pytest-reset-scenario", "description": None},
    ).json()
    scenario_id = scenario["id"]

    try:
        # 2) 创建数据表（此时 rows_json 会写入 reset_rows_json 快照）
        table = client.post(
            f"/api/v1/mock/scenarios/{scenario_id}/tables",
            json={
                "table_name": "user_balance",
                "description": "pytest table",
                "schema_json": [{"name": "id", "type": "string"}, {"name": "balance", "type": "number"}],
                "rows_json": [{"id": "u1", "balance": 100}],
            },
        ).json()
        original_rows = table["rows_json"]

        # 3) 外部 state 覆盖运行时数据（不应影响 reset 快照）
        client.patch(
            f"/api/v1/mock/scenarios/{scenario_id}/state",
            json={
                "tables": [
                    {
                        "table_name": "user_balance",
                        "rows_json": [{"id": "u1", "balance": 50}],
                    }
                ]
            },
        )

        detail = client.get(f"/api/v1/mock/scenarios/{scenario_id}").json()
        user_balance = [t for t in detail["tables"] if t["table_name"] == "user_balance"][0]
        assert user_balance["rows_json"] == [{"id": "u1", "balance": 50}]

        # 4) reset 回到最初版本
        client.post(f"/api/v1/mock/scenarios/{scenario_id}/reset")

        detail2 = client.get(f"/api/v1/mock/scenarios/{scenario_id}").json()
        user_balance2 = [t for t in detail2["tables"] if t["table_name"] == "user_balance"][0]
        assert user_balance2["rows_json"] == original_rows
    finally:
        client.delete(f"/api/v1/mock/scenarios/{scenario_id}")

