import { useEffect, useState } from "react";
import { api } from "../api";
import type { SystemStatus } from "../types";

/** Human-readable "in 3m" / "now" from a seconds-until value. */
function fmtIn(seconds: number): string {
  if (seconds <= 0) return "now";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/** Live worker/queue + backoff indicator, with an expandable schedule showing
 *  the next channel scan and which videos are due to be processed. Refreshes
 *  every 15s. */
export default function StatusBar() {
  const [s, setS] = useState<SystemStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [scanning, setScanning] = useState(false);

  const load = () => api.status().then(setS).catch(() => {});

  useEffect(() => {
    let alive = true;
    const tick = () => api.status().then((d) => alive && setS(d)).catch(() => {});
    tick();
    const t = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  async function scanNow() {
    setScanning(true);
    try {
      await api.poll();   // run discovery immediately
      await load();       // refresh the queue/schedule view
    } finally {
      setScanning(false);
    }
  }

  async function removeJob(videoId: string) {
    // Optimistically drop it so the UI feels instant; the next poll reconciles.
    setS((prev) =>
      prev ? { ...prev, upcoming: prev.upcoming.filter((u) => u.video_id !== videoId) } : prev,
    );
    try {
      await api.cancelQueued(videoId);
    } finally {
      load();
    }
  }

  if (!s) return null;

  const q = s.queue;
  const pending = q.pending ?? 0;
  const running = q.running ?? 0;
  const b = s.backoff;
  const nextPoll = s.next_poll_in_seconds;
  const upcoming = s.upcoming ?? [];

  return (
    <div className="statusbar-wrap">
      <div className="statusbar">
        <span>Queue:</span>
        <span className="pill">{pending} pending</span>
        {running > 0 && <span className="pill warn">{running} running</span>}
        <span
          className="pill schedule-toggle"
          title="Next scan of your channels for new uploads. Click to see which videos are scheduled to be processed."
          onClick={() => setOpen((o) => !o)}
        >
          🔄 Next poll: {nextPoll == null ? "—" : fmtIn(nextPoll)}
          {upcoming.length > 0 ? ` · ${upcoming.length} queued` : ""} {open ? "▴" : "▾"}
        </span>
        <span className="spacer" style={{ flex: 1 }} />
        {b.blocked ? (
          <span className="pill bad" title="YouTube is rate-limiting this server's IP. Transcript fetches will fail until this clears or traffic is routed through a different IP.">
            ⛔ Rate-limited by YouTube (level {b.backoff_level}) · {Math.ceil(b.seconds_remaining / 60)}m left
          </span>
        ) : b.recently_blocked ? (
          <span className="pill warn" title="Recently rate-limited. IP flags last 12–24h, so some transcript fetches may still fail.">
            ⚠ Recently rate-limited
          </span>
        ) : (
          <span className="pill good">● YouTube OK</span>
        )}
      </div>

      {open && (
        <div className="schedule-panel">
          <div className="schedule-head">
            <span className="muted">
              Channels are scanned every {s.poll_interval_minutes} min · next scan{" "}
              {nextPoll == null ? "unknown (scheduler not running)" : fmtIn(nextPoll)}.
              {upcoming.length === 0
                ? " No videos are queued for processing right now."
                : " Videos are processed one at a time, in this order:"}
            </span>
            <button className="schedule-scan" onClick={scanNow} disabled={scanning}>
              {scanning ? "Scanning…" : "Scan now"}
            </button>
          </div>
          {upcoming.length > 0 && (
            <ul className="schedule-list">
              {upcoming.map((j) => (
                <li key={j.video_id}>
                  <span className="when">
                    {j.due_in_seconds <= 0 ? "processing soon" : `in ${fmtIn(j.due_in_seconds)}`}
                  </span>
                  <span className="what">
                    {j.url ? (
                      <a href={j.url} target="_blank" rel="noreferrer">{j.title ?? j.video_id}</a>
                    ) : (
                      j.title ?? j.video_id
                    )}
                    {j.channel_name ? <span className="muted"> · {j.channel_name}</span> : null}
                    {j.priority > 0 ? <span className="pill" style={{ marginLeft: 6 }}>priority</span> : null}
                  </span>
                  <button
                    className="schedule-remove"
                    title="Remove this video from the queue"
                    onClick={() => removeJob(j.video_id)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
