"use client";

import { useState } from "react";
import styles from "./WhatIfChat.module.css";
import { fetchWhatIf, WhatIfResponse } from "../lib/api";

interface ChatTurn {
  query: string;
  response: WhatIfResponse | null;
  error: string | null;
}

export default function WhatIfChat({ scenarioId }: { scenarioId: string }) {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);

  async function handleSend() {
    const query = input.trim();
    if (!query || loading) return;

    setInput("");
    setLoading(true);
    setTurns((prev) => [...prev, { query, response: null, error: null }]);

    try {
      const response = await fetchWhatIf(scenarioId, query);
      setTurns((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { query, response, error: null };
        return copy;
      });
    } catch (err) {
      setTurns((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = {
          query,
          response: null,
          error: "Failed to reach the what-if endpoint — is the backend running?",
        };
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

  return (
    <div className={styles.wrapper}>
      <div className={styles.title}>AI Copilot — What-If</div>

      <div className={styles.history}>
        {turns.length === 0 && (
          <div className={styles.emptyState}>
            Try: "What if SAT-B becomes priority 10?"
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i} className={styles.turn}>
            <div className={styles.userQuery}>{turn.query}</div>

            {!turn.response && !turn.error && (
              <div className={styles.loadingText}>Thinking...</div>
            )}

            {turn.error && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Error</div>
                {turn.error}
              </div>
            )}

            {turn.response && (
              <div className={styles.response}>
                <div className={styles.responseLabel}>Proposed change</div>
                {turn.response.result?.explanation ??
                  "No re-solve was needed for this query."}

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

      <div className={styles.inputRow}>
        <input
          className={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a what-if question..."
          disabled={loading}
        />
        <button
          className={styles.sendButton}
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}