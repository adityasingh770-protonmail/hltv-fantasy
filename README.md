# HLTV Fantasy team builder

Build the five highest-ranked distinct five-player fantasy lineups for a selected HLTV fantasy tournament.

## Intended workflow

1. Discover events from https://www.hltv.org/fantasy and distinguish open entries, ongoing games, and completed games. A tournament appearing in news does not establish that entries remain open.
2. Capture the selected game's eligible players, prices, roster restrictions, budget, lock time, scoring rules, roles, and boosters. Store source URLs and collection timestamps.
3. Estimate player fantasy points using recent performance and the event's format, opponents, expected matches, and any stage-skipping adjustments. Keep projections separate from observed statistics.
4. Rank legal five-player combinations and return the top five distinct rosters under the chosen projection model, including cost, remaining budget, projected points, and rationale. Report when fewer than five legal rosters exist.
5. Recommend roles and boosters only once their rules and supporting player statistics have been verified.

“Best” means highest projected fantasy score under a documented model, not a guaranteed outcome. Historical evaluations must use information available before the game's lock time.

## Initial discovery — September 10, 2026 (historical snapshot)

The workspace was empty at the start of discovery. A first working implementation now includes a Next.js interface, FastAPI API, OR-Tools optimizer, and PostgreSQL persistence.

HLTV's [FISSURE Playground 3 announcement](https://www.hltv.org/news/45462/fissure-playground-3-teams-format-schedule-prizes-fantasy) confirms a single fantasy game for the entire tournament, scheduled September 8–13. It links to [fantasy game 650](https://www.hltv.org/fantasy/650/overview). Entry availability and player prices have not been verified.

Verified directly in Chrome using Computer Use: the September fantasy hub lists four live games and four finished games. Expanding coming months shows October, November, and December headings without games. No upcoming game open for drafting was displayed. Live status is recorded separately from entry availability; individual entry controls have not been checked.

