import { mapScheduleToMissions } from "./mapSchedule";

const API_BASE = "http://localhost:8000/api/v1";

export async function fetchExplanation(
  scenarioId: string,
  requestId: string,
  userQuestion?: string
) {
  const res = await fetch(`${API_BASE}/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario_id: scenarioId,
      request_id: requestId,
      user_question: userQuestion,
    }),
  });
  if (!res.ok) throw new Error(`Explain failed: ${res.status}`);
  const data = await res.json();
  return data.explanation;
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
    intent: string;
    operations: { operation: string; request_id: string; value: any }[];
    requires_resolve: boolean;
    error?: string | null;
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
    can_apply: boolean;
  } | null;
}

export async function fetchWhatIf(
  baseScenarioId: string,
  userQuery: string
): Promise<WhatIfResponse> {
  const res = await fetch(`${API_BASE}/what-if`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_scenario_id: baseScenarioId,
      user_query: userQuery,
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
  satellite_id?: string;
  status: string; // ALTERNATIVES_FOUND | NO_FEASIBLE_ALTERNATIVES | REQUEST_ALREADY_SCHEDULED | PIPELINE_UNAVAILABLE
  reason_codes: string[];
  alternatives: AlternativeWindow[];
}

export async function fetchAlternatives(
  scenarioId: string,
  requestId: string,
  limit: number = 3
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

export interface RiskFactor {
  weight: number;
  factor_score?: number;
  points?: number;
  metrics?: Record<string, any>;
  state?: string;
  status?: string;
  best_alternative?: any;
  matched_events?: any[];
  context_events?: any[];
  matched_kp_readings?: any[];
  effective_kp_index?: number | null;
}

export interface RiskAssessment {
  scenario_id: string;
  request_id: string;
  satellite_id?: string;
  schedule_status: string; // SCHEDULED | UNSCHEDULED | UNKNOWN
  assessment_status: string; // ASSESSED | UNRESOLVED | RISK_UNAVAILABLE
  contact?: {
    station_id: string;
    window_id: string;
    scheduled_start: string;
    scheduled_end: string;
  } | null;
  risk_score?: number | null;
  risk_level?: string | null;
  reason_codes: string[];
  factors: Record<string, RiskFactor>;
  data_quality: {
    overall: string;
    space_weather?: string;
  };
  conflict_evidence?: Record<string, any> | null;
}

export async function fetchRiskAssessment(
  scenarioId: string,
  requestId: string,
  includeAlternatives: boolean = true
): Promise<RiskAssessment> {
  const res = await fetch(`${API_BASE}/risk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario_id: scenarioId,
      request_id: requestId,
      include_alternatives: includeAlternatives,
    }),
  });
  if (!res.ok) throw new Error(`Risk request failed: ${res.status}`);
  return res.json();
}