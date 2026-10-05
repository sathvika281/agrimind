import { friendlyError } from "./copy";
import { getDict } from "./i18n";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";

export interface User {
  id: number;
  email: string;
  created_at: string;
}
export interface Farm {
  id: number;
  name: string;
  location: string;
  soil_type: string;
  created_at: string;
  /** Optional, FARMER-PROVIDED context (absent/null = "not provided"; never guessed). */
  primary_crop?: string | null;
  irrigation_method?: "rainfed" | "drip" | "sprinkler" | "flood" | "other" | null;
  season?: "kharif" | "rabi" | "summer" | null;
  planting_date?: string | null; // YYYY-MM-DD
  notes?: string | null;
  context_updated_at?: string | null;
}
export type FarmPatch = Partial<Pick<Farm, "name" | "location" | "soil_type" | "primary_crop" | "irrigation_method" | "season" | "planting_date" | "notes">>;
export interface AnalysisResult {
  likely_issue: string;
  explanation: string;
  recommended_actions: string[];
  precautions: string[];
  uncertainty: string;
  severity?: "low" | "medium" | "high" | "unknown";
  observations?: string[];
  when_to_seek_help?: string;
  // Phase 3 (all optional: older results don't have them)
  possible_alternatives?: { possibility: string; how_to_tell: string }[];
  evidence_for?: string[];
  evidence_against?: string[];
  unknowns?: string[];
  immediate_actions?: string[];
  monitoring_steps?: string[];
  follow_up_questions?: string[];
  uncertainty_level?: "low" | "some" | "high" | "unknown";
  image_quality?: "good" | "limited" | "poor" | "not_provided";
  image_guidance?: string;
  // Phase 13 (optional: older results don't have them)
  verdict?: string;
  quick_questions?: { question: string; options: string[] }[];
  change?: { status: "better" | "same" | "worse" | "unclear"; note: string } | null;
  // Agentic investigation (optional: only present when it ran)
  sources?: { title: string; institution: string; url: string; excerpt?: string }[];
  agent_steps?: { agent: string; status: "ok" | "skipped" | "failed" | "retry"; note?: string }[];
}
export interface Weather {
  location_name: string;
  temperature_c: number | null;
  humidity_pct: number | null;
  precipitation_mm: number | null;
  wind_kmh: number | null;
  temp_min_c: number | null;
  temp_max_c: number | null;
  past_3d_rain_mm: number | null;
  next_3d_rain_mm: number | null;
  trend: string;
  fetched_at?: string;
}
export interface Analysis {
  id: number;
  farm_id: number;
  farm_name: string;
  crop: string;
  symptoms: string;
  language: string;
  input_type?: string;
  has_image?: boolean;
  result: AnalysisResult;
  weather?: Weather | null;
  weather_note?: string | null;
  /** Other-language versions of this same check (written on request); absent/empty on older results. */
  translations?: Record<string, AnalysisResult>;
  created_at: string;
  /** Set when this check refines ("refine") or follows up ("followup") an earlier one. */
  parent_id?: number | null;
  link_kind?: "refine" | "followup" | null;
}

export interface WeatherRisk {
  kind: "extreme_heat" | "heavy_rain" | "humid_wet" | "hot_dry";
  action: string;
  humidity_pct: number | null;
  rain_mm: number | null;
  temp_max_c: number | null;
}
export type EventKind = "sowed" | "irrigated" | "fertilised" | "sprayed" | "weeded" | "harvested" | "other";
export interface FarmEvent {
  id: number;
  kind: EventKind;
  event_date: string; // YYYY-MM-DD
  note: string | null;
  created_at: string;
}

/** Farm history, derived on the server ONLY from this farm's stored checks (never sample data or weather). */
export type Sev = "low" | "medium" | "high" | "unknown";
export interface InsightEvidence {
  analysis_id: number;
  at: string;
}
export interface InsightCheck extends InsightEvidence {
  crop: string;
  issue: string;
  severity: Sev;
}
export interface InsightTrend {
  kind: "recurring" | "more_frequent" | "less_frequent" | "repeated_high" | "stable";
  issue: string;
  count: number;
  window: number;
  earlier_count?: number | null;
  severity?: Sev | null;
  evidence: InsightEvidence[];
}
export interface Insights {
  farm_id: number;
  level: "none" | "one" | "limited" | "enough";
  total: number;
  first_at: string | null;
  last_at: string | null;
  latest: InsightCheck | null;
  severity_counts: Record<Sev, number>;
  unclear_count: number;
  issues: { label: string; count: number; last_seen: string; evidence: InsightEvidence[] }[];
  recent: InsightCheck[];
  trends: InsightTrend[];
  comparison: { previous: InsightCheck; latest: InsightCheck; same_issue: boolean; comparable: boolean; same_crop: boolean; severity_changed: boolean } | null;
}

