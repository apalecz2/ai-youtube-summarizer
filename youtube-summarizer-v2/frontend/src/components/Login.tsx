import { useState } from "react";
import { api } from "../api";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(password);
      onLogin();
    } catch {
      setError("Invalid password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <h2>▶ YouTube Summarizer</h2>
      <p className="muted">Sign in to view your summaries.</p>
      <form onSubmit={submit}>
        <input
          type="password"
          placeholder="Password"
          value={password}
          autoFocus
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="primary" disabled={busy || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error && <span className="error">{error}</span>}
      </form>
    </div>
  );
}
