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

// ---------------------------------------------------------------------------
// Chat history — SQLite persistence
// ---------------------------------------------------------------------------

export interface ChatTurnOut {
  query: string;
  type: "explain" | "whatif";
  explanation: string | null;
  whatif_response: WhatIfResponse | null;
  error: string | null;
  created_at: string;
}

export async function fetchChatHistory(sessionId: string): Promise<ChatTurnOut[]> {
  const res = await fetch(`${API_BASE}/chat/history/${encodeURIComponent(sessionId)}`);
  if (!res.ok) return [];           // silently return empty on any failure
  const data = await res.json();
  return data.turns ?? [];
}

export async function saveChatTurn(
  sessionId: string,
  query: string,
  type: "explain" | "whatif",
  explanation: string | null,
  whatifResponse: WhatIfResponse | null,
  error: string | null,
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
        error,
      }),
    });
  } catch {
    // persistence failure is non-fatal — chat still works in-session
  }
}