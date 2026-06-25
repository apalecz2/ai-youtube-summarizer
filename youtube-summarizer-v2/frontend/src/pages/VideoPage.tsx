import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import type { VideoDetail } from "../types";
import { fmtDate, fmtDuration, statusPill, isRateLimited } from "../util";
import QuizView from "../components/QuizView";

export default function VideoPage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<VideoDetail | null>(null);
  const [error, setError] = useState("");
  const [showTranscript, setShowTranscript] = useState(false);
  const [action, setAction] = useState("");

  async function retry() {
    try {
      await api.retryVideo(id);
      setAction("Re-queued — it'll reprocess shortly.");
    } catch (e) {
      setAction(`Error: ${(e as Error).message}`);
    }
  }

  async function dismiss() {
    try {
      await api.dismissVideo(id);
      setAction("Dismissed — removed from 'needs attention'.");
    } catch (e) {
      setAction(`Error: ${(e as Error).message}`);
    }
  }

  useEffect(() => {
    setData(null);
    api.getVideo(id).then(setData).catch((e) => setError((e as Error).message));
  }, [id]);

  if (error) return <div className="empty">Error: {error}</div>;
  if (!data) return <p className="muted">Loading…</p>;

  const { video, summary, transcript } = data;

  return (
    <>
      <p><Link to="/">← Back to summaries</Link></p>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>{video.title ?? video.video_id}</h2>
        <div className="row muted">
          <span>{video.channel_name ?? "Unknown channel"}</span>
          {video.duration ? <span>· {fmtDuration(video.duration)}</span> : null}
          <span className={`pill ${statusPill(video.status)}`}>{video.status}</span>
          {video.url && <a href={video.url} target="_blank" rel="noreferrer">Watch on YouTube ↗</a>}
        </div>
        {video.skip_reason && video.status !== "failed" && (
          <p className="muted">Note: {video.skip_reason}</p>
        )}
      </div>

      {video.status === "failed" && video.skip_reason && (
        <div className="card error-banner">
          <h3 style={{ marginTop: 0 }}>
            {isRateLimited(video.skip_reason) ? "⛔ Failed — YouTube rate limit" : "⚠ Processing failed"}
          </h3>
          {isRateLimited(video.skip_reason) && (
            <p className="muted" style={{ marginTop: 0 }}>
              This video likely <strong>does</strong> have a transcript — the fetch was blocked by YouTube
              rate-limiting this server's IP, not by a missing caption track. Retry once the block clears,
              or route YouTube traffic through a different IP.
            </p>
          )}
          <pre className="error-detail">{video.skip_reason}</pre>
          <div className="row" style={{ marginTop: 10 }}>
            <button onClick={retry}>Retry</button>
            <button onClick={dismiss}>Dismiss</button>
            {video.url && (
              <a href={video.url} target="_blank" rel="noreferrer">Watch on YouTube ↗</a>
            )}
          </div>
          {action && <p className="muted" style={{ marginBottom: 0 }}>{action}</p>}
        </div>
      )}

      {summary ? (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3 style={{ margin: 0 }}>Summary</h3>
            <span className="muted">{summary.model} · {fmtDate(summary.created_at)}</span>
          </div>
          <div className="summary-md">
            <ReactMarkdown>{summary.summary_md}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <div className="card muted">No summary yet — it may still be queued.</div>
      )}

      {transcript && (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3 style={{ margin: 0 }}>Transcript <span className="muted">({transcript.source})</span></h3>
            <button onClick={() => setShowTranscript((v) => !v)}>
              {showTranscript ? "Hide" : "Show"}
            </button>
          </div>
          {showTranscript && <div className="transcript" style={{ marginTop: 12 }}>{transcript.text}</div>}
        </div>
      )}

      {(summary || transcript) && <QuizView videoId={id} initial={data.quiz} />}
    </>
  );
}