/** Rule-based next-step guidance (keys + facts, computed on the server from stored evidence only). */
export type DecisionState = "no_actionable_evidence" | "seek_expert_help" | "verify" | "monitor";
export interface Decision {
  farm_id: number;
  analysis_id: number | null;
  state: DecisionState;
  level: "none" | "one" | "limited" | "enough";
  history_total: number;
  observed: { crop: string; issue: string; unclear: boolean; severity: Sev; uncertainty: string; image_quality: string; input_type: string; checked_at: string } | null;
  evidence: { kind: "this_check" | "severity" | "history_same_issue" | "history_insufficient" | "history_isolated" | "trend"; value?: string | null; count?: number | null; window?: number | null; dates: InsightEvidence[] }[];
  actions: ("inspect_plants" | "compare_plants" | "check_spread" | "record_clearer_photo" | "recheck_if_changes" | "consult_expert" | "add_detail")[];
  limitations: ("no_treatment" | "severity_not_recorded" | "history_insufficient" | "no_farm_context" | "context_not_causal")[];
  expert_reason: "severity_high" | "repeated_high" | "recurring" | "more_frequent" | null;
  context: { field: "primary_crop" | "irrigation_method" | "season" | "planting_date" | "soil_type" | "location"; value: string }[];
}

/** What deserves attention in a farm's STORED checks (keys + facts; at most 3 items). */
export interface Proactive {
  farm_id: number;
  level: "none" | "attention" | "important";
  total_checks: number;
  items: {
    priority: "attention" | "important";
    issue: string;
    crop: string;
    reasons: { kind: "latest_high" | "repeated_high" | "recurring" | "more_frequent" | "unresolved_verify"; count?: number | null; window?: number | null; earlier_count?: number | null; dates: InsightEvidence[] }[];
    actions: Decision["actions"];
    expert_suggested: boolean;
    evidence_count: number;
    latest_at: string;
    /** Navigation reference to a check the signed-in farmer owns; the Result page enforces ownership. */
    analysis_id: number;
  }[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string = "",
    /** True when trying the same request again could plausibly succeed (never retried automatically). */
    public retryable: boolean = false,
    public requestId: string = "",
  ) {
    super(message);
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

// Overridable via VITE_ANALYSIS_TIMEOUT_MS (used only to test the timeout UI quickly).
export const ANALYSIS_TIMEOUT_MS = Number(import.meta.env.VITE_ANALYSIS_TIMEOUT_MS) || 75_000;
const TIMEOUT_MESSAGE = "The analysis is taking longer than expected. You can try again.";

interface RequestOpts {
  quiet401?: boolean;
  timeoutMs?: number;
  headers?: Record<string, string>;
}

async function request<T>(method: string, path: string, body?: unknown, opts?: RequestOpts): Promise<T> {
  let res: Response;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const headers: Record<string, string> = { ...(opts?.headers ?? {}) };
  // For FormData the browser sets the multipart boundary itself.
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";

  const controller = opts?.timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), opts!.timeoutMs) : null;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      credentials: "include",
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal: controller?.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(friendlyError("timeout", 0, TIMEOUT_MESSAGE), 0, "timeout", true);
    }
    throw new ApiError(friendlyError("network", 0, ""), 0, "network", true);
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (res.status === 204) return undefined as T;

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }

  if (!res.ok) {
    const d = data as { detail?: unknown; code?: unknown; request_id?: unknown } | null;
    let message = typeof d?.detail === "string" ? d.detail : "";
    if (res.status === 401 && !opts?.quiet401) onUnauthorized?.();
    const retryable = res.status === 500 || res.status === 502 || res.status === 503 || res.status === 504;
    const code = typeof d?.code === "string" ? d.code : "";
    const wait = Number(res.headers.get("Retry-After"));
    // Wording comes from the active-language dictionary; backend values/codes are never shown to the farmer.
    message = res.status === 429 && wait > 0 ? getDict().err.rate(wait) : friendlyError(code, res.status, message);
    throw new ApiError(
      message,
      res.status,
      code,
      retryable,
      typeof d?.request_id === "string" ? d.request_id : res.headers.get("X-Request-ID") ?? "",
    );
  }
  return data as T;
}

