/**
 * Tiny typed fetch wrapper. All requests go same-origin (dev uses Vite's proxy,
 * prod is served by FastAPI), with credentials so the session cookie is sent.
 */
import type {
  Channel, ChannelFilter, Quiz, SearchResult, SummaryListItem,
  SystemStatus, Transcript, Video, VideoDetail,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function form(data: Record<string, string>): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(data).toString(),
  };
}

export const api = {
  // ── Auth ──
  me: () => req<{ authenticated: boolean }>("/auth/me"),
  login: (password: string) => req<{ status: string }>("/auth/login", form({ password })),
  logout: () => req<{ status: string }>("/auth/logout", { method: "POST" }),

  // ── Content ──
  listSummaries: (limit = 50, offset = 0) =>
    req<{ summaries: SummaryListItem[] }>(`/summaries?limit=${limit}&offset=${offset}`),
  listVideos: (status?: string) =>
    req<{ videos: Video[] }>(`/videos${status ? `?status=${status}` : ""}`),
  getVideo: (id: string) => req<VideoDetail>(`/videos/${id}`),
  getTranscript: (id: string) => req<Transcript>(`/transcripts/${id}`),
  search: (q: string) => req<{ query: string; results: SearchResult[] }>(`/search?q=${encodeURIComponent(q)}`),
  getQuiz: (id: string) => req<Quiz>(`/videos/${id}/quiz`),
  makeQuiz: (id: string, n = 5) => req<Quiz>(`/videos/${id}/quiz?num_questions=${n}`, { method: "POST" }),

  // ── Channels ──
  listChannels: () => req<{ channels: Channel[] }>("/channels"),
  addChannel: (channel_id: string, title?: string) =>
    req("/channels", form(title ? { channel_id, title } : { channel_id })),
  removeChannel: (id: string) => req(`/channels/${id}`, { method: "DELETE" }),
  listFilters: (id: string) => req<{ channel_id: string; filters: ChannelFilter[] }>(`/channels/${id}/filters`),
  addFilter: (id: string, value: string, action: string) =>
    req(`/channels/${id}/filters`, form({ value, action })),
  removeFilter: (filterId: number) => req(`/channels/filters/${filterId}`, { method: "DELETE" }),

  // ── Actions ──
  summarize: (url: string, detail = 2) => req("/summarize", form({ url, detail: String(detail) })),
  poll: () => req<{ status: string; new: number }>("/poll", { method: "POST" }),
  status: () => req<SystemStatus>("/status"),
  cancelQueued: (id: string) => req<{ status: string; video_id: string }>(`/queue/${id}`, { method: "DELETE" }),

  // ── Reconcile failures ──
  retryVideo: (id: string) => req<{ status: string; enqueued: boolean }>(`/videos/${id}/retry`, { method: "POST" }),
  dismissVideo: (id: string) => req<{ status: string }>(`/videos/${id}/dismiss`, { method: "POST" }),
  retryFailures: () => req<{ status: string; count: number; total: number }>("/failures/retry", { method: "POST" }),
  dismissFailures: () => req<{ status: string; count: number }>("/failures/dismiss", { method: "POST" }),
};
