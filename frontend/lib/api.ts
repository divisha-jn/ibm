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
  includeWeather = true
): Promise<RiskAssessment> {
  const res = await fetch(`${API_BASE}/risk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scenario_id: scenarioId,
      request_id: requestId,
      include_weather: includeWeather,
    }),
  });
  if (!res.ok) throw new Error(`Risk assessment failed: ${res.status}`);
  return res.json();
}