/** A random key for one logical analysis attempt (reused when the farmer taps "Try again"). */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

export const api = {
  me: () => request<User>("GET", "/auth/me", undefined, { quiet401: true }),
  register: (email: string, password: string) => request<User>("POST", "/auth/register", { email, password }, { quiet401: true }),
  login: (email: string, password: string) => request<User>("POST", "/auth/login", { email, password }, { quiet401: true }),
  logout: () => request<void>("POST", "/auth/logout"),
  farms: () => request<Farm[]>("GET", "/farms"),
  createFarm: (f: { name: string; location: string; soil_type: string }) => request<Farm>("POST", "/farms", f),
  /** Edit what the farmer entered about a farm: omitted = unchanged, null/"" = clear. */
  updateFarm: (id: number, patch: FarmPatch) => request<Farm>("PATCH", `/farms/${id}`, patch),
  analyses: () => request<Analysis[]>("GET", "/analyses"),
  analysis: (id: number | string) => request<Analysis>("GET", `/analyses/${id}`),
  createAnalysis: (a: { farm_id: number; crop: string; symptoms: string; image?: File | null; language?: string; follow_up_of?: number | null }, idempotencyKey?: string) => {
    const fd = new FormData();
    fd.append("farm_id", String(a.farm_id));
    fd.append("crop", a.crop);
    fd.append("symptoms", a.symptoms);
    fd.append("language", a.language ?? "en"); // the language the analysis should be written in
    if (a.image) fd.append("image", a.image);
    if (a.follow_up_of) fd.append("follow_up_of", String(a.follow_up_of));
    return request<Analysis>("POST", "/analyses", fd, {
      timeoutMs: ANALYSIS_TIMEOUT_MS,
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    });
  },
  /** Real weather for a farm's saved location; {weather: null, note} when unavailable (never an error page). */
  farmWeather: (farmId: number) => request<{ weather: Weather | null; note: string | null; risks?: WeatherRisk[] }>("GET", `/farms/${farmId}/weather`),
  /** Answer the quick questions of a stored check: one new, linked check (the model runs once). */
  refineAnalysis: (id: number, answers: { question: string; answer: string }[], language?: string, idempotencyKey?: string) =>
    request<Analysis>("POST", `/analyses/${id}/refine`, { answers, language }, { timeoutMs: ANALYSIS_TIMEOUT_MS, headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined }),
  /** Everything stored about the signed-in farmer, as a JSON file (no photos, no password hash). */
  exportMyData: async (): Promise<Blob> => {
    let res: Response;
    try {
      res = await fetch(`${BASE}/auth/me/export`, { credentials: "include" });
    } catch {
      throw new ApiError(friendlyError("network", 0, ""), 0, "network", true);
    }
    if (!res.ok) throw new ApiError(friendlyError("", res.status, ""), res.status, "", res.status >= 500);
    return res.blob();
  },
  /** Delete the account and everything it owns. A wrong password is a 403 (not a 401, which would sign you out). */
  deleteAccount: (password: string) => request<void>("DELETE", "/auth/me", { password }, { quiet401: true }),
  farmEvents: (farmId: number) => request<FarmEvent[]>("GET", `/farms/${farmId}/events`),
  addFarmEvent: (farmId: number, e: { kind: EventKind; event_date?: string | null; note?: string | null }) => request<FarmEvent>("POST", `/farms/${farmId}/events`, e),
  deleteFarmEvent: (farmId: number, eventId: number) => request<void>("DELETE", `/farms/${farmId}/events/${eventId}`),
  /** Write this check again in another language (one cached model call on the server). */
  translateAnalysis: (id: number, language: string) =>
    request<Analysis>("POST", `/analyses/${id}/translate`, { language }, { timeoutMs: ANALYSIS_TIMEOUT_MS }),
  /** What this farm's stored checks show over time (deterministic, scoped to the signed-in user's farm). */
  farmInsights: (farmId: number) => request<Insights>("GET", `/farms/${farmId}/insights`),
  /** Rule-based next step for a farm's latest check, or "as of" a specific check. Read-only. */
  farmDecision: (farmId: number, analysisId?: number) =>
    request<Decision>("GET", `/farms/${farmId}/decision-support${analysisId != null ? `?analysis_id=${analysisId}` : ""}`),
  /** What deserves attention in this farm's stored checks. Read-only. */
  farmProactive: (farmId: number) => request<Proactive>("GET", `/farms/${farmId}/proactive`),
  imageUrl: (id: number) => `${BASE}/analyses/${id}/image`,
};
