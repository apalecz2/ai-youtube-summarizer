import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { AppEvent, Diagnostics, JobRow } from "../types";
import EventList from "../components/EventList";
import { fmtBytes, fmtDate, fmtRel, fmtSpan } from "../util";

const LEVEL_ORDER = { bad: 0, warn: 1, ok: 2 } as const;
const JOB_STATUSES = ["pending", "running", "done", "failed", "cancelled"];

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <div className={`stat-n ${tone ?? ""}`}>{value}</div>
      <div className="muted">{label}</div>
    </div>
  );
}

export default function SystemPage() {
  const [d, setD] = useState<Diagnostics | null>(null);
  const [err, setErr] = useState("");
  const [auto, setAuto] = useState(true);
  const [msg, setMsg] = useState("");

  // events
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [level, setLevel] = useState("");
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(200);

  // jobs
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobStatus, setJobStatus] = useState("");

  const load = useCallback(async () => {
    try {
      const [diag, ev, jb] = await Promise.all([
        api.diagnostics(),
        api.events({ limit, level, source, q }),
        api.jobs(jobStatus || undefined),
      ]);
      setD(diag); setEvents(ev.events); setJobs(jb.jobs); setErr("");
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [limit, level, source, q, jobStatus]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [auto, load]);

  async function act(fn: () => Promise<unknown>, done: string) {
    try { await fn(); setMsg(done); } catch (e) { setMsg(`Error: ${(e as Error).message}`); }
    load();
  }

  if (err && !d) return <div className="empty">Error: {err}</div>;
  if (!d) return <p className="muted">Loading…</p>;

  const health = [...d.health].sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]);
  const bad = health.filter((h) => h.level === "bad").length;
  const warn = health.filter((h) => h.level === "warn").length;
  const a = d.worker.activity;
  const sched = d.scheduler;
  const problemCount = Object.values(d.problems).reduce((n, rows) => n + rows.length, 0);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>System</h2>
        <div className="row">
          <span className="muted">{auto ? "Auto-refreshing every 5s" : "Paused"}</span>
          <button onClick={() => setAuto((v) => !v)}>{auto ? "Pause" : "Resume"}</button>
          <button onClick={load}>Refresh</button>
        </div>
      </div>
      {msg && <p className="muted">{msg}</p>}

      {/* ── Health ── */}
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>
            Health{" "}
            <span className={`pill ${bad ? "bad" : warn ? "warn" : "good"}`}>
              {bad ? `${bad} problem${bad > 1 ? "s" : ""}` : warn ? `${warn} warning${warn > 1 ? "s" : ""}` : "all good"}
            </span>
          </h3>
          <div className="row">
            <button disabled={problemCount === 0} onClick={() => act(api.fixStuck, "Requeued stuck jobs.")}
              title="Reset jobs stuck in 'running' (not the one the worker is actively on) back to pending">
              Fix stuck jobs
            </button>
          </div>
        </div>
        <ul className="health">
          {health.map((h) => (
            <li key={h.id}>
              <span className={`dot ${h.level}`} />
              <div>
                <div>{h.title}</div>
                {h.detail && <div className="muted">{h.detail}</div>}
              </div>
            </li>
          ))}
        </ul>
        {problemCount > 0 && (
          <details>
            <summary className="muted">Show the affected rows</summary>
            {Object.entries(d.problems).filter(([, rows]) => rows.length).map(([k, rows]) => (
              <div key={k}>
                <strong>{k}</strong>
                <pre className="error-detail">{JSON.stringify(rows, null, 1)}</pre>
              </div>
            ))}
          </details>
        )}
      </div>

      {/* ── Right now ── */}
      <div className="card">
        <h3>Right now</h3>
        <div className="grid">
          <div>
            <div className="muted">Worker</div>
            {a ? (
              <div>
                Processing <Link to={`/videos/${a.video_id}`}>{a.video_id}</Link> (job #{a.job_id}, attempt {a.attempt})
                <div className="muted">
                  Stage: <strong>{a.stage}</strong> for {a.stage_seconds}s · job running {a.running_seconds}s
                </div>
              </div>
            ) : d.backoff.manual ? (
              <div>Paused — manual cooldown, resumes {fmtRel(d.backoff.blocked_until, d.now)}</div>
            ) : (
              <div>Idle (waiting for due jobs)</div>
            )}
            <div className="muted">
              Heartbeat {d.worker.seconds_since_heartbeat != null ? `${Math.round(d.worker.seconds_since_heartbeat)}s ago` : "never"}
            </div>
          </div>
          <div>
            <div className="muted">Rate limit</div>
            <div>
              {d.backoff.mode === "manual" ? "Manual cooldown (set by you)"
                : d.backoff.mode === "fallback" ? `Suspended (level ${d.backoff.backoff_level}) — using direct Gemini, YouTube retry ${fmtRel(d.backoff.blocked_until, d.now)}`
                : d.backoff.mode === "suspect" ? `Checking: ${d.backoff.suspect_video_id} failed, waiting for a second video`
                : `OK (level ${d.backoff.backoff_level})`}
            </div>
            <div className="muted">
              Last block: {d.backoff.last_block_at ? fmtRel(d.backoff.last_block_at, d.now) : "never"} · last success:{" "}
              {d.backoff.last_success_at ? fmtRel(d.backoff.last_success_at, d.now) : "never"}
            </div>
          </div>
          <div>
            <div className="muted">Discovery</div>
            <div>Next scan {sched.next_poll_in_seconds != null ? fmtRel(d.now + sched.next_poll_in_seconds, d.now) : "— (not scheduled)"}</div>
            <div className="muted">
              {sched.last_discovery
                ? `Last: ${fmtRel(sched.last_discovery.at, d.now)} — ${sched.last_discovery.new} new, ${sched.last_discovery.filtered} filtered, ${sched.last_discovery.pre_existing} pre-existing (${sched.last_discovery.channels} channels)`
                : "No scan since this app started"}
            </div>
          </div>
        </div>
      </div>

      {/* ── Database ── */}
      <div className="card">
        <h3>Database</h3>
        <div className="stats">
          {Object.entries(d.videos).sort((x, y) => y[1] - x[1]).map(([s, n]) => (
            <Stat key={s} label={`videos: ${s}`} value={n}
              tone={s === "failed" && n ? "bad" : s === "fetching" && n ? "warn" : ""} />
          ))}
        </div>
        <div className="muted" style={{ margin: "10px 0 4px" }}>Queue (jobs by status)</div>
        <div className="stats">
          {Object.keys(d.queue).length === 0 && <span className="muted">no jobs</span>}
          {Object.entries(d.queue).map(([s, n]) => (
            <Stat key={s} label={`jobs: ${s}`} value={n} tone={s === "running" ? "warn" : s === "failed" && n ? "bad" : ""} />
          ))}
        </div>
        <div className="muted" style={{ margin: "10px 0 4px" }}>Changed in the last 24h</div>
        <div className="stats">
          {Object.keys(d.videos_last_24h).length === 0 && <span className="muted">nothing</span>}
          {Object.entries(d.videos_last_24h).map(([s, n]) => <Stat key={s} label={s} value={n} />)}
        </div>
        <div className="muted" style={{ margin: "10px 0 4px" }}>Table row counts</div>
        <div className="stats">
          {Object.entries(d.tables).map(([t, n]) => <Stat key={t} label={t} value={n} />)}
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          {d.database.path} · {fmtBytes(d.database.db.bytes)}
          {d.database.wal.exists ? ` + ${fmtBytes(d.database.wal.bytes)} WAL` : ""} · modified {fmtRel(d.database.db.modified_at, d.now)}
        </p>
      </div>

      {/* ── Gemini usage ── */}
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>Gemini requests today</h3>
          <span className="muted">resets at midnight Pacific, in {fmtSpan(d.gemini[0]?.resets_in_seconds ?? 0)}</span>
        </div>
        {d.gemini.map((g, i) => {
          const pct = Math.min(100, Math.round((g.used / g.limit) * 100));
          const tone = g.exhausted ? "bad" : pct >= 80 ? "warn" : "good";
          return (
            <div key={g.model} className="usage-row">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>{i + 1}. {g.model}{i === d.gemini.length - 1 ? <span className="muted"> (last resort)</span> : null}</span>
                <span className="muted">
                  {g.used} / {g.limit} requests · {g.tokens_today.toLocaleString()} input tokens
                  {g.exhausted ? " · spent, skipped until reset"
                    : g.projected_exhaustion_in_seconds != null ? ` · on pace to run out in ~${fmtSpan(g.projected_exhaustion_in_seconds)}` : ""}
                </span>
              </div>
              <div className="bar"><div className={`bar-fill ${tone}`} style={{ width: `${pct}%` }} /></div>
              <div className="muted">
                Last minute: {g.tokens_last_minute.toLocaleString()} / {g.tpm_budget.toLocaleString()} input tokens
              </div>
            </div>
          );
        })}
        <p className="muted" style={{ marginBottom: 0 }}>
          A model at its daily limit is skipped before any request is made, and the next one in the order above is used.
        </p>
      </div>

      {/* ── Jobs ── */}
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>Jobs</h3>
          <select value={jobStatus} onChange={(e) => setJobStatus(e.target.value)}>
            <option value="">all statuses</option>
            {JOB_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          <table className="jobs">
            <thead>
              <tr><th>#</th><th>Video</th><th>Job</th><th>Video status</th><th>Tries</th><th>Scheduled</th><th>Last error</th></tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>{j.id}</td>
                  <td>
                    <Link to={`/videos/${j.video_id}`}>{j.title ?? j.video_id}</Link>
                    {j.priority > 0 && <span className="pill" style={{ marginLeft: 6 }}>priority</span>}
                  </td>
                  <td><span className={`pill ${j.status === "running" ? "warn" : j.status === "failed" ? "bad" : j.status === "done" ? "good" : ""}`}>{j.status}</span></td>
                  <td>{j.video_status ?? <span className="muted">(missing)</span>}</td>
                  <td>{j.attempts}</td>
                  <td title={fmtDate(j.scheduled_at)}>{fmtRel(j.scheduled_at, d.now)}</td>
                  <td className="muted">{j.last_error ?? ""}</td>
                </tr>
              ))}
              {jobs.length === 0 && <tr><td colSpan={7} className="muted">No jobs.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Event log ── */}
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>Event log</h3>
          <div className="row">
            <input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 150 }} />
            <select value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">all levels</option>
              <option value="warn">warnings + errors</option>
              <option value="error">errors only</option>
            </select>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">all sources</option>
              {["worker", "job", "discovery", "gate", "scheduler", "startup", "api"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <EventList events={events} />
        {events.length >= limit && (
          <button style={{ marginTop: 10 }} onClick={() => setLimit((l) => l + 200)}>Load more</button>
        )}
      </div>

      {/* ── Config ── */}
      <div className="card">
        <h3>Effective configuration</h3>
        <table className="kv">
          <tbody>
            {([
              ["Scan interval", `${d.config.poll_interval_minutes} min`],
              ["Fetch spread window", `${d.config.fetch_spread_minutes} min`],
              ["Jitter between fetches", `${d.config.fetch_jitter_seconds[0]}–${d.config.fetch_jitter_seconds[1]}s`],
              ["Block suspension schedule", d.config.backoff_schedule_minutes.map((m) => fmtSpan(m * 60)).join(" → ")],
              ["Block check timeout", `${d.config.suspect_timeout_minutes}m (a lone failure is treated as a one-off after this)`],
              ["Gemini models (in order)", d.config.gemini_models.join(" → ")],
              ["Gemini input budget", `${d.config.gemini_tpm_budget.toLocaleString()} tokens/min per model`],
              ["Skip shorter than / longer than", `${d.config.min_duration_seconds}s / ${d.config.max_duration_seconds}s`],
              ["Cookies", d.config.cookies.exists ? `${d.config.cookies_file} (${fmtBytes(d.config.cookies.bytes)}, modified ${fmtRel(d.config.cookies.modified_at ?? null, d.now)})` : `none (${d.config.cookies_file} missing)`],
              ["Proxy", d.config.proxy_set ? "set" : "none"],
              ["Impersonation", d.config.impersonate ? `${d.config.impersonate} (curl_cffi ${d.config.curl_cffi_installed ? "installed" : "MISSING"})` : "off"],
              ["yt-dlp / Python", `${d.config.ytdlp_version ?? "?"} / ${d.config.python_version}`],
              ["Gemini key", d.config.gemini_key_set ? "set" : "MISSING"],
              ["Email", d.config.email_configured ? "configured" : "not configured"],
              ["Data dir", d.config.data_dir],
            ] as [string, string][]).map(([k, v]) => (
              <tr key={k}><td className="muted">{k}</td><td>{v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
