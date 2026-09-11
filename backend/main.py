import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy import select, text

from backend.db import Run, Session, Snapshot
from backend.ingestion import read_resource
from backend.optimizer import optimize
from backend.schemas import OptimizeRequest, PoolImport

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="HLTV Fantasy Lab", version="0.1.0")


@app.get("/health")
def health():
    with Session() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/events")
def events():
    return read_resource(Session)


@app.post("/events/refresh")
def refresh_events():
    return read_resource(Session, refresh=True)


@app.get("/events/{event_id}")
def event_details(event_id: int):
    if event_id <= 0:
        raise HTTPException(422, "Event ID must be positive")
    return read_resource(Session, event_id)


@app.post("/events/{event_id}/refresh")
def refresh_event(event_id: int):
    if event_id <= 0:
        raise HTTPException(422, "Event ID must be positive")
    return read_resource(Session, event_id, refresh=True)


@app.get("/sample")
def sample():
    return json.loads((ROOT / "data/sample-history-pool.json").read_text())


@app.post("/pools", status_code=201)
def import_pool(pool: PoolImport):
    if pool.observed_at > datetime.now(UTC):
        raise HTTPException(422, "Observation timestamp cannot be in the future")
    with Session() as session:
        snapshot = Snapshot(payload=pool.model_dump(mode="json"))
        session.add(snapshot)
        session.commit()
        return {"id": snapshot.id, "pool": snapshot.payload}


@app.get("/pools")
def pools():
    with Session() as session:
        rows = session.scalars(select(Snapshot).order_by(Snapshot.created_at.desc()).limit(50)).all()
        return [{"id": row.id, "pool": row.payload} for row in rows]


@app.post("/optimize")
def build_lineups(request: OptimizeRequest):
    with Session() as session:
        snapshot = session.get(Snapshot, request.pool_id)
        if snapshot is None:
            raise HTTPException(404, "Player pool not found")
        pool = PoolImport.model_validate(snapshot.payload)
        if not pool.is_demo and not pool.rules_verified:
            raise HTTPException(422, "Verify the event rules before generating lineups")
        try:
            result = optimize(pool, request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        warnings = [
            "Projections depend on imported estimates and scores; roles and boosters are not yet modeled."
        ]
        if pool.is_demo:
            warnings.append("Synthetic demonstration: these are fictional players, prices, and projections.")
        if pool.lock_at and pool.lock_at <= datetime.now(UTC):
            warnings.append(
                "The supplied lock time has passed. Treat this run as analysis, not an entry recommendation."
            )
        elif pool.lock_at is None:
            warnings.append("Entry deadline is unknown. Check HLTV before attempting to enter.")
        result.update(
            {"warnings": warnings, "request": request.model_dump(), "pool": pool.model_dump(mode="json")}
        )
        run = Run(pool_id=snapshot.id, payload=result)
        session.add(run)
        session.commit()
        return {"id": run.id, **result}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    with Session() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        return {"id": run.id, **run.payload}
