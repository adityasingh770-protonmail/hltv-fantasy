"""Read-only adapter for HLTV's public fantasy JSON, verified 2026-09-11.

Overview players are featured subsets. Never turn them into optimizer pools.
"""

import hashlib
import json
import threading
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from backend.db import IngestionResource

BASE = "https://www.hltv.org"
TTL_SECONDS = 900
RETRY_SECONDS = 60
MAX_BYTES = 2_000_000
_sync_lock = threading.Lock()


class IngestionError(Exception):
    pass


def fetch_json(path: str) -> dict:
    # Paths are constructed by this adapter, never accepted as user-supplied URLs.
    with httpx.Client(
        timeout=10,
        follow_redirects=False,
        headers={
            "User-Agent": "HLTVFantasyLab/0.1",
            "Accept": "application/json",
        },
    ) as client:
        for attempt in range(2):
            try:
                with client.stream("GET", BASE + path) as response:
                    if response.status_code in (401, 403, 429):
                        raise IngestionError(
                            f"HLTV blocked or rate-limited this request (HTTP {response.status_code}). "
                            "The last successful data is retained; retry later."
                        )
                    if response.status_code >= 500 and attempt == 0:
                        time.sleep(0.5)
                        continue
                    if response.status_code != 200:
                        raise IngestionError(f"HLTV returned HTTP {response.status_code}.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise IngestionError("HLTV response exceeded the 2 MB safety limit.")
                    try:
                        data = json.loads(body)
                    except (ValueError, UnicodeError) as exc:
                        raise IngestionError(
                            "HLTV returned a page instead of JSON; refresh is unavailable."
                        ) from exc
                    if not isinstance(data, dict):
                        raise IngestionError("HLTV's response format changed; adapter update required.")
                    return data
            except httpx.TransportError as exc:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise IngestionError(
                    "Could not connect to HLTV. The last successful data is retained."
                ) from exc
    raise IngestionError("HLTV refresh failed.")


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid HLTV identifier")
    return value


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError("Invalid HLTV label")
    return value.strip()


def parse_events(data: dict) -> dict:
    events = {}
    for key, category in (("monthlyEvents", "season"), ("nonSeasonOpenMonthlyEvents", "partner")):
        months = data[key]
        if not isinstance(months, list):
            raise TypeError("Missing event groups")
        for month in months:
            for event in month["events"]:
                if type(event["enabled"]) is not bool:
                    raise ValueError("Invalid enabled flag")
                if not event["enabled"]:
                    continue
                state = label(event["state"]["type"]).rsplit(".", 1)[-1]
                if state == "FinishedEvent":
                    continue
                event_id = positive_id(event["fantasyId"]["id"])
                # Only the observed LiveEvent variant has a verified interpretation.
                # Unknown future variants remain visible without claiming entries are open.
                events.setdefault(
                    event_id,
                    {
                        "id": event_id,
                        "name": label(event["name"]),
                        "category": category,
                        "status": "live" if state == "LiveEvent" else "unknown",
                        "source_state": state,
                        "enabled": True,
                        "entry_open": False if state == "LiveEvent" else None,
                        "url": f"{BASE}/fantasy/{event_id}/overview",
                    },
                )
    return {"events": sorted(events.values(), key=lambda e: e["id"]), "source_url": BASE + "/fantasy/json"}


def parse_overview(data: dict, event_id: int) -> dict:
    if positive_id(data["topMenuData"]["fantasyId"]["id"]) != event_id:
        raise ValueError("HLTV returned a different event")
    for key in ("isGameStarted", "gameFinished"):
        if type(data[key]) is not bool:
            raise ValueError("Missing game status")
    players = {}
    for key in ("bestValueForMoneyPlayers", "mostPickedPlayers", "topRatedPlayers"):
        rows = data[key]
        if not isinstance(rows, list):
            raise TypeError("Invalid featured player list")
        for row in rows:
            player = row if key == "topRatedPlayers" else row["player"]
            player_id = str(positive_id(player["fantasyPlayerId"]["playerId"]))
            stats = player["stats"]
            if not isinstance(stats, dict) or not all(
                isinstance(k, str) and isinstance(v, (str, type(None))) for k, v in stats.items()
            ):
                raise ValueError("Invalid player statistics")
            normalized = players.setdefault(
                player_id,
                {
                    "id": player_id,
                    "name": label(player["name"]),
                    "team": label(player["team"]["name"]),
                    "price": None,
                    "stats": stats,
                    "featured_in": [],
                },
            )
            normalized["featured_in"].append(key)
            if key == "bestValueForMoneyPlayers":
                price = positive_id(row["price"])
                if price > 10_000_000:
                    raise ValueError("Invalid draft price")
                normalized["price"] = price
    scoring = {}
    for key in (
        "roleFailPoints",
        "roleSmallBonus",
        "roleMaxBonus",
        "failBoost",
        "succeedBoost",
        "teamWonPoints",
        "teamLostPoints",
    ):
        if type(data[key]) is not int:
            raise ValueError("Invalid scoring rule")
        scoring[key] = data[key]
    return {
        "event_id": event_id,
        "event_name": label(data["eventName"]),
        "source_url": f"{BASE}/fantasy/{event_id}/overview/json",
        "status": "finished" if data["gameFinished"] else "live" if data["isGameStarted"] else "not_started",
        "entry_open": False if data["isGameStarted"] or data["gameFinished"] else None,
        "lock_at": None,
        "players": list(players.values()),
        "scoring": scoring,
        "pool_complete": False,
        "optimizer_ready": False,
        "limitations": [
            "HLTV's overview contains featured players only; this is not the complete draft pool.",
            "Only explicitly supplied draft prices are recorded. Missing prices remain unknown.",
            "A complete pool, verified roster rules, and projections are required for optimization.",
        ],
    }


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def read_resource(session_factory, event_id: int | None = None, refresh: bool = False):
    key = "events" if event_id is None else f"event:{positive_id(event_id)}"
    path = "/fantasy/json" if event_id is None else f"/fantasy/{event_id}/overview/json"
    # Serialize refreshes within a worker, including the first cache insert.
    with _sync_lock, session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            # Share the cooldown across API workers and the optional ingestion worker.
            lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        now = datetime.now(UTC)
        row = session.get(IngestionResource, key)
        age = (now - _utc(row.observed_at)).total_seconds() if row and row.observed_at else float("inf")
        attempt_age = (now - _utc(row.attempted_at)).total_seconds() if row else float("inf")
        if (refresh or age >= TTL_SECONDS) and attempt_age >= RETRY_SECONDS:
            if row is None:
                row = IngestionResource(key=key)
                session.add(row)
            row.attempted_at = now
            try:
                raw = fetch_json(path)
                payload = parse_events(raw) if event_id is None else parse_overview(raw, event_id)
                payload["content_sha256"] = hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest()
                row.payload, row.observed_at, row.error = payload, datetime.now(UTC), None
            except (IngestionError, KeyError, TypeError, ValueError, AttributeError) as exc:
                row.error = (
                    str(exc)
                    if isinstance(exc, IngestionError)
                    else (
                        "HLTV's data format changed or is incomplete; the last successful data is retained."
                    )
                )
            session.commit()
        age = (datetime.now(UTC) - _utc(row.observed_at)).total_seconds() if row.observed_at else float("inf")
        return {
            **(row.payload or {"events": []} if event_id is None else row.payload or {}),
            "observed_on": _utc(row.observed_at).isoformat() if row.observed_at else None,
            "attempted_at": _utc(row.attempted_at).isoformat(),
            "stale": age >= TTL_SECONDS or bool(row.error),
            "error": row.error,
            "available": row.payload is not None,
            "refresh_interval_seconds": TTL_SECONDS,
        }
