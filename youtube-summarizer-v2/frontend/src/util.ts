export function fmtDate(epoch?: number | null): string {
  if (!epoch) return "";
  return new Date(epoch * 1000).toLocaleString();
}

export function fmtDuration(seconds?: number | null): string {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export function statusPill(status: string): "good" | "warn" | "bad" | "" {
  if (status === "summarized") return "good";
  if (status === "failed") return "bad";
  if (status === "queued" || status === "fetching") return "warn";
  return "";
}

/** The backend tags rate-limit-caused failures with a "[rate-limited]" marker in
 * the reason, so the UI can flag them distinctly from genuine failures. */
export function isRateLimited(reason?: string | null): boolean {
  return !!reason && reason.toLowerCase().includes("[rate-limited]");
}

/** "3m 12s ago" / "in 5m" style relative time from an epoch (seconds). */
export function fmtRel(epoch?: number | null, now = Math.floor(Date.now() / 1000)): string {
  if (!epoch) return "—";
  const d = epoch - now;
  const abs = Math.abs(d);
  let t: string;
  if (abs < 60) t = `${abs}s`;
  else if (abs < 3600) t = `${Math.floor(abs / 60)}m ${abs % 60}s`;
  else if (abs < 86400) t = `${Math.floor(abs / 3600)}h ${Math.floor((abs % 3600) / 60)}m`;
  else t = `${Math.floor(abs / 86400)}d ${Math.floor((abs % 86400) / 3600)}h`;
  return d >= 0 ? `in ${t}` : `${t} ago`;
}

export function fmtBytes(n?: number | null): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}
