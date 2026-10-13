import { Link } from "react-router-dom";
import type { AppEvent } from "../types";

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour12: false });
  return d.toDateString() === today.toDateString() ? time : `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

/** Compact monospace event rows. `linkVideos` turns video ids into links to the video page. */
export default function EventList({ events, linkVideos = true }: { events: AppEvent[]; linkVideos?: boolean }) {
  if (events.length === 0) return <p className="muted">No events.</p>;
  return (
    <div className="events">
      {events.map((e) => (
        <div key={e.id} className={`event ${e.level}`}>
          <span className="ev-time">{fmtTime(e.ts)}</span>
          <span className="ev-src">{e.source}</span>
          <span className="ev-msg">
            {e.message}
            {e.video_id && (
              <span className="ev-ref">
                {" "}
                {linkVideos ? <Link to={`/videos/${e.video_id}`}>{e.video_id}</Link> : e.video_id}
              </span>
            )}
            {e.job_id != null && <span className="ev-ref"> job#{e.job_id}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}
