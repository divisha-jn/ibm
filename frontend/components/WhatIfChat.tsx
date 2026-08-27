"use client";

import { useState, useEffect, useRef } from "react";
import styles from "./WhatIfChat.module.css";
import {
  fetchWhatIf,
  fetchExplanation,
  fetchChatHistory,
  saveChatTurn,
  WhatIfResponse,
} from "../lib/api";
import { Mission } from "../data/mockMissions";

const SCHEDULED_SUGGESTIONS = [
  "Why was this scheduled here?",
  "Why this time slot?",
  "Why this antenna?",
  "What constraints influenced this decision?",
  "Which other requests competed for this slot?",
  "What would happen if I changed the priority?",
];

const REJECTED_SUGGESTIONS = [
  "Why was this rejected?",
  "Which constraint caused the rejection?",
  "Which mission conflicted with this one?",
  "How much overlap caused the rejection?",
  "What could I change to schedule this?",
  "What if this becomes mandatory?",
];

// Questions that should route to /what-if instead of /explain
const WHAT_IF_KEYWORDS = [
  "what if", "what would happen", "what happens if",
  "if i change", "if i move", "if i delay", "if i increase", "if i decrease",
  "what would change", "what changes if", "can i give", "can we schedule",
  "becomes priority", "becomes mandatory", "must be scheduled", "has to run",
  "disable", "goes offline",
];

function isWhatIfQuestion(q: string): boolean {
  const lower = q.toLowerCase();
  return WHAT_IF_KEYWORDS.some((kw) => lower.includes(kw));
}

interface ChatTurn {
  query: string;
  response: WhatIfResponse | null;
  explanation: string | null;
  error: string | null;
  type: "explain" | "whatif";
}

interface Props {
  scenarioId: string;
  selectedMission: Mission | null;
}

// sessionId is stable for the lifetime of a (scenario × mission) pair.
// Stored in localStorage so it survives page refresh.
function getSessionId(scenarioId: string, missionId: string | null): string {
  const key = `chat_session__${scenarioId}__${missionId ?? "global"}`;
  if (typeof window === "undefined") return key;
  let id = localStorage.getItem(key);
  if (!id) {
    id = key;
    localStorage.setItem(key, id);
  }
  return id;
}

