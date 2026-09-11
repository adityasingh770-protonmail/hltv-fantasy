"""API persistence tests run against a temporary DB; PostgreSQL is also smoke-tested locally."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import main
from backend.db import Base
from backend.schemas import PoolImport


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "Session", sessionmaker(engine))
    with TestClient(main.app) as client:
        yield client
    engine.dispose()


@pytest.mark.parametrize("filename", ["sample-pool.json", "sample-history-pool.json"])
def test_import_optimize_and_retrieve(client, filename):
    pool = json.loads((Path("data") / filename).read_text())
    response = client.post("/pools", json=pool)
    assert response.status_code == 201
    pool_id = response.json()["id"]
    result = client.post("/optimize", json={"pool_id": pool_id})
    assert result.status_code == 200
    assert len(result.json()["lineups"]) == 5
    assert client.get(f"/runs/{result.json()['id']}").json() == result.json()
    assert client.get("/pools").json()[0]["pool"] == PoolImport.model_validate(pool).model_dump(mode="json")


def test_unverified_real_pool_cannot_generate(client):
    pool = json.loads(Path("data/sample-pool.json").read_text())
    pool["is_demo"] = False
    pool_id = client.post("/pools", json=pool).json()["id"]
    response = client.post("/optimize", json={"pool_id": pool_id})
    assert response.status_code == 422
    assert "Verify" in response.json()["detail"]


def test_missing_pool_and_bad_import(client):
    assert client.post("/optimize", json={"pool_id": "missing"}).status_code == 404
    assert client.post("/pools", json={"players": []}).status_code == 422


def test_past_deadline_is_analysis_only(client):
    pool = json.loads(Path("data/sample-pool.json").read_text())
    pool.update(is_demo=False, rules_verified=True, lock_at="2020-01-01T00:00:00Z")
    pool_id = client.post("/pools", json=pool).json()["id"]
    result = client.post("/optimize", json={"pool_id": pool_id}).json()
    assert any("lock time has passed" in w for w in result["warnings"])
