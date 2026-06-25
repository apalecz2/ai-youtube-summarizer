import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { SearchResult } from "../types";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    try {
      const r = await api.search(q.trim());
      setResults(r.results);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="row" onSubmit={run}>
        <input
          style={{ flex: 1 }}
          placeholder="Search across all summaries & transcripts…"
          value={q}
          autoFocus
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="primary" disabled={busy}>Search</button>
      </form>

      {results && results.length === 0 && <div className="empty">No matches.</div>}
      <div style={{ marginTop: 16 }}>
        {results?.map((r) => (
          <Link key={r.video_id} to={`/videos/${r.video_id}`} className="card" style={{ display: "block" }}>
            <h3 style={{ marginBottom: 4 }}>{r.title ?? r.video_id}</h3>
            <div className="muted">{r.channel_name} · matched in {r.sources}</div>
            <p style={{ marginBottom: 0 }} dangerouslySetInnerHTML={{ __html: highlight(r.snippet) }} />
          </Link>
        ))}
      </div>
    </>
  );
}

// The backend wraps FTS matches in [brackets]; render them emphasized safely.
function highlight(snippet: string): string {
  const escaped = snippet
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return escaped.replace(/\[(.+?)\]/g, "<mark>$1</mark>");
}
