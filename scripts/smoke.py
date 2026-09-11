"""Run with the local API and PostgreSQL started; creates one demo snapshot and run."""

import httpx

with httpx.Client(base_url="http://127.0.0.1:3000/api", timeout=30) as client:
    assert client.get("/health").json() == {"status": "ok"}
    pool = client.get("/sample").json()
    response = client.post("/pools", json=pool)
    response.raise_for_status()
    pool_id = response.json()["id"]
    assert "recent-form-v1" in response.json()["pool"]["projection_method"]
    assert all(p["projected_points"] is not None for p in response.json()["pool"]["players"])
    response = client.post("/optimize", json={"pool_id": pool_id, "locked": ["nova"], "excluded": ["axis"]})
    response.raise_for_status()
    result = response.json()
    assert len(result["lineups"]) == 5
    for row in result["lineups"]:
        ids = {p["id"] for p in row["players"]}
        assert "nova" in ids and "axis" not in ids
        assert row["cost"] <= pool["rules"]["budget"]
    assert client.get(f"/runs/{result['id']}").json() == result
    print("Next.js proxy → FastAPI → PostgreSQL: import, optimize, and saved-run retrieval passed.")
