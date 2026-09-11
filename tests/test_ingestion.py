import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend import ingestion, main
from backend.db import Base, IngestionResource, Snapshot


@pytest.fixture
def index():
    return json.loads(Path("tests/fixtures/hltv-index.json").read_text())


@pytest.fixture
def overview():
    return json.loads(Path("tests/fixtures/hltv-overview.json").read_text())


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ingestion.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


def test_live_index_matches_observed_hltv(index):
    events = ingestion.parse_events(index)["events"]
    assert [e["id"] for e in events] == [650, 651, 652, 653]
    assert all(e["status"] == "live" and e["entry_open"] is False for e in events)
    assert [e["category"] for e in events] == ["season", "partner", "partner", "partner"]


def test_disabled_and_unknown_states(index):
    event = index["monthlyEvents"][-1]["events"]
    # Add an enabled future state without guessing its entry availability.
    sample = deepcopy(index["monthlyEvents"][0]["events"][0])
    sample.update(fantasyId={"id": 700}, state={"type": "EventState.FutureVariant"})
    event.append(sample)
    found = next(e for e in ingestion.parse_events(index)["events"] if e["id"] == 700)
    assert found["status"] == "unknown" and found["entry_open"] is None
    sample["enabled"] = False
    assert all(e["id"] != 700 for e in ingestion.parse_events(index)["events"])
    with pytest.raises(KeyError):
        ingestion.parse_events({})


def test_featured_prices_are_not_fabricated_and_never_optimizer_ready(overview):
    data = ingestion.parse_overview(overview, 650)
    assert data["pool_complete"] is False and data["optimizer_ready"] is False
    assert data["lock_at"] is None
    players = {p["name"]: p for p in data["players"]}
    assert players["d1Ledez"]["price"] == 201000
    assert players["JamYoung"]["price"] is None
    assert len(data["players"]) == len({p["id"] for p in data["players"]})
    assert not any("projected_points" in p for p in data["players"])
    with pytest.raises(ValueError, match="different event"):
        ingestion.parse_overview(overview, 651)


def test_cache_survives_failure_and_success_replaces_it(sessions, monkeypatch, index):
    calls = []

    def fetch(path):
        calls.append(path)
        return index

    monkeypatch.setattr(ingestion, "fetch_json", fetch)
    first = ingestion.read_resource(sessions)
    assert first["available"] and not first["stale"]
    assert ingestion.read_resource(sessions)["observed_on"] == first["observed_on"]
    ingestion.read_resource(sessions, refresh=True)
    assert len(calls) == 1  # Forced refresh also respects the per-resource cooldown.
    with sessions() as session:
        row = session.get(IngestionResource, "events")
        row.attempted_at = datetime.now(UTC) - timedelta(minutes=20)
        row.observed_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()
    monkeypatch.setattr(ingestion, "fetch_json", lambda _: {})
    failed = ingestion.read_resource(sessions)
    assert failed["events"] == first["events"]
    assert failed["stale"] and failed["error"] and failed["available"]
    with sessions() as session:
        row = session.get(IngestionResource, "events")
        row.attempted_at = datetime.now(UTC) - timedelta(minutes=2)
        session.commit()
    monkeypatch.setattr(ingestion, "fetch_json", fetch)
    recovered = ingestion.read_resource(sessions, refresh=True)
    assert not recovered["stale"] and recovered["error"] is None


def test_no_cache_failure_does_not_fallback_to_static_events(sessions, monkeypatch):
    def fail(_):
        raise ingestion.IngestionError("HLTV unavailable")

    monkeypatch.setattr(ingestion, "fetch_json", fail)
    result = ingestion.read_resource(sessions)
    assert result["events"] == [] and result["observed_on"] is None
    assert not result["available"] and result["stale"]


def test_api_ingestion_is_separate_from_optimizer_pools(sessions, monkeypatch, index, overview):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "Session", sessions)
    monkeypatch.setattr(ingestion, "fetch_json", lambda path: index if path == "/fantasy/json" else overview)
    with TestClient(main.app) as client:
        assert len(client.get("/events").json()["events"]) == 4
        assert client.post("/events/refresh").status_code == 200
        assert client.get("/events/650").json()["optimizer_ready"] is False
        assert client.post("/events/650/refresh").json()["event_id"] == 650
        assert client.get("/events/-1").status_code == 422
        assert client.get("/pools").json() == []
    with sessions() as session:
        assert session.scalar(select(Snapshot)) is None


@pytest.mark.parametrize(
    "status,body",
    [(403, "blocked"), (429, "rate limited"), (200, "<html>challenge</html>"), (302, "redirect")],
)
def test_http_rejects_blocking_html_and_redirects(monkeypatch, status, body):
    client_type = httpx.Client
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, text=body)

    monkeypatch.setattr(
        ingestion.httpx, "Client", lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw)
    )
    with pytest.raises(ingestion.IngestionError):
        ingestion.fetch_json("/fantasy/json")
    assert len(requests) == 1


def test_http_retries_transient_failure_and_bounds_response(monkeypatch):
    client_type = httpx.Client
    responses = iter([httpx.Response(503), httpx.Response(200, json={"ok": True})])
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        ingestion.httpx,
        "Client",
        lambda **kw: client_type(transport=httpx.MockTransport(lambda _: next(responses)), **kw),
    )
    assert ingestion.fetch_json("/fantasy/json") == {"ok": True}
    responses = iter([httpx.Response(200, text="x" * (ingestion.MAX_BYTES + 1))])
    with pytest.raises(ingestion.IngestionError, match="2 MB"):
        ingestion.fetch_json("/fantasy/json")
