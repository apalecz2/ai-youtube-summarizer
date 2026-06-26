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

export interface SystemStatus {
  now: number;
  queue: Record<string, number>;
  backoff: BackoffStatus;
  poll_interval_minutes: number;
  next_poll_at: number | null;
  next_poll_in_seconds: number | null;
  upcoming: UpcomingJob[];
}
