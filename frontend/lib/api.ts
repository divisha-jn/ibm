import { mapScheduleToMissions } from "./mapSchedule";

const API_BASE = "http://localhost:8000/api/v1";

// ---------------------------------------------------------------------------
// Chat history persistence — backed by SQLite via POST/GET /api/v1/chat/history
// ---------------------------------------------------------------------------

export interface ChatTurnOut {
  query: string;
  type: string;
  explanation: string | null;
  whatif_response: Record<string, any> | null;
  risk_response: Record<string, any> | null;
  error: string | null;
  created_at: string;
}

export async function fetchChatHistory(sessionId: string): Promise<ChatTurnOut[]> {
  try {
    const res = await fetch(`${API_BASE}/chat/history/${encodeURIComponent(sessionId)}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.turns ?? [];
  } catch {
    return [];
  }
}

export async function saveChatTurn(
  sessionId: string,
  query: string,
  type: string,
  explanation: string | null,
  whatifResponse: Record<string, any> | null,
  error: string | null,
  riskResponse: Record<string, any> | null = null,
): Promise<void> {
  try {
    await fetch(`${API_BASE}/chat/history`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        query,
        type,
        explanation,
        whatif_response: whatifResponse,
        risk_response: riskResponse,
        error,
      }),
    });
  } catch {
    // Best-effort — never block the UI if persistence fails
  }
}

export async function fetchSchedule() {
  const res = await fetch(`${API_BASE}/schedule`);
  const data = await res.json();
  return mapScheduleToMissions(data);
}

export interface WhatIfResponse {
  what_if_id: string;
  base_scenario_id: string;
  user_query: string;
  interpretation: {
    intent: string;  // "MODIFY_SCENARIO" | "UNSUPPORTED" | "NEEDS_CLARIFICATION"
    operations: { operation: string; request_id: string; value: any }[];
    requires_resolve: boolean;
    error?: string | null;
    clarification_question?: string | null;
  };
  result: {
    solver_status: string;
    impact: {
      newly_scheduled: string[];
      newly_unscheduled: string[];
      unchanged: string[];
    };
    proposed_schedule: Record<string, any>;
    explanation: string;
    conflict_evidence?: Record<string, any> | null;
  } | null;
}

export async function fetchWhatIf(
  baseScenarioId: string,
  userQuery: string,
  conversationHistory: ChatTurnOut[] = [],
): Promise<WhatIfResponse> {
  const res = await fetch(`${API_BASE}/what-if`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_scenario_id: baseScenarioId,
      user_query: userQuery,
      conversation_history: conversationHistory,
    }),
  });
  if (!res.ok) throw new Error(`What-if request failed: ${res.status}`);
  return res.json();
}

export interface RankingMetrics {
  displaced_count: number;
  displaced_priority_total: number;
  rescheduled_count: number;
  rescheduled_priority_total: number;
}

export interface AlternativeWindow {
  rank: number;
  alternative_type: string;
  window_id: string;
  station_id: string;
  scheduled_start: string;
  scheduled_end: string;
  duration_seconds: number;
  displaced_request_ids: string[];
  rescheduled_request_ids: string[];
  ranking_metrics: RankingMetrics;
}

export interface AlternativesResponse {
  scenario_id: string;
  request_id: string;
  satellite_id?: string | null;
  // ALTERNATIVES_FOUND | NO_FEASIBLE_ALTERNATIVES | REQUEST_ALREADY_SCHEDULED | PIPELINE_UNAVAILABLE
  status: string;
  reason_codes: string[];
  alternatives: AlternativeWindow[];
  explanation?: string | null;  // Granite narrative; null when Granite unavailable
}

export async function fetchAlternatives(
  scenarioId: string,
  requestId: string,
  limit = 3
): Promise<AlternativesResponse> {
  const res = await fetch(`${API_BASE}/alternatives`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario_id: scenarioId,
      request_id: requestId,
      limit,
    }),
  });
  if (!res.ok) throw new Error(`Alternatives request failed: ${res.status}`);
  return res.json();
}

export interface RiskFactorDetail {
  weight: number;
  points: number;
  factor_score: number;
  metrics?: Record<string, any> | null;
  state?: string | null;
}

export interface RiskAssessment {
  scenario_id: string;
  request_id: string;
  satellite_id: string;
  schedule_status: string;       // "SCHEDULED" | "UNSCHEDULED"
  assessment_status: string;     // "ASSESSED" | "UNRESOLVED" | "PIPELINE_UNAVAILABLE"
  contact?: {
    station_id: string;
    window_id: string;
    scheduled_start: string;
    scheduled_end: string;
  } | null;
  risk_score?: number | null;    // 0–100
  risk_level?: string | null;    // "LOW" | "MEDIUM" | "HIGH"
  reason_codes: string[];
  factors: Record<string, RiskFactorDetail>;
  data_quality?: {
    overall: string;
    space_weather: string;
  } | null;
  narrative?: string | null;
}

export async function fetchRiskAssessment(
  scenarioId: string,
  requestId: string,
  includeWeather = true,
  conversationHistory: ChatTurnOut[] = [],
): Promise<RiskAssessment> {
  const res = await fetch(`${API_BASE}/risk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario_id: scenarioId,
      request_id: requestId,
      include_weather: includeWeather,
      conversation_history: conversationHistory,
    }),
  });
  if (!res.ok) throw new Error(`Risk assessment failed: ${res.status}`);
  return res.json();
}