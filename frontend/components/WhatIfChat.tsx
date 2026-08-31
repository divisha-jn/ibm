"use client";

import { useState, useEffect, useRef } from "react";
import styles from "./WhatIfChat.module.css";
import { fetchWhatIf, fetchAlternatives, fetchChatHistory, saveChatTurn, WhatIfResponse, AlternativesResponse, ChatTurnOut } from "../lib/api";
import { Mission } from "../data/mockMissions";

const SCHEDULED_SUGGESTIONS = [
  "Why was this scheduled here?",
  "Why this time slot?",
  "What constraints influenced this decision?",
  "What would happen if I changed the priority?",
];

const REJECTED_SUGGESTIONS = [
  "Why was this rejected?",
  "Which constraint caused the rejection?",
  "Which mission conflicted with this one?",
  "How much overlap caused the rejection?",
  "What could I change to schedule this?",
  "What if this becomes mandatory?",
  "Show ranked alternatives",
];

interface ChatTurn {
  query: string;
  response: WhatIfResponse | null;
  explanation: string | null;
  alternatives: AlternativesResponse | null;
  clarification_question: string | null;
  pending_clarification_for: string | null;
  error: string | null;
  type: "explain" | "whatif" | "alternatives" | "clarification";
}

interface Props {
  scenarioId: string;
  selectedMission: Mission | null;
}

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
  const [history, setHistory] = useState<ChatTurnOut[]>([]);
  const [loading, setLoading] = useState(false);
  const prevMissionId = useRef<string | null>(null);
  const historyEndRef = useRef<HTMLDivElement>(null);

  const sessionId = getSessionId(scenarioId, selectedMission?.mission_id ?? null);

  // Auto-scroll to latest message
  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  // When mission changes: clear UI and load persisted history
  useEffect(() => {
    if (selectedMission?.mission_id !== prevMissionId.current) {
      prevMissionId.current = selectedMission?.mission_id ?? null;
      setTurns([]);
      setHistory([]);
      setInput("");
    }

    fetchChatHistory(sessionId).then((loaded) => {
      if (loaded.length === 0) return;
      setHistory(loaded);
      setTurns(
        loaded.map((t) => ({
          query: t.query,
          type: t.type as "explain" | "whatif" | "alternatives" | "clarification",
          explanation: t.explanation,
          response: t.whatif_response as WhatIfResponse | null,
          alternatives: null,
          clarification_question: null,
          pending_clarification_for: null,
          error: t.error,
        }))
      );
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMission, sessionId]);

  // If the last turn was a clarification, prepend its context to the new query
  function buildClarifiedQuery(q: string): string {
    const lastTurn = turns[turns.length - 1];
    if (lastTurn?.clarification_question && lastTurn?.pending_clarification_for) {
      return `${lastTurn.pending_clarification_for} — clarification: ${q}`;
    }
    return q;
  }

  async function handleSend(query?: string) {
    const rawQ = (query ?? input).trim();
    if (!rawQ || loading) return;

    const q = buildClarifiedQuery(rawQ);
    setInput("");
    setLoading(true);

    // Optimistically add the turn; type will be corrected on response
    setTurns((prev) => [...prev, {
      query: rawQ, response: null, explanation: null, alternatives: null,
      clarification_question: null, pending_clarification_for: null,
      error: null, type: "whatif",
    }]);

    try {
      // Always send to /what-if first — Granite decides intent.
      // MODIFY_SCENARIO → run solver, show outcome
      // NEEDS_CLARIFICATION → show clarification bubble
      // UNSUPPORTED + mission selected → fall through to /explain
      const enrichedQuery = selectedMission
        ? `[Context: selected request is ${selectedMission.mission_id}] ${q}`
        : q;
      const response = await fetchWhatIf(scenarioId, enrichedQuery, history);
      const intent = response.interpretation.intent;

      if (intent === "NEEDS_CLARIFICATION") {
        const cq = response.interpretation.clarification_question ?? "Could you provide more details?";
        setTurns((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            query: rawQ, response: null, explanation: null, alternatives: null,
            clarification_question: cq, pending_clarification_for: q,
            error: null, type: "clarification",
          };
          return copy;
        });

      } else if (intent === "UNSUPPORTED" && selectedMission) {
        // Not a what-if command — route to /explain
        const data = await fetch("http://localhost:8000/api/v1/explain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            scenario_id: scenarioId,
            request_id: selectedMission.mission_id,
            user_question: q,
            conversation_history: history,
          }),
        }).then((r) => r.json());

        if (data.clarification_question) {
          setTurns((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = {
              query: rawQ, response: null, explanation: null, alternatives: null,
              clarification_question: data.clarification_question, pending_clarification_for: q,
              error: null, type: "clarification",
            };
            return copy;
          });
        } else {
          const explanation = data.explanation as string;
          setTurns((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = {
              query: rawQ, response: null, explanation, alternatives: null,
              clarification_question: null, pending_clarification_for: null,
              error: null, type: "explain",
            };
            return copy;
          });
          const saved: ChatTurnOut = { query: rawQ, type: "explain", explanation, whatif_response: null, risk_response: null, error: null, created_at: new Date().toISOString() };
          setHistory((h) => [...h, saved]);
          saveChatTurn(sessionId, rawQ, "explain", explanation, null, null);
        }

      } else {
        // MODIFY_SCENARIO (or UNSUPPORTED with no mission selected)
        setTurns((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            query: rawQ, response, explanation: null, alternatives: null,
            clarification_question: null, pending_clarification_for: null,
            error: null, type: "whatif",
          };
          return copy;
        });
        const saved: ChatTurnOut = { query: rawQ, type: "whatif", explanation: null, whatif_response: response as any, risk_response: null, error: null, created_at: new Date().toISOString() };
        setHistory((h) => [...h, saved]);
        saveChatTurn(sessionId, rawQ, "whatif", null, response as any, null);
      }

    } catch (err) {
      setTurns((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { ...copy[copy.length - 1], error: "Failed to reach the backend — is it running?" };
        return copy;
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleAlternatives() {
    if (!selectedMission || loading) return;
    const q = "Show ranked alternatives";

    setLoading(true);
    setTurns((prev) => [...prev, {
      query: q, response: null, explanation: null, alternatives: null,
      clarification_question: null, pending_clarification_for: null,
      error: null, type: "alternatives",
    }]);

    try {
      const alternatives = await fetchAlternatives(scenarioId, selectedMission.mission_id, 3);
      setTurns((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = {
          query: q, response: null, explanation: null, alternatives,
          clarification_question: null, pending_clarification_for: null,
          error: null, type: "alternatives",
        };
        return copy;
      });
    } catch (err) {
      setTurns((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { ...copy[copy.length - 1], error: "Failed to fetch alternatives — is the backend running?" };
        return copy;
      });
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

  const suggestions = selectedMission?.status === "rejected" ? REJECTED_SUGGESTIONS : SCHEDULED_SUGGESTIONS;
  const isScheduled = selectedMission?.status === "scheduled";

  return (
    <div className={styles.wrapper}>
      <div className={styles.title}>AI Copilot</div>

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
                onClick={() => (s === "Show ranked alternatives" ? handleAlternatives() : handleSend(s))}
                disabled={loading}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {!selectedMission && turns.length === 0 && (
        <div className={styles.emptyState}>
          Click any bar on the Gantt to explore it here, or type a what-if question directly.
        </div>
      )}

      <div className={styles.history}>
        {turns.map((turn, i) => (
          <div key={i} className={styles.turn}>
            <div className={styles.userQuery}>{turn.query}</div>

            {!turn.response && !turn.explanation && !turn.alternatives && !turn.clarification_question && !turn.error && (
              <div className={styles.loadingText}>Thinking</div>
            )}

            {turn.clarification_question && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Needs clarification</div>
                {turn.clarification_question}
              </div>
            )}

            {turn.error && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Error</div>
                {turn.error}
              </div>
            )}

            {turn.explanation && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Analysis</div>
                {turn.explanation}
              </div>
            )}

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

            {turn.alternatives && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Ranked Alternatives</div>
                {turn.alternatives.explanation && (
                  <div style={{ marginBottom: 10, color: "#e4e7eb" }}>{turn.alternatives.explanation}</div>
                )}
                {turn.alternatives.status === "ALTERNATIVES_FOUND" && turn.alternatives.alternatives.length > 0 ? (
                  turn.alternatives.alternatives.map((alt) => (
                    <div key={alt.window_id} style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #232931" }}>
                      <strong>#{alt.rank}</strong> — {alt.station_id}, {new Date(alt.scheduled_start).toISOString().slice(11, 16)}–{new Date(alt.scheduled_end).toISOString().slice(11, 16)} UTC
                      <div style={{ fontSize: 12, color: "#7c8792", marginTop: 4 }}>
                        Displaces {alt.ranking_metrics.displaced_count} mission(s), reschedules {alt.ranking_metrics.rescheduled_count}
                      </div>
                    </div>
                  ))
                ) : turn.alternatives.status === "NO_FEASIBLE_ALTERNATIVES" ? (
                  "No feasible alternative windows were found for this request."
                ) : turn.alternatives.status === "REQUEST_ALREADY_SCHEDULED" ? (
                  "This request is already scheduled — no alternatives needed."
                ) : (
                  "Alternatives are unavailable right now (solver pipeline inactive)."
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={historyEndRef} />
      </div>

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
