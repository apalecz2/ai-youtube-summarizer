import { useEffect, useState } from "react";
import { api } from "../api";
import type { Channel, ChannelFilter } from "../types";

export default function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [newId, setNewId] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [error, setError] = useState("");

  const load = () => api.listChannels().then((r) => setChannels(r.channels));
  useEffect(() => { load(); }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.addChannel(newId.trim(), newTitle.trim() || undefined);
      setNewId(""); setNewTitle("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <div className="card">
        <h3>Add a channel</h3>
        <form className="row" onSubmit={add}>
          <input placeholder="Channel ID (UC…)" value={newId} onChange={(e) => setNewId(e.target.value)} />
          <input placeholder="Label (optional)" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
          <button className="primary" disabled={!newId.trim()}>Add</button>
        </form>
        <p className="muted" style={{ marginBottom: 0 }}>
          Tip: the browser extension can add the channel you're currently viewing in one click.
        </p>
        {error && <p className="error">{error}</p>}
      </div>

      {channels.length === 0 && <div className="empty">No channels tracked yet.</div>}
      {channels.map((c) => (
        <ChannelCard key={c.channel_id} channel={c} onRemoved={load} />
      ))}
    </>
  );
}

function ChannelCard({ channel, onRemoved }: { channel: Channel; onRemoved: () => void }) {
  const [filters, setFilters] = useState<ChannelFilter[]>([]);
  const [value, setValue] = useState("");
  const [action, setAction] = useState("include");

  const load = () => api.listFilters(channel.channel_id).then((r) => setFilters(r.filters));
  useEffect(() => { load(); }, [channel.channel_id]);

  async function addFilter(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    await api.addFilter(channel.channel_id, value.trim(), action);
    setValue("");
    load();
  }

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <strong>{channel.title ?? channel.channel_name ?? channel.channel_id}</strong>
          {channel.channel_name && channel.channel_name !== channel.title && (
            <div className="muted">{channel.channel_name}</div>
          )}
          <div className="muted">{channel.channel_id}</div>
        </div>
        <button
          onClick={() => api.removeChannel(channel.channel_id).then(onRemoved)}
        >
          Remove
        </button>
      </div>

      <div style={{ marginTop: 12 }}>
        <div className="muted" style={{ marginBottom: 6 }}>
          Title filters {filters.length === 0 && "— none (every upload is summarized)"}
        </div>
        {filters.map((f) => (
          <div key={f.id} className="row" style={{ marginBottom: 4 }}>
            <span className={`pill ${f.action === "exclude" ? "bad" : "good"}`}>{f.action}</span>
            <span>title contains “{f.value}”</span>
            <button onClick={() => api.removeFilter(f.id).then(load)} style={{ padding: "2px 8px" }}>✕</button>
          </div>
        ))}
        <form className="row" onSubmit={addFilter} style={{ marginTop: 8 }}>
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="include">include</option>
            <option value="exclude">exclude</option>
          </select>
          <input placeholder="title contains…" value={value} onChange={(e) => setValue(e.target.value)} />
          <button disabled={!value.trim()}>Add filter</button>
        </form>
      </div>
    </div>
  );
}