export default function WhatIfChat({ scenarioId, selectedMission }: Props) {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const prevMissionId = useRef<string | null>(null);

  // Compute the stable session key for the current (scenario × mission) pair
  const sessionId = getSessionId(scenarioId, selectedMission?.mission_id ?? null);

  // When mission changes: clear UI state and load history for the new session
  useEffect(() => {
    if (selectedMission?.mission_id !== prevMissionId.current) {
      prevMissionId.current = selectedMission?.mission_id ?? null;
      setTurns([]);
      setInput("");
    }

    // Load persisted history for this session
    fetchChatHistory(sessionId).then((history) => {
      if (history.length === 0) return;
      setTurns(
        history.map((t) => ({
          query: t.query,
          type: t.type as "explain" | "whatif",
          explanation: t.explanation,
          response: t.whatif_response as WhatIfResponse | null,
          error: t.error,
        }))
      );
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMission, sessionId]);

  async function handleSend(query?: string) {
    const q = (query ?? input).trim();
    if (!q || loading) return;

    setInput("");
    setLoading(true);
    setTurns((prev) => [...prev, { query: q, response: null, explanation: null, error: null, type: isWhatIfQuestion(q) ? "whatif" : "explain" }]);

    try {
      if (isWhatIfQuestion(q) || !selectedMission) {
        // Route to /what-if — inject selected mission id into the query if present
        const enrichedQuery = selectedMission
          ? `[Context: selected request is ${selectedMission.mission_id}] ${q}`
          : q;
        const response = await fetchWhatIf(scenarioId, enrichedQuery);
        setTurns((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { query: q, response, explanation: null, error: null, type: "whatif" };
          return copy;
        });
        saveChatTurn(sessionId, q, "whatif", null, response, null);
      } else {
        // Route to /explain — carry the selected request as context
        const explanation = await fetchExplanation(scenarioId, selectedMission.mission_id, q);
        setTurns((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { query: q, response: null, explanation, error: null, type: "explain" };
          return copy;
        });
        saveChatTurn(sessionId, q, "explain", explanation, null, null);
      }
    } catch (err) {
      const errorMsg = "Failed to reach the backend — is it running?";
      setTurns((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = {
          ...copy[copy.length - 1],
          error: errorMsg,
        };
        return copy;
      });
      saveChatTurn(sessionId, q, isWhatIfQuestion(q) ? "whatif" : "explain", null, null, errorMsg);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const suggestions = selectedMission?.status === "rejected"
    ? REJECTED_SUGGESTIONS
    : SCHEDULED_SUGGESTIONS;

  const isScheduled = selectedMission?.status === "scheduled";

  return (
    <div className={styles.wrapper}>
      <div className={styles.title}>AI Copilot</div>

      {/* Context card — shown when a mission is selected */}
      {selectedMission && (
        <div className={`${styles.contextCard} ${isScheduled ? styles.contextScheduled : styles.contextRejected}`}>
          <div className={styles.contextId}>{selectedMission.mission_id}</div>
          <div className={styles.contextMeta}>
            {isScheduled ? "Scheduled" : "Rejected"} · {selectedMission.station}
            {selectedMission.visibility_start && (
              <span> · {new Date(selectedMission.visibility_start).toISOString().slice(11, 16)}–{new Date(selectedMission.visibility_end).toISOString().slice(11, 16)} UTC</span>
            )}
          </div>
          <div className={styles.contextLabel}>
            {isScheduled ? "Understand this decision" : "Understand this rejection"}
          </div>
          <div className={styles.chips}>
            {suggestions.map((s) => (
              <button
                key={s}
                className={styles.chip}
                onClick={() => handleSend(s)}
                disabled={loading}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Empty state — no mission selected, no turns */}
      {!selectedMission && turns.length === 0 && (
        <div className={styles.emptyState}>
          Click any bar on the Gantt to explore it here, or type a what-if question directly.
        </div>
      )}

      {/* Chat history */}
      <div className={styles.history}>
        {turns.map((turn, i) => (
          <div key={i} className={styles.turn}>
            <div className={styles.userQuery}>{turn.query}</div>

            {!turn.response && !turn.explanation && !turn.error && (
              <div className={styles.loadingText}>Thinking...</div>
            )}

            {turn.error && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Error</div>
                {turn.error}
              </div>
            )}

            {/* Explain response */}
            {turn.explanation && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Analysis</div>
                {turn.explanation}
              </div>
            )}

            {/* What-if response */}
            {turn.response && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>
                  {turn.response.result ? "Proposed change" : "Not understood"}
                </div>
                {turn.response.result?.explanation ??
                  (turn.response.interpretation?.error
                    ? `Could not parse request: ${turn.response.interpretation.error}`
                    : "This query is not supported. Try asking about a specific request ID.")}

                {turn.response.result && (
                  <div className={styles.impactRow}>
                    {turn.response.result.impact.newly_scheduled.length > 0 && (
                      <span className={styles.impactGood}>
                        + {turn.response.result.impact.newly_scheduled.join(", ")}
                      </span>
                    )}
                    {turn.response.result.impact.newly_unscheduled.length > 0 && (
                      <span className={styles.impactBad}>
                        − {turn.response.result.impact.newly_unscheduled.join(", ")}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Input row */}
      <div className={styles.inputRow}>
        <input
          className={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            selectedMission
              ? `Ask anything about ${selectedMission.mission_id}...`
              : "Ask a what-if question..."
          }
          disabled={loading}
        />
        <button
          className={styles.sendButton}
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