| Live game | Game ID | Category |
| --- | --- | --- |
| [FISSURE Playground 3](https://www.hltv.org/fantasy/650/gameredirect) | 650 | Fall season |
| [PGL Masters Bucharest 2026 Europe Closed Qualifier](https://www.hltv.org/fantasy/651/gameredirect) | 651 | Partner |
| [PGL Masters Bucharest 2026 South America Closed Qualifier](https://www.hltv.org/fantasy/652/gameredirect) | 652 | Partner |
| [Thunderpick World Championship 2026 Closed Qualifier](https://www.hltv.org/fantasy/653/gameredirect) | 653 | Partner |

Finished September games: Playoffs - BLAST Open Porto 2026 (648), IEM Beijing 2026 Asia Closed Qualifier (646), IEM Beijing 2026 Closed Qualifier (647), and Stake Ranked Episode 4 Closed Qualifier (649).

Partner games have their own prizes but do not contribute to the season leaderboard. The web reader returned error-page content for the hub; the browser UI was successfully inspected and is the source for this snapshot.

## Automatic ingestion — September 11, 2026

The live adapter uses public `GET https://www.hltv.org/fantasy/json` and
`GET https://www.hltv.org/fantasy/{id}/overview/json` responses. These are observed
website endpoints, not a documented stable API. No account, cookies, browser
session, or competition entry is required. The app no longer serves `data/events.json`.

Event discovery and overview ingestion work automatically. **Full eligible draft-pool
ingestion is still incomplete**: the verified overview endpoint contains only featured
players and supplies draft prices for only some of them. No verified full-pool route
was available during this implementation. This data cannot produce valid top-five
lineups without a complete imported pool and projections.

- Disabled and finished games are filtered out. Live games are marked as started;
  unfamiliar state variants stay visible as `unknown`, with entry availability unknown.
- Selecting a numeric HLTV event automatically fetches its overview, featured player
  statistics, available explicit prices, and scoring constants. No missing prices,
  draft deadlines, roster constraints, or fantasy projections are invented.
- The UI refreshes every 15 minutes while open. GET requests use a 15-minute database
  cache; **Refresh HLTV** requests an earlier update, subject to a 60-second cooldown.
- PostgreSQL stores normalized source data, a content hash, successful observation time,
  latest attempt time, and a readable failure. Failed refreshes preserve the last good
  data and mark it stale. No static or synthetic fallback is presented as current data.
- Requests have a 10-second per-operation timeout, at most two attempts for transient
  failures, a 2 MB response limit, and no redirects. Blocked/rate-limited responses are
  not retried immediately. PostgreSQL advisory locks coordinate workers and cooldowns.
- Ingestion data stays separate from immutable optimizer snapshots. Featured subsets
  always report `pool_complete: false` and `optimizer_ready: false`.

After applying the migration, refresh all enabled event overviews once:

```sh
uv run python -m scripts.ingest
```

For updates while the UI is closed, run this optional foreground worker alongside
the API (stop with Ctrl+C; keep it supervised for continuous service):

```sh
uv run python -m scripts.ingest --watch
```

Endpoints: `GET /events`, `POST /events/refresh`, `GET /events/{id}`, and
`POST /events/{id}/refresh`. Responses include `available`, `stale`, `error`,
`observed_on`, and `attempted_at`. An unavailable upstream is represented in these
fields so the UI can still render; the one-shot ingestion command exits nonzero
if any requested refresh fails. Run `alembic upgrade head` before using them.

## Run locally

Requirements: Python 3.12, uv, Node.js 20.9+ (22 LTS recommended), npm, and Docker with Compose. Dependencies are pinned in `uv.lock` and `web/package-lock.json`.

From the repository root:

```sh
uv sync --locked --python 3.12
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

If your installation provides standalone Compose, use `docker-compose up -d db` instead. The database is bound to localhost:55432 and stored in the `fantasy_pg` Docker volume. Wait for its health check before applying migrations. The default local database credentials are for development only.

In a second terminal:

```sh
cd web
npm ci
npm run dev -- --port 3000
```

Open http://127.0.0.1:3000. Use **Load synthetic demo**, then **Generate five lineups**. The API docs are at http://127.0.0.1:8000/docs.

For a custom database, export `DATABASE_URL` before running migrations and the API. For a different backend address, export `API_URL` before running Next.js. `.env.example` documents defaults; `.env` files are not loaded automatically by the Python commands above. Alternatively use `uv run --env-file .env ...`.

## What works

- Automatically refresh enabled, unfinished HLTV fantasy events and selected event statistics from public JSON. Show freshness, failures, and last successful data.
- Import a JSON pool with eligible players, prices, projections, source URL, observation time, optional lock time, and event rules.
- Search players, lock or exclude picks, and choose a minimum number of player changes between rosters.
- Generate up to five legal, distinct rosters with costs and projected scores.
- Save immutable pool snapshots and optimization results in PostgreSQL, and export full results as JSON.
- Reload saved pools; retrieve a saved run with `GET /runs/{id}`.

Use `data/sample-pool.json` as the import template. Its names, prices, projections, and rules are entirely synthetic. Real pools must set `is_demo: false`; `rules_verified: true` is an importer assertion, not independent verification by the application. Each real pool needs its own verified budget and team limit. Player `team` values must use one consistent canonical spelling per team.

The optimizer accepts **supplied projected fantasy points** or calculates a transparent recent-form baseline from imported historical fantasy scores. It does not yet fetch or convert HLTV ratings into fantasy points. Every normalized player includes a rationale and every pool identifies its projection method. Current outputs do not include roles or boosters. Those require verified scoring rules and a historical performance pipeline before recommendations can be trusted for live entry.

### Recent-form projection

The on-screen demo and `data/sample-history-pool.json` demonstrate this mode with fictional scores. For each player, supply `recent_form` instead of `projected_points` and `rationale`:

```json
{
  "recent_form": {
    "matches": [
      {"played_at": "2026-08-11T00:00:00Z", "fantasy_points": 10},
      {"played_at": "2026-09-10T00:00:00Z", "fantasy_points": 40}
    ],
    "expected_matches": 4,
    "half_life_days": 30,
    "padding_points": 6
  }
}
```

This is a fragment to add to each player, not a complete pool. At an observation time of September 10, the weighted mean is `(10 × 0.5 + 40) / 1.5 = 30` points per series, giving `30 × 4 + 6 = 126` projected points. `recent_form` takes precedence if both forms are provided. Historical scores must be comparable per-series fantasy scores excluding roles and boosters; expected series and padding are explicit user estimates. The baseline does not infer bracket advancement, opponent strength, or uncertainty. Future historical observations and timezone-free dates are rejected.

## Optimization contract

Exactly five distinct players, within the imported budget and maximum-per-team rule. Locked players are included and excluded players cannot appear. The objective maximizes the sum of player projections, rounded per player to 0.001 points using decimal half-up rounding.

With minimum changes = 1, repeated optimal solves exclude each prior roster to produce the exact top five under that additive objective. Equal-scoring rosters have no secondary preference. With minimum changes > 1, each subsequent roster must differ by at least that many players from **every** earlier roster; this is greedy sequential diversity, not joint portfolio optimization.

The entire request has a 15-second solver budget. Only solutions proven optimal are returned. The response explicitly distinguishes five results, exhaustion of feasible rosters, and solver timeout. An infeasible pool or restrictive locks may produce fewer than five results. Passed or unknown entry deadlines are flagged; the app never submits a lineup to HLTV.

## Validation

```sh
uv run pytest -q
uv run ruff check backend tests migrations scripts
cd web
npm run typecheck
npm run build
```

Optimizer tests compare results against exhaustive enumeration, including locks, exclusions, and sequential diversity. API tests use temporary SQLite databases to isolate fixtures. With the real local services running, `uv run python scripts/smoke.py` additionally verifies the Next.js proxy, FastAPI, PostgreSQL, and persisted results together. It creates a demo snapshot and run.

## Architecture and next work

- `backend/schemas.py`: strict imports and request validation.
- `backend/optimizer.py`: independent constrained optimization engine.
- `backend/projections.py`: recency-weighted baseline and readable player explanations.
- `backend/main.py`: API endpoints and immutable run recording.
- `backend/ingestion.py`, `scripts/ingest.py`: public HLTV adapters, persistent cache, and optional refresh worker.
- `backend/db.py`, `migrations/`: SQLAlchemy persistence and Alembic schema history.
- `web/app/`: responsive lineup workspace.
- `data/`: observed event snapshot and fictional practice pool.

Next: verify and ingest the complete HLTV eligible player pool, prices, roster limits, and draft deadline; transparent, backtested player projections with tournament advancement assumptions; role assignment and booster scheduling. Observed statistics must remain separate from estimates, and backtests must use only information available before the relevant deadline.

The production script uses Next.js's webpack path because Turbopack's CSS worker failed to start in this development environment. Development preview uses the default Next.js bundler.

The first version is a local single-user application without authentication. Both app servers and PostgreSQL bind to localhost. Production hosting requires a Node runtime, Python runtime, PostgreSQL, and authentication/access controls; the selected Python/OR-Tools backend is not packaged for the Sites Cloudflare Worker runtime.

An optional `generate_fantasy_lineups` WebMCP tool is feature-detected in compatible browsers and uses the same visible selections and generation action. This browser integration has not been runtime-verified; unsupported browsers use the normal interface.
