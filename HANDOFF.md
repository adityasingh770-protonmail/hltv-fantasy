# HLTV Fantasy Lab — implementation handoff

Updated: September 11, 2026, Asia/Kolkata.
Workspace: `/Users/aditya-mac/Work/Personal/Projects/hltv-fantasy`.

## Resume condition and user direction

The user wants an app that builds the five best legal five-player fantasy teams
for a selected HLTV tournament. The current priority is completing automatic HLTV
ingestion.

**Pause full player-pool discovery until a new fantasy event is available before
its start.** The user explicitly clarified that in-progress events do not share
the player-pool data needed for this work. All four available games during this
session were already live. Do not keep probing those games for a complete pool
or treat their featured-player data as a complete roster.

When resuming, refresh the event index and inspect a new, not-yet-started game.
Capture its draft data before the deadline. No scheduled reminder or background
monitor was created. The optional ingestion worker described below was implemented
but was not left running in watch mode.

## Current implementation

The local MVP uses Next.js 16 / React 19 / TypeScript, FastAPI / Python 3.12,
SQLAlchemy / Alembic / PostgreSQL 17, and OR-Tools CP-SAT.

- Import immutable player-pool snapshots with prices, rules, projections, provenance,
  and optional deadline. Importer-supplied historical fantasy scores can produce
  a recency-weighted baseline; ratings are not automatically converted into points.
- Generate up to five optimal distinct rosters under budget, maximum-per-team,
  locks, and exclusions. With minimum changes = 1 these are the top five under
  the additive projection objective; greater diversity uses sequential constraints.
- Persist optimization requests/results, display lineups, and export JSON.
- Synthetic demo players and prices remain clearly separate from real observations.
- Automatically fetch enabled, unfinished events and selected event overviews.
- Show featured-player statistics and available explicit prices with clear
  incomplete-pool messaging. These observations cannot enter the optimizer.
- Cache observations in PostgreSQL with timestamps, content hashes, errors, and
  last-good-data retention. Refresh failures show stale data instead of replacing it
  with static or synthetic data.

Full automatic eligible-player pools, roster rules, and deadlines are **not complete**.
Neither are production-quality projections, role recommendations, or booster scheduling.

## Important files

| File | Purpose |
| --- | --- |
| `backend/ingestion.py` | Public HTTP adapter, event/overview parsers, cache and refresh coordination |
| `backend/main.py` | API routes, pool imports, optimization, persisted results |
| `backend/db.py` | Snapshot, Run, and IngestionResource models |
| `migrations/versions/0002_ingestion.py` | New persistent ingestion cache table |
| `backend/schemas.py` | Strict pool and request validation; projections required for optimizer pools |
| `backend/projections.py` | Recency-weighted imported historical-score baseline |
| `backend/optimizer.py` | Five-roster constrained optimization |
| `web/app/page.tsx` | UI, automatic refresh, observed-player panel, imported pool workflow |
| `scripts/ingest.py` | One-shot refresh of index and active overviews; optional `--watch` |
| `scripts/smoke.py` | Existing end-to-end demo optimizer test through Next.js proxy |
| `tests/test_ingestion.py` | Parser, caching, failure, HTTP, and API separation tests |
| `tests/fixtures/hltv-*.json` | Sanitized real source fixtures captured September 11 |
| `README.md` | Setup, ingestion contract, limitations, optimizer semantics |

`data/events.json` is a historical September 10 snapshot; the running API no longer
serves it. `data/sample-*.json` are fictional optimizer examples.

## Verified HLTV source contracts

Direct HTTP GET requests succeeded without login, cookies, or browser-session extraction:

- `https://www.hltv.org/fantasy/json`
- `https://www.hltv.org/fantasy/{fantasy_id}/overview/json`

The HTML hub is a JavaScript shell. Its hidden 404/500 templates do not establish
that the visible page failed. Public JSON routes were identified from the browser's
observed resource inventory. Some static JavaScript assets and the separate
`fantasy-secure.hltv.org` root returned Cloudflare challenges; these are not needed
for the working adapter.

Index fields used:

- `monthlyEvents[].events[]`: season games.
- `nonSeasonOpenMonthlyEvents[].events[]`: partner games, including historical ones.
- `fantasyId.id`, `name`, `enabled`, `state.type`.
- Observed state suffixes: `LiveEvent` and `FinishedEvent`.
- Filter disabled and finished games. Unknown future variants remain visible as
  `unknown`; do not assume their entry availability. **The upcoming state contract
  still needs to be captured from a real pre-start event.**

Last successful live run found:

| Fantasy ID | Name |
| --- | --- |
| 650 | FISSURE Playground 3 |
| 651 | PGL Masters Bucharest 2026 Europe Closed Qualifier |
| 652 | PGL Masters Bucharest 2026 South America Closed Qualifier |
| 653 | Thunderpick World Championship 2026 Closed Qualifier |

Overview fields used:

- `topMenuData.fantasyId.id`, `eventName`, `isGameStarted`, `gameFinished`.
- `bestValueForMoneyPlayers[].player` plus explicit `.price`.
- `mostPickedPlayers[].player` and `topRatedPlayers[]` have player identity and
  pre-event stats, but do not supply draft prices in the observed response.
- Player identity: `fantasyPlayerId.playerId`, `name`, `team.name`; statistics in `stats`.
- Numeric scoring fields: `roleFailPoints`, `roleSmallBonus`, `roleMaxBonus`,
  `failBoost`, `succeedBoost`, `teamWonPoints`, `teamLostPoints`.

