export interface Video {
  video_id: string;
  channel_id: string | null;
  title: string | null;
  channel_name: string | null;
  duration: number | null;
  published_at: number | null;
  url: string | null;
  status: string;
  skip_reason: string | null;
  discovered_at: number | null;
  updated_at: number | null;
}

export interface SummaryListItem {
  id: number;
  video_id: string;
  detail_level: number;
  model: string | null;
  created_at: number;
  title: string | null;
  channel_name: string | null;
  url: string | null;
  duration: number | null;
}

export interface Summary {
  id: number;
  video_id: string;
  detail_level: number;
  model: string | null;
  summary_md: string;
  created_at: number;
}

export interface Transcript {
  video_id: string;
  lang: string | null;
  source: string | null;
  text: string;
  fetched_at: number;
}

export interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export interface Quiz {
  id?: number;
  video_id: string;
  model: string | null;
  questions: QuizQuestion[];
  created_at?: number;
}

export interface VideoDetail {
  video: Video;
  summary: Summary | null;
  transcript: Transcript | null;
  quiz: Quiz | null;
}

export interface Channel {
  channel_id: string;
  title: string | null;
  channel_name: string | null;
  added_at: number;
  active: number;
}

export interface ChannelFilter {
  id: number;
  channel_id: string;
  field: string;
  match_type: string;
  value: string;
  action: string;
}

export interface SearchResult {
  video_id: string;
  rank: number;
  sources: string;
  snippet: string;
  title: string | null;
  channel_name: string | null;
  url: string | null;
}

export interface BackoffStatus {
  blocked: boolean;
  blocked_until: number;
  seconds_remaining: number;
  backoff_level: number;
  last_block_at: number | null;
  last_success_at: number | null;
  recently_blocked: boolean;
  manual: boolean;
}

export interface UpcomingJob {
  video_id: string;
  title: string | null;
  channel_name: string | null;
  url: string | null;
  scheduled_at: number;
  due_in_seconds: number;
  priority: number;
}

export interface WorkerStatus {
  alive: boolean;
  seconds_since_heartbeat: number | null;
  stalled: boolean;
}

export interface SystemStatus {
  now: number;
  queue: Record<string, number>;
  backoff: BackoffStatus;
  worker: WorkerStatus;
  poll_interval_minutes: number;
  next_poll_at: number | null;
  next_poll_in_seconds: number | null;
  upcoming: UpcomingJob[];
}

// ── System / diagnostics ──
export interface HealthCheck {
  id: string;
  level: "ok" | "warn" | "bad";
  title: string;
  detail: string;
}

export interface WorkerActivity {
  job_id: number;
  video_id: string;
  attempt: number | null;
  stage: string;
  running_seconds: number;
  stage_seconds: number;
}

export interface FileInfo { exists: boolean; bytes: number; modified_at: number | null }

export interface Diagnostics {
  now: number;
  health: HealthCheck[];
  worker: { alive: boolean; seconds_since_heartbeat: number | null; stalled: boolean; activity: WorkerActivity | null };
  backoff: BackoffStatus;
  scheduler: {
    next_poll_at: number | null;
    next_poll_in_seconds: number | null;
    last_discovery: { at: number; channels: number; new: number; filtered: number; pre_existing: number } | null;
  };
  queue: Record<string, number>;
  videos: Record<string, number>;
  videos_last_24h: Record<string, number>;
  tables: Record<string, number>;
  database: { path: string; db: FileInfo; wal: FileInfo };
  problems: Record<string, Record<string, unknown>[]>;
  config: {
    poll_interval_minutes: number;
    fetch_spread_minutes: number;
    fetch_jitter_seconds: [number, number];
    backoff_schedule_minutes: number[];
    min_duration_seconds: number;
    max_duration_seconds: number;
    cookies_file: string | null;
    cookies: Partial<FileInfo>;
    proxy_set: boolean;
    impersonate: string | null;
    curl_cffi_installed: boolean;
    ytdlp_version: string | null;
    python_version: string;
    gemini_key_set: boolean;
    email_configured: boolean;
    app_base_url_set: boolean;
    data_dir: string;
  };
}

export interface AppEvent {
  id: number;
  ts: number;
  level: "info" | "warn" | "error";
  source: string;
  message: string;
  video_id: string | null;
  job_id: number | null;
}

export interface JobRow {
  id: number;
  video_id: string;
  job_type: string;
  priority: number;
  scheduled_at: number;
  attempts: number;
  status: string;
  last_error: string | null;
  detail_level: number;
  send_email: number;
  created_at: number;
  title?: string | null;
  channel_name?: string | null;
  video_status?: string | null;
  url?: string | null;
}

export interface VideoTrace {
  video_id: string;
  jobs: JobRow[];
  events: AppEvent[];
}
