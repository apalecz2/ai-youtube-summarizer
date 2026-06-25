import { useEffect, useState } from "react";
import { api } from "../api";
import type { SystemStatus } from "../types";

/** Live worker/queue + backoff indicator. Refreshes every 15s. */
export default function StatusBar() {
  const [s, setS] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.status().then((d) => alive && setS(d)).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!s) return null;

  const q = s.queue;
  const pending = q.pending ?? 0;
  const running = q.running ?? 0;
  const b = s.backoff;

  return (
    <div className="statusbar">
      <span>Queue:</span>
      <span className="pill">{pending} pending</span>
      {running > 0 && <span className="pill warn">{running} running</span>}
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
  );
}
