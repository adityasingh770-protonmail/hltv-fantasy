"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

type Player = {
  id: string;
  name: string;
  team: string;
  price: number;
  projected_points: number;
  rationale: string;
};
type Pool = {
  event_id: string;
  event_name: string;
  source_url: string;
  observed_at: string;
  lock_at: string | null;
  is_demo: boolean;
  rules_verified: boolean;
  projection_method: string;
  rules: { budget: number; roster_size: number; max_per_team: number };
  players: Player[];
};
type Snapshot = { id: string; pool: Pool };
type Event = {
  id: number;
  name: string;
  category: string;
  status: string;
  url: string;
};
type Feed = {
  events: Event[];
  observed_on: string | null;
  stale: boolean;
  error: string | null;
  available: boolean;
};
type EventDetails = {
  event_id?: number;
  event_name?: string;
  status?: string;
  observed_on: string | null;
  stale: boolean;
  error: string | null;
  available: boolean;
  players?: {
    id: string;
    name: string;
    team: string;
    price: number | null;
    stats: Record<string, string | null>;
  }[];
  limitations?: string[];
};
type Lineup = {
  rank: number;
  cost: number;
  remaining_budget: number;
  projected_points: number;
  players: Player[];
};
type Result = {
  id: string;
  lineups: Lineup[];
  warnings: string[];
  message: string;
  ranking_mode: string;
  termination: string;
  pool: Pool;
};
const money = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (d: { loc: string[]; msg: string }) =>
                  `${d.loc.join(".")}: ${d.msg}`,
              )
              .join("; ")
          : "Could not reach the API. Check that the backend and database are running.",
    );
  }
  return response.json();
}

