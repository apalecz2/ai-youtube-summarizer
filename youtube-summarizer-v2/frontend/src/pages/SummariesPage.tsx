import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { SummaryListItem, Video } from "../types";
import { fmtDate, fmtDuration, isRateLimited } from "../util";

export default function SummariesPage() {
  const [items, setItems] = useState<SummaryListItem[]>([]);
  const [failures, setFailures] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState("");
  const [detail, setDetail] = useState(2);
  const [msg, setMsg] = useState("");

  // Silent refresh — keeps Recent summaries / failures live as the backend
  // processes the queue, without flashing the "Loading…" state each time.
  const refresh = () => {
    api.listSummaries().then((r) => setItems(r.summaries)).catch(() => {}).finally(() => setLoading(false));
    api.listVideos("failed").then((r) => setFailures(r.videos)).catch(() => setFailures([]));
  };
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, []);

  async function summarize(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api.summarize(url, detail);
      setMsg("Queued — it will appear here once fetched (spread out to mimic real browsing).");
      setUrl("");
    } catch (err) {
      setMsg(`Error: ${(err as Error).message}`);
    }
  }

  async function poll() {
    setMsg("Checking channels…");
    try {
      const r = await api.poll();
      setMsg(`Discovery done — ${r.new} new video(s) queued.`);
    } catch (err) {
      setMsg(`Error: ${(err as Error).message}`);
    }
  }

  async function retryOne(id: string) {
    try {
      await api.retryVideo(id);
      setFailures((f) => f.filter((v) => v.video_id !== id));
      setMsg("Re-queued — it'll appear under Recent summaries once processed.");
    } catch (err) {
      setMsg(`Error: ${(err as Error).message}`);
    }
  }

  async function dismissOne(id: string) {
    try {
      await api.dismissVideo(id);
      setFailures((f) => f.filter((v) => v.video_id !== id));
    } catch (err) {
      setMsg(`Error: ${(err as Error).message}`);
    }
  }

  async function retryAll() {
    try {
      const r = await api.retryFailures();
      setFailures([]);
      setMsg(`Re-queued ${r.count} of ${r.total} failed video(s).`);
    } catch (err) {
      setMsg(`Error: ${(err as Error).message}`);
    }
  }

  async function dismissAll() {
    try {
      const r = await api.dismissFailures();
      setFailures([]);
      setMsg(`Dismissed ${r.count} failure(s).`);
    } catch (err) {
      setMsg(`Error: ${(err as Error).message}`);
    }
  }

  return (
    <>
      <div className="card">
        <h3>Summarize a video now</h3>
        <form className="row" onSubmit={summarize}>
          <input
            style={{ flex: 1, minWidth: 240 }}
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <select value={detail} onChange={(e) => setDetail(Number(e.target.value))}>
            <option value={1}>Overview</option>
            <option value={2}>Thorough</option>
            <option value={3}>Expert</option>
          </select>
          <button className="primary" disabled={!url}>Summarize</button>
          <button type="button" onClick={poll}>Poll channels</button>
        </form>
        {msg && <p className="muted" style={{ marginBottom: 0 }}>{msg}</p>}
      </div>

      {failures.length > 0 && (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3>Needs attention ({failures.length})</h3>
            <div className="row">
              <button onClick={retryAll} title="Re-queue all failed videos">Retry all</button>
              <button onClick={dismissAll} title="Acknowledge and hide all failures">Dismiss all</button>
            </div>
          </div>
          {failures.map((v) => (
            <div key={v.video_id} className="card error-banner">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <Link to={`/videos/${v.video_id}`}><strong>{v.title ?? v.video_id}</strong></Link>
                <span className="pill bad">{isRateLimited(v.skip_reason) ? "rate-limited" : "failed"}</span>
              </div>
              <div className="muted" style={{ marginTop: 2 }}>
                {v.channel_name ?? "Unknown channel"}{v.updated_at ? ` · ${fmtDate(v.updated_at)}` : ""}
              </div>
              {v.skip_reason && <pre className="error-detail">{v.skip_reason}</pre>}
              <div className="row" style={{ marginTop: 10 }}>
                <button onClick={() => retryOne(v.video_id)}>Retry</button>
                <button onClick={() => dismissOne(v.video_id)}>Dismiss</button>
              </div>
            </div>
          ))}
        </>
      )}

      <h3>Recent summaries</h3>
      {loading && <p className="muted">Loading…</p>}
      {!loading && items.length === 0 && (
        <div className="empty">No summaries yet. Add channels or summarize a URL above.</div>
      )}
      {items.map((s) => (
        <Link key={s.id} to={`/videos/${s.video_id}`} className="card" style={{ display: "block" }}>
          <h3 style={{ marginBottom: 4 }}>{s.title ?? s.video_id}</h3>
          <div className="muted">
            {s.channel_name ?? "Unknown channel"}
            {s.duration ? ` · ${fmtDuration(s.duration)}` : ""} · {fmtDate(s.created_at)}
          </div>
        </Link>
      ))}
    </>
  );
}
