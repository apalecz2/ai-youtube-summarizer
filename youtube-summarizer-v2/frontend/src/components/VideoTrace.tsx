import { useEffect, useState } from "react";
import { api } from "../api";
import type { VideoTrace as Trace } from "../types";
import { fmtRel } from "../util";
import EventList from "./EventList";

/** Collapsible "what happened to this video" panel: its jobs + event history. */
export default function VideoTrace({ videoId }: { videoId: string }) {
  const [open, setOpen] = useState(false);
  const [t, setT] = useState<Trace | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    api.videoTrace(videoId).then(setT).catch((e) => setErr((e as Error).message));
  }, [open, videoId]);

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Processing trace</h3>
        <button onClick={() => setOpen((v) => !v)}>{open ? "Hide" : "Show"}</button>
      </div>
      {open && (
        <div style={{ marginTop: 12 }}>
          {err && <p className="error">{err}</p>}
          {t && (
            <>
              <div className="muted">Jobs</div>
              {t.jobs.length === 0 ? <p className="muted">No jobs for this video.</p> : (
                <ul className="schedule-list">
                  {t.jobs.map((j) => (
                    <li key={j.id}>
                      <span className="when">#{j.id} · {j.status}</span>
                      <span className="what">
                        attempts {j.attempts} · scheduled {fmtRel(j.scheduled_at)}
                        {j.last_error ? <span className="muted"> · {j.last_error}</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="muted" style={{ marginTop: 10 }}>Events (oldest first)</div>
              <EventList events={t.events} linkVideos={false} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
