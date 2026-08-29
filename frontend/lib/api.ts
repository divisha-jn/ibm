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
  factor_score: number;
  points: number;
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
  satellite_id: string;
  schedule_status: string;
  assessment_status: string;
  contact?: {
    station_id: string;
    window_id: string;
    scheduled_start: string;
    scheduled_end: string;
  };
  risk_score: number;
  risk_level: string;
  reason_codes: string[];
  factors: {
    scheduling_flexibility: RiskFactor;
    station_redundancy: RiskFactor;
    conflict_pressure: RiskFactor;
    recovery: RiskFactor;
    mission_priority: RiskFactor;
    space_weather: RiskFactor;
  };
  data_quality: {
    overall: string;
    space_weather: string;
  };
}

// MOCK — matches contracts/risk_assessment.example.json exactly.
// Swap the body of this function for a real fetch() once P2/P4 add
// the actual /risk endpoint. Keep the function signature the same
// so nothing else needs to change.
export async function fetchRiskAssessment(
  scenarioId: string,
  requestId: string
): Promise<RiskAssessment> {
  // Simulate network delay so loading states can be tested too
  await new Promise((resolve) => setTimeout(resolve, 400));

  return {
    scenario_id: scenarioId,
    request_id: requestId,
    satellite_id: "NORAD_48274",
    schedule_status: "SCHEDULED",
    assessment_status: "ASSESSED",
    contact: {
      station_id: "GS_SG_01",
      window_id: "VW_0012",
      scheduled_start: "2026-08-25T10:00:00Z",
      scheduled_end: "2026-08-25T10:05:00Z",
    },
    risk_score: 40,
    risk_level: "MEDIUM",
    reason_codes: ["SINGLE_FEASIBLE_WINDOW", "SINGLE_USABLE_STATION"],
    factors: {
      scheduling_flexibility: {
        weight: 20,
        factor_score: 1.0,
        points: 20,
        metrics: {
          duration_feasible_window_count: 1,
          total_feasible_visibility_seconds: 600,
          total_start_slack_seconds: 300,
        },
      },
      station_redundancy: {
        weight: 15,
        factor_score: 1.0,
        points: 15,
        metrics: {
          usable_station_count: 1,
          usable_station_ids: ["GS_SG_01"],
        },
      },
      conflict_pressure: {
        weight: 25,
        factor_score: 0.0,
        points: 0,
        metrics: {
          blocked_window_count: 0,
          duration_feasible_window_count: 1,
          blocked_window_fraction: 0.0,
          blocked_window_ids: [],
          conflicting_request_ids: [],
        },
      },
      recovery: {
        weight: 20,
        state: "NOT_APPLICABLE_SCHEDULED",
        factor_score: 0.0,
        points: 0,
        best_alternative: null,
      },
      mission_priority: {
        weight: 10,
        factor_score: 0.5,
        points: 5,
        metrics: {
          priority: 5,
          approved_scale_min: 1,
          approved_scale_max: 10,
          meaning: "OPERATIONAL_CONSEQUENCE",
          mandatory_included: false,
        },
      },
      space_weather: {
        weight: 10,
        status: "COMPLETE",
        state: "CLEAR",
        factor_score: 0.0,
        points: 0,
        matched_events: [],
        context_events: [],
        matched_kp_readings: [],
        effective_kp_index: null,
      },
    },
    data_quality: {
      overall: "COMPLETE",
      space_weather: "COMPLETE",
    },
  };
}
