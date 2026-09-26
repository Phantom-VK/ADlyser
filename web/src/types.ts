/** Shapes of the API responses: the library, and debug.json (what the Decision Trace shows). */

export type CandidateStatus =
  | "selected"
  | "vetoed"
  | "blocked"
  | "pacing_rejected"
  | "not_scene_change"
  | "below_min_score";

export interface ReviewVerdict {
  decision: "approve" | "veto";
  reason: string;
  retry: string | null;
}

export interface ToolCall {
  tool: string;
  args: Record<string, number>;
  frames: number;
}

export interface CandidateRecord {
  t: number;
  silence_s: number;
  kind: "hard" | "black" | "silence";
  is_scene_change: boolean;
  break_score: number;
  boundary_reason: string;
  status: CandidateStatus;
  reason: string;
  review: ReviewVerdict | null;
  review_trace: ToolCall[];
}

export interface SceneInfo {
  index: number;
  start: number;
  end: number;
  summary: string;
  dominant_activity: string;
  activity_tags: string[];
  safety_tags: string[];
  unknown: boolean;
}

export interface SceneRecord {
  scene: SceneInfo;
  sweep_added: string[];
  unknown_before_sweep: boolean;
}

export interface ShortlistEntry {
  brand_id: string;
  name: string;
  similarity: number;
  fit: number | null;
  reason: string;
}

export interface BlockedRecord {
  brand_id: string;
  name: string;
  tags: string[];
}

export interface BreakRecord {
  break_id: string | null;
  t: number;
  break_score: number;
  outcome: "brand" | "promo" | "dropped";
  brand_id: string | null;
  brand_name: string | null;
  before_scene: number;
  after_scene: number;
  shortlist: ShortlistEntry[];
  blocked: BlockedRecord[];
  sweep_added: Record<string, string[]>;
  review: ReviewVerdict | null;
  review_trace: ToolCall[];
  history: string[];
  reason: string;
}

export interface Brand {
  id: string;
  name: string;
  category: string;
  tagline: string;
  description: string;
  target_contexts: string[];
  negative_tags: string[];
  negative_contexts_raw: string[];
}

export interface Funnel {
  silences: number;
  long_enough: number;
  with_cut: number;
  in_window: number;
  after_spacing_cap: number;
}

export interface DebugReport {
  video: string;
  duration_s: number;
  funnel: Funnel;
  candidates: CandidateRecord[];
  scenes: SceneRecord[];
  breaks: BreakRecord[];
  brands: Brand[];
  loops: number;
  wall_s: number;
  /** The break-score threshold; absent in reports made before it was recorded. */
  min_break_score?: number | null;
  /** Where the opening titles end (0 = none found) and the closing titles start; absent in older reports. */
  intro_end?: number;
  outro_start?: number | null;
  /** Per prompt: `requests` are real model calls, `cached` are cache hits. */
  llm_stats: Record<string, Record<string, number>>;
}

export interface LibraryItem {
  name: string;
  video: string;
  video_url: string;
  size_bytes: number;
  processed: boolean;
  duration_s: number | null;
  breaks: number;
  candidates: number;
  wall_s: number | null;
  uploaded: boolean;
}

/** A video with a finished analysis, as GET /api/videos lists it. */
export interface AnalysedVideo extends LibraryItem {
  /** When the analysis finished, in seconds since the epoch. */
  analysed_at: number;
}

export interface AppConfig {
  upload_max_mb: number;
  upload_suffixes: string[];
}

export interface AddedBrand {
  id: string;
  name: string;
  record: Record<string, unknown>;
}

export type JobStatus = "idle" | "running" | "done" | "error";

export interface NodeEvent {
  type: "node";
  node: string;
  elapsed_s: number;
}

/** What a pipeline node is doing right now, e.g. "Analysing stretch 7 of 20". */
export interface DetailEvent {
  type: "detail";
  node: string;
  text: string;
  done?: number;
  total?: number;
  /** A milestone inside a node ("signals": speech and cuts are measured). */
  stage?: string;
}

export type ProgressEvent = NodeEvent | DetailEvent;

export interface EndEvent {
  type: "end";
  status: JobStatus;
  error: string;
}