The UI's price-per-point value is not a draft price. The JSON's explicit `price`
was verified separately (e.g. d1Ledez = 201000). Missing prices remain null.
Current-event actual points and popularity must not be used as pre-event predictions.
`timeToDraftEnd` was null in the live overview; no deadline interpretation is implemented.
Overview results always have `pool_complete: false`, `optimizer_ready: false`, and
`lock_at: null`.

## Refresh behavior

API routes:

```text
GET  /events
POST /events/refresh
GET  /events/{id}
POST /events/{id}/refresh
```

Responses include `available`, `stale`, `error`, `observed_on`, `attempted_at`, and
`refresh_interval_seconds`. Upstream failures remain HTTP 200 with explicit status
fields so cached data can still render. Invalid nonpositive IDs return 422.

- Successful data has a 15-minute TTL.
- Explicit refresh also respects a 60-second per-resource cooldown.
- The open UI requests updates every 15 minutes; selecting an event fetches details.
- Optional worker updates index plus all enabled unfinished event overviews.
- HTTP requests reject redirects and non-JSON pages, bound responses to 2 MB, use a
  10-second per-operation timeout, and retry transient failures at most once.
- 401/403/429 are surfaced without immediate retries or challenge bypasses.
- A process lock serializes refreshes; PostgreSQL transaction advisory locks also
  coordinate API/worker processes. SQLite is used for isolated tests.

## What to do when a new pre-start event appears

1. Run the ingestor and inspect the index for a new enabled game. Verify its actual
   entry status in HLTV's rendered UI; record the upcoming state fields in a fixture.
2. Open its public draft/player-selection view before the start. Read the applicable
   browser skill before controlling the browser; use observed links and resource
   inventory to find the actual full-pool endpoint. Do not invent an endpoint contract.
3. Capture sanitized fixtures with all eligible player IDs, canonical teams, draft
   prices, availability/replacement flags, roster size, budget, maximum per team,
   deadline with timezone, and any event-specific constraints. Preserve source URLs
   and observation times. Exclude account data, leaderboards, and advertising.
4. Implement a strict pre-start parser and explicit completeness checks. Verify the
   player count and prices against the draft UI. Treat missing or ambiguous values
   as unavailable, not zero or default rules. Handle transitions into live/finished
   states without deleting previously captured full draft snapshots.
5. Connect validated full pools to immutable snapshots. Keep observed data and
   projected scores separate: `PoolImport` currently requires projections/rationale
   or imported recent-form scores, so ingestion alone must not fabricate predictions.
   Decide whether to store a raw full pool pending a model or add an explicit
   projection stage before enabling optimization.
6. Add fixtures/tests for upcoming, live, finished, disabled, changed players/prices,
   malformed/partial data, unknown rules/deadline, stale refreshes, and repeated syncs.
   Test one real pre-start pool through the UI and optimizer once projections exist.
7. Finish the pending local preview/smoke verification described below. Update this
   handoff and README to reflect what is actually complete.

## Validation and exact stopping point

Completed in this session:

- 30 pytest tests passed after the final backend change (including advisory locking).
- Ruff lint and formatting checks passed for backend, tests, migrations, and scripts.
- Frontend TypeScript check and production webpack build passed. A subsequent tiny
  UI edit resets the details-loading flag on event changes; rerun frontend checks.
- `uv.lock` updated with httpx as a runtime dependency.
- Migration `0002` applied successfully to local PostgreSQL.
- Real `python -m scripts.ingest` succeeded for the index and all four overviews;
  each returned `available: true`, `error: null` and persisted data.

Pending verification:

- The old Next.js dev process hung. Browser navigation and the proxy smoke test
  timed out against it. It ignored SIGTERM and was force-stopped specifically.
- A new Next.js preview then started successfully on port 3000, reporting ready.
  The user interrupted before browser and smoke tests were rerun. **Do not claim
  end-to-end UI verification for ingestion has passed yet.**
- Latest known tool sessions: API `31504` (PID 67799 at launch), Next.js `74847`.
  These may no longer exist on resume; inspect ports/processes before restarting.
  The older smoke session `20070` exited with a timeout.
- There is no active watch worker. All project files were untracked at handoff;
  no implementation commit or PR was created. Preserve the existing work.

## Local commands

From the project root, using the default local database:

```sh
uv sync --locked --python 3.12
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Standalone `docker-compose` was used on this Mac because its Docker CLI did not
provide `docker compose`. PostgreSQL is on localhost:55432 with development
database/user/password `fantasy`; data is in the Docker volume.

In another terminal:

```sh
cd web
npm ci
npm run dev -- --port 3000
```

Ingestion and verification:

```sh
uv run python -m scripts.ingest
# Optional foreground service; not required to resume implementation:
uv run python -m scripts.ingest --watch

uv run pytest -q
uv run ruff check backend tests migrations scripts
uv run ruff format --check backend tests migrations scripts
uv run python scripts/smoke.py
cd web
npm run format:check
npm run typecheck
npm run build
```

Read `web/AGENTS.md` and the relevant installed Next.js documentation before UI
edits. Build uses `next build --webpack`; avoid running a production build against
an actively serving dev build directory if it disrupts the preview. `.env` is not
automatically loaded by Python commands; export settings or use `uv run --env-file`.
This remains a local single-user app, not a deployed production service.