export default function Home() {
  const [events, setEvents] = useState<Event[]>([]);
  const [observed, setObserved] = useState("");
  const [feedWarning, setFeedWarning] = useState("");
  const [details, setDetails] = useState<EventDetails | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [active, setActive] = useState<Snapshot | null>(null);
  const [selectedEvent, setSelectedEvent] = useState("demo");
  const [locked, setLocked] = useState<string[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [diversity, setDiversity] = useState(1);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generateAction = useRef<() => Promise<Result | null>>(async () => null);

  useEffect(() => {
    const context = (
      document as Document & {
        modelContext?: {
          registerTool: (
            tool: object,
            options: { signal: AbortSignal },
          ) => unknown;
        };
      }
    ).modelContext;
    if (!context) return;
    const lifecycle = new AbortController();
    try {
      Promise.resolve(
        context.registerTool(
          {
            name: "generate_fantasy_lineups",
            description:
              "Generate and save up to five optimal lineups for the currently selected pool and visible constraints, then display the results. Does not enter an HLTV contest.",
            inputSchema: {
              type: "object",
              properties: {},
              additionalProperties: false,
            },
            annotations: { readOnlyHint: false, untrustedContentHint: true },
            async execute(input: unknown) {
              if (
                !input ||
                typeof input !== "object" ||
                Array.isArray(input) ||
                Object.keys(input).length
              )
                throw new Error("Expected an empty object");
              const value = await generateAction.current();
              if (!value)
                throw new Error(
                  "Could not generate lineups. Check the pool, rules, and visible error message.",
                );
              return {
                id: value.id,
                count: value.lineups.length,
                termination: value.termination,
                message: value.message,
              };
            },
          },
          { signal: lifecycle.signal },
        ),
      ).catch(() => {
        /* Optional browser capability; UI remains available. */
      });
    } catch {
      /* Unsupported browser implementation; UI remains available. */
    }
    return () => lifecycle.abort();
  }, []);

  useEffect(() => {
    let live = true;
    Promise.all([api<Feed>("/events"), api<Snapshot[]>("/pools")])
      .then(([data, saved]) => {
        if (live) {
          setEvents(data.events);
          setObserved(data.observed_on || "");
          setFeedWarning(
            data.error || (data.stale ? "Event data is stale." : ""),
          );
          setSnapshots(saved);
          setActive(saved.find((s) => s.pool.is_demo) || null);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    setDetails(null);
    setDetailsLoading(false);
    if (!/^\d+$/.test(selectedEvent)) return;
    async function loadDetails() {
      setDetailsLoading(true);
      try {
        const data = await api<EventDetails>(`/events/${selectedEvent}`);
        if (live) setDetails(data);
      } catch (e) {
        if (live)
          setDetails({
            observed_on: null,
            stale: true,
            available: false,
            error: (e as Error).message,
          });
      } finally {
        if (live) setDetailsLoading(false);
      }
    }
    void loadDetails();
    const timer = setInterval(loadDetails, 900_000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [selectedEvent]);

  useEffect(() => {
    const timer = setInterval(() => {
      api<Feed>("/events")
        .then((data) => {
          setEvents(data.events);
          setObserved(data.observed_on || "");
          setFeedWarning(
            data.error || (data.stale ? "Event data is stale." : ""),
          );
        })
        .catch((e) => setFeedWarning(e.message));
    }, 900_000);
    return () => clearInterval(timer);
  }, []);

  async function refreshHltv() {
    setSyncing(true);
    try {
      const data = await api<Feed>("/events/refresh", {});
      setEvents(data.events);
      setObserved(data.observed_on || "");
      setFeedWarning(data.error || (data.stale ? "Event data is stale." : ""));
      if (/^\d+$/.test(selectedEvent)) {
        setDetails(
          await api<EventDetails>(`/events/${selectedEvent}/refresh`, {}),
        );
      }
    } catch (e) {
      setFeedWarning((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  function choose(snapshot: Snapshot | null, eventId?: string) {
    setActive(snapshot);
    setSelectedEvent(eventId || (snapshot?.pool.event_id ?? "demo"));
    setLocked([]);
    setExcluded([]);
    setResult(null);
    setError("");
    setQuery("");
  }
  async function importData(data: unknown) {
    const snapshot = await api<Snapshot>("/pools", data);
    setSnapshots((previous) => [snapshot, ...previous]);
    choose(snapshot);
  }
  async function loadDemo() {
    setBusy(true);
    setError("");
    try {
      await importData(await api<Pool>("/sample"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      if (file.size > 1_000_000)
        throw new Error("Choose a player-pool JSON file smaller than 1 MB.");
      await importData(JSON.parse(await file.text()));
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? "This file is not valid JSON. Download the example to see the expected format."
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  function toggle(id: string, kind: "lock" | "exclude") {
    setResult(null);
    if (kind === "lock") {
      setLocked((previous) =>
        previous.includes(id)
          ? previous.filter((x) => x !== id)
          : [...previous, id],
      );
      setExcluded((previous) => previous.filter((x) => x !== id));
    } else {
      setExcluded((previous) =>
        previous.includes(id)
          ? previous.filter((x) => x !== id)
          : [...previous, id],
      );
      setLocked((previous) => previous.filter((x) => x !== id));
    }
  }
  async function generate(): Promise<Result | null> {
    if (!active || busy) return null;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const value = await api<Result>("/optimize", {
        pool_id: active.id,
        locked,
        excluded,
        min_unique: diversity,
      });
      flushSync(() => setResult(value));
      return value;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    generateAction.current = generate;
  });
  function exportResult() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `fantasy-run-${result?.id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  const pool = active?.pool;
  const players =
    pool?.players.filter((p) =>
      `${p.name} ${p.team}`.toLowerCase().includes(query.toLowerCase()),
    ) ?? [];
  const selectedCost =
    pool?.players
      .filter((p) => locked.includes(p.id))
      .reduce((sum, p) => sum + p.price, 0) ?? 0;
  const eventOptions = [
    ...events.map((e) => ({ id: String(e.id), name: e.name })),
    ...snapshots
      .filter(
        (s) =>
          !s.pool.is_demo &&
          !events.some((e) => String(e.id) === s.pool.event_id),
      )
      .map((s) => ({ id: s.pool.event_id, name: s.pool.event_name })),
  ].filter((e, i, all) => all.findIndex((x) => x.id === e.id) === i);

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="/" aria-label="Fantasy Lab home">
          <span className="brandmark">F/</span> FANTASY
          <span className="muted">LAB</span>
        </a>
        <span className="topnote">COUNTER-STRIKE · LINEUP WORKSPACE</span>
        <a
          className="external"
          href="https://www.hltv.org/fantasy"
          target="_blank"
          rel="noreferrer"
        >
          Open HLTV ↗
        </a>
      </header>
      <div className="pageheading">
        <div>
          <p className="eyebrow">MAKE EVERY PICK COUNT</p>
          <h1>Build your advantage.</h1>
          <p className="intro">Five lineups. One budget. Your projections.</p>
        </div>
        <span className="version">WORKSPACE / 01</span>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="eventbar" aria-label="Event selection">
        <div className="eventselect">
          <label htmlFor="event">TOURNAMENT</label>
          <select
            id="event"
            value={selectedEvent}
            disabled={busy || loading || syncing}
            onChange={(e) => {
              const id = e.target.value;
              choose(snapshots.find((s) => s.pool.event_id === id) ?? null, id);
            }}
          >
            <option value="demo">Practice arena · synthetic demo</option>
            {eventOptions.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </select>
        </div>
        <div className="eventmeta">
          <span className="tag">
            {pool?.is_demo || selectedEvent === "demo"
              ? "DEMO"
              : pool
                ? "IMPORTED POOL"
                : "POOL NEEDED"}
          </span>
          <span>
            Event list checked{" "}
            {observed ? new Date(observed).toLocaleString() : "—"}
            <br />
            Automatic refresh every 15 minutes
          </span>
        </div>
        <label className={`button secondary ${busy ? "disabled" : ""}`}>
          Import player pool
          <input
            type="file"
            accept=".json,application/json"
            onChange={upload}
            disabled={busy}
            className="sr-only"
          />
        </label>
      </section>
      {feedWarning && (
        <div className="notice" role="status">
          {feedWarning}
        </div>
      )}
      <section className="notice" aria-label="HLTV ingestion">
        <button
          className="button secondary"
          disabled={syncing || loading}
          onClick={refreshHltv}
        >
          {syncing ? "Refreshing HLTV…" : "Refresh HLTV"}
        </button>
        {detailsLoading && <p role="status">Fetching HLTV event statistics…</p>}
        {details && (
          <>
            {details.error && <p role="status">{details.error}</p>}
            {details.available && (
              <>
                <p>
                  <strong>{details.event_name}</strong> · {details.status} ·{" "}
                  {details.stale ? "Stale data" : "Fetched"}{" "}
                  {details.observed_on
                    ? new Date(details.observed_on).toLocaleString()
                    : "—"}
                </p>
                <p>
                  Featured players from HLTV. This is an incomplete player list
                  and cannot be used to generate lineups. Draft deadline and
                  roster rules remain unverified.
                </p>
                <details>
                  <summary>
                    View {details.players?.length || 0} observed players and
                    statistics
                  </summary>
                  <div style={{ overflowX: "auto" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Player</th>
                          <th>Team</th>
                          <th>Observed draft price</th>
                          <th>Pre-event rating</th>
                        </tr>
                      </thead>
                      <tbody>
                        {details.players?.map((player) => (
                          <tr key={player.id}>
                            <td>{player.name}</td>
                            <td>{player.team}</td>
                            <td>
                              {player.price === null
                                ? "Unknown"
                                : money(player.price)}
                            </td>
                            <td>{player.stats.rating || "Unknown"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </>
            )}
          </>
        )}
      </section>
      <div className="workspace">
        <section className="poolpanel" aria-labelledby="pool-title">
          <div className="sectionheading">
            <div>
              <p className="eyebrow">01 / PLAYER POOL</p>
              <h2 id="pool-title">Choose your core</h2>
            </div>
            <span className="count">{pool?.players.length ?? 0} players</span>
          </div>
          {loading ? (
            <p className="empty">Loading saved pools…</p>
          ) : !pool ? (
            <div className="empty">
              <span className="emptyicon">＋</span>
              <h3>
                {selectedEvent === "demo"
                  ? "Start with a practice pool"
                  : "Player data needed"}
              </h3>
              <p>
                {selectedEvent === "demo"
                  ? "Try the optimizer with fictional players and prices, or import your own verified pool."
                  : "HLTV event statistics refresh automatically above. To generate lineups, import a complete player pool with verified prices, roster rules, and projections."}
              </p>
              <button
                className="button primary"
                disabled={busy}
                onClick={loadDemo}
              >
                Load synthetic demo
              </button>
              <a
                className="textlink"
                href="/api/sample"
                download="sample-pool.json"
              >
                Download JSON example ↓
              </a>
            </div>
          ) : (
            <>
              <div className={`notice ${pool.is_demo ? "demo" : ""}`}>
                {pool.is_demo
                  ? "SYNTHETIC DEMO — fictional players, prices, and projections."
                  : `Imported ${new Date(pool.observed_at).toLocaleString()}. ${pool.rules_verified ? "Rules marked verified by importer." : "Rules need verification before optimization."}`}
              </div>
              <div className="pooltools">
                <input
                  aria-label="Search players or teams"
                  placeholder="Search player or team…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <select
                  aria-label="Saved player pool"
                  disabled={busy}
                  value={active?.id || ""}
                  onChange={(e) =>
                    choose(
                      snapshots.find((s) => s.id === e.target.value) ?? null,
                    )
                  }
                >
                  {snapshots.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.pool.event_name} ·{" "}
                      {new Date(s.pool.observed_at).toLocaleDateString()}
                    </option>
                  ))}
                </select>
              </div>
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th>PLAYER / TEAM</th>
                      <th>PRICE</th>
                      <th>
                        <abbr title="Supplied projected fantasy points">
                          PROJ.
                        </abbr>
                      </th>
                      <th>SELECTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {players.map((p) => (
                      <tr
                        key={p.id}
                        className={
                          excluded.includes(p.id)
                            ? "excluded"
                            : locked.includes(p.id)
                              ? "locked"
                              : ""
                        }
                      >
                        <td>
                          <span
                            className={`avatar team${pool.players.findIndex((x) => x.team === p.team) % 4}`}
                          >
                            {p.team.slice(0, 1)}
                          </span>
                          <span className="playername">
                            {p.name}
                            <small>{p.team}</small>
                          </span>
                        </td>
                        <td>{money(p.price)}</td>
                        <td className="points" title={p.rationale}>
                          {p.projected_points.toFixed(1)}
                        </td>
                        <td>
                          <div className="pickactions">
                            <button
                              disabled={
                                busy ||
                                (!locked.includes(p.id) && locked.length >= 5)
                              }
                              className={locked.includes(p.id) ? "active" : ""}
                              aria-label={`Lock ${p.name}`}
                              aria-pressed={locked.includes(p.id)}
                              onClick={() => toggle(p.id, "lock")}
                            >
                              Lock
                            </button>
                            <button
                              disabled={busy}
                              className={
                                excluded.includes(p.id) ? "active exclude" : ""
                              }
                              aria-label={`Exclude ${p.name}`}
                              aria-pressed={excluded.includes(p.id)}
                              onClick={() => toggle(p.id, "exclude")}
                            >
                              ×
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {players.length === 0 && (
                  <p className="empty">No matching players.</p>
                )}
              </div>
              <div className="poolfooter">
                <span>
                  {locked.length} locked · {excluded.length} excluded
                </span>
                <button
                  className="textlink"
                  disabled={busy}
                  onClick={() => {
                    setLocked([]);
                    setExcluded([]);
                    setResult(null);
                  }}
                >
                  Reset picks
                </button>
              </div>
            </>
          )}
        </section>
        <aside className="buildpanel">
          <p className="eyebrow">02 / BUILD SETTINGS</p>
          <h2>The game plan</h2>
          <div className="budget">
            <span>Team budget</span>
            <strong>{pool ? money(pool.rules.budget) : "—"}</strong>
            <div className="budgettrack">
              <div
                style={{
                  width: `${pool ? Math.min(100, (selectedCost / pool.rules.budget) * 100) : 0}%`,
                }}
              />
            </div>
            <small>{money(selectedCost)} committed to locked picks</small>
          </div>
          <div className="rules">
            <div>
              <span>Players per lineup</span>
              <strong>5</strong>
            </div>
            <div>
              <span>Maximum from one team</span>
              <strong>{pool?.rules.max_per_team ?? "—"}</strong>
            </div>
            <div>
              <span>Lineups to generate</span>
              <strong>5</strong>
            </div>
          </div>
          <label className="fieldlabel" htmlFor="diversity">
            Minimum player changes
          </label>
          <select
            id="diversity"
            value={diversity}
            disabled={busy}
            onChange={(e) => {
              setDiversity(Number(e.target.value));
              setResult(null);
            }}
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n === 1 ? "1 · Exact top five" : `${n} · More variety`}
              </option>
            ))}
          </select>
          <p className="help">
            {diversity === 1
              ? "Rank the five highest-scoring distinct rosters. They may share four players."
              : `Each new lineup must change at least ${diversity} players from every earlier lineup. These are sequential picks, not a globally optimal portfolio.`}
          </p>
          <button
            className="button primary generate"
            disabled={busy || !pool || (!pool.is_demo && !pool.rules_verified)}
            onClick={generate}
          >
            {busy ? "Working…" : "Generate five lineups →"}
          </button>
          <p className="help">
            Ranked by projected points. Roles and boosters are not included yet.
          </p>
          {pool && (
            <details>
              <summary>Projection method & source</summary>
              <p>{pool.projection_method}</p>
              <a href={pool.source_url} target="_blank" rel="noreferrer">
                Source ↗
              </a>
            </details>
          )}
        </aside>
      </div>
      <section className="results" aria-live="polite">
        <div className="sectionheading">
          <div>
            <p className="eyebrow">03 / YOUR SHORTLIST</p>
            <h2>
              {result
                ? `${result.lineups.length} lineups, ready to compare`
                : "Your next five start here"}
            </h2>
          </div>
          {result && (
            <button className="button secondary" onClick={exportResult}>
              Export results ↓
            </button>
          )}
        </div>
        {!result ? (
          <div className="resultempty">
            <span>01 — 05</span>
            <p>
              Load a player pool, set your picks, and generate your shortlist.
            </p>
          </div>
        ) : (
          <>
            <p className="resultmessage">{result.message}</p>
            {result.warnings.map((w) => (
              <p className="warning" key={w}>
                {w}
              </p>
            ))}
            <div className="lineups">
              {result.lineups.map((lineup) => (
                <article className="lineup" key={lineup.rank}>
                  <div className="lineuptop">
                    <span>BUILD {String(lineup.rank).padStart(2, "0")}</span>
                    {lineup.rank === 1 && (
                      <span className="best">TOP PROJECTION</span>
                    )}
                  </div>
                  <div className="lineupscore">
                    {lineup.projected_points.toFixed(1)}
                    <small>projected pts</small>
                  </div>
                  <ul>
                    {lineup.players.map((p) => (
                      <li key={p.id}>
                        <span>
                          {p.name}
                          <small>{p.team}</small>
                        </span>
                        <span>{money(p.price)}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="lineupcost">
                    <span>{money(lineup.cost)}</span>
                    <small>{money(lineup.remaining_budget)} left</small>
                  </div>
                </article>
              ))}
            </div>
            {result.lineups.length === 0 && (
              <div className="empty">
                No legal lineup fits these selections. Try unlocking players,
                restoring excluded players, or reducing the diversity setting.
              </div>
            )}
          </>
        )}
      </section>
      <footer>
        <span>
          FANTASY LAB{" "}
          <span className="muted">
            / Independent project. Not affiliated with HLTV.
          </span>
        </span>
        <span>Estimates, never guarantees.</span>
      </footer>
    </main>
  );
}
