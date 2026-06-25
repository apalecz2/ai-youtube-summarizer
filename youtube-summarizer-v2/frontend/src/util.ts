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
