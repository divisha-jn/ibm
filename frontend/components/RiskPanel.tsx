"use client";

import { useEffect, useState } from "react";
import styles from "./RiskPanel.module.css";
import { fetchRiskAssessment, saveChatTurn, RiskAssessment, ChatTurnOut } from "../lib/api";
import { Mission } from "../data/mockMissions";

interface Props {
  scenarioId: string;
  selectedMission: Mission | null;
  sessionId: string;
  conversationHistory: ChatTurnOut[];
  onRiskSaved: (turn: ChatTurnOut) => void;
}

const FACTOR_LABELS: Record<string, string> = {
  scheduling_flexibility: "Scheduling flexibility",
  station_redundancy: "Station redundancy",
  conflict_pressure: "Conflict pressure",
  recovery: "Recovery options",
  mission_priority: "Mission priority",
  space_weather: "Space weather",
};

const DEFAULT_FACTOR_ORDER = Object.keys(FACTOR_LABELS);

function levelClass(level: string | null | undefined) {
  if (level === "LOW") return "Low";
  if (level === "HIGH") return "High";
  if (level === "MEDIUM") return "Medium";
  return "NoData";
}

export default function RiskPanel({ scenarioId, selectedMission, sessionId, conversationHistory, onRiskSaved }: Props) {
  const [risk, setRisk] = useState<RiskAssessment | null>(null);
  const [loading, setLoading] = useState(false);
  const [dimReason, setDimReason] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedMission) {
      setRisk(null);
      setDimReason(null);
      return;
    }
    setLoading(true);
    setRisk(null);
    setDimReason(null);
    fetchRiskAssessment(scenarioId, selectedMission.mission_id, true, conversationHistory)
      .then((r) => {
        setRisk(r);
        const turn: ChatTurnOut = {
          query: `Risk assessment for ${selectedMission.mission_id}`,
          type: "risk",
          explanation: r.narrative ?? null,
          whatif_response: null,
          risk_response: r as any,
          error: null,
          created_at: new Date().toISOString(),
        };
        onRiskSaved(turn);
        saveChatTurn(sessionId, turn.query, "risk", r.narrative ?? null, null, null, r as any);
      })
      .catch(() => setDimReason("Failed to reach the backend."))
      .finally(() => setLoading(false));
  }, [selectedMission, scenarioId]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Decide whether we have a real score to show "alive," or should stay dimmed.
  const hasScore =
  risk?.schedule_status === "SCHEDULED" &&
  risk?.assessment_status === "ASSESSED" &&
  risk?.risk_score != null;

// "Answered" means the backend gave us a definitive result — scored or not.
// Only truly dim when nothing's selected, still loading, or the request failed outright.
const hasAnswer = !!risk && !loading;

let dimText: string | null = dimReason;
if (!dimText && !loading) {
  if (!selectedMission) dimText = "Select a mission to assess";
  else if (risk?.assessment_status === "RISK_UNAVAILABLE") dimText = "Risk pipeline unavailable";
  else if (risk?.assessment_status === "UNRESOLVED") dimText = "Could not be resolved — not scheduled";
  else if (risk && !hasScore) dimText = `${risk.request_id} is not scheduled`;
}

const lvl = hasScore ? levelClass(risk!.risk_level) : "NoData";
const isAlive = hasAnswer; // full brightness whenever we have any real answer

  const accentColor = lvl === "Low" ? "#24a148" : lvl === "Medium" ? "#ff9f1c" : lvl === "High" ? "#da1e28" : "#232931";

  return (
    <div
      className={`${styles.wrapper} ${isAlive ? styles.alive : styles.dimmed}`}
      style={{ borderTop: `2px solid ${accentColor}` }}
    >
       <div className={styles.title}>
        Operational Risk{risk ? ` — ${risk.request_id}` : ""}
        </div>

        {isAlive && risk!.narrative && (
        <div className={styles.narrative}>{risk!.narrative}</div>
        )}

        <div className={styles.scoreRow}>
        <div className={styles.scoreGauge}>
          {(() => {
            const radius = 30;
            const circumference = 2 * Math.PI * radius;
            const score = hasScore ? risk!.risk_score! : 0;
            const fill = (score / 100) * circumference;
            const colorMap: Record<string, string> = { Low: "#24a148", Medium: "#ff9f1c", High: "#da1e28", NoData: "#7c8792" };
            const color = colorMap[lvl] ?? "#7c8792";
            return (
              <svg width="72" height="72" viewBox="0 0 72 72">
                <circle cx="36" cy="36" r={radius} fill="none" stroke="#232931" strokeWidth="4" />
                <circle
                  cx="36" cy="36" r={radius} fill="none"
                  stroke={color} strokeWidth="4"
                  strokeDasharray={`${fill} ${circumference}`}
                  strokeDashoffset={circumference * 0.25}
                  strokeLinecap="round"
                  style={{ transition: "stroke-dasharray 0.6s ease" }}
                />
                <text x="36" y="33" textAnchor="middle" fill={color} fontSize="16" fontWeight="600" fontFamily="IBM Plex Mono, monospace">
                  {hasScore ? risk!.risk_score : "—"}
                </text>
                <text x="36" y="46" textAnchor="middle" fill="#7c8792" fontSize="9" fontFamily="IBM Plex Mono, monospace">
                  / 100
                </text>
              </svg>
            );
          })()}
        </div>
        <div>
          <span className={`${styles.levelBadge} ${styles[`badge${lvl}`]}`}>
            {hasScore ? `${risk!.risk_level} RISK` : selectedMission ? "NOT SCORED" : "NO DATA"}
          </span>
          {isAlive && risk!.contact && (
            <div className={styles.contactMeta}>
              {risk!.contact.station_id} ·{" "}
              {new Date(risk!.contact.scheduled_start).toISOString().slice(11, 16)}–
              {new Date(risk!.contact.scheduled_end).toISOString().slice(11, 16)} UTC
            </div>
          )}
          {!isAlive && dimText && <div className={styles.dimLabel}>{dimText}</div>}
        </div>
      </div>

      {isAlive && risk!.reason_codes.length > 0 && (
        <div className={styles.reasonCodes}>
          {risk!.reason_codes.map((code) => (
            <span key={code} className={styles.reasonTag}>
              {code}
            </span>
          ))}
        </div>
      )}

      <div className={styles.factorsGrid}>
        {isAlive && risk!.factors
          ? Object.entries(risk!.factors).map(([key, factor]) => (
              <div key={key} className={styles.factorRow}>
                <span className={styles.factorName}>{FACTOR_LABELS[key] ?? key}</span>
                <div className={styles.factorBarTrack}>
                  <div
                    className={styles.factorBarFill}
                    style={(() => {
                      const pct = factor.points != null && factor.weight ? (factor.points / factor.weight) * 100 : 0;
                      const color = pct < 40 ? "#24a148" : pct < 70 ? "#ff9f1c" : "#da1e28";
                      return { width: `${pct}%`, background: color };
                    })()}
                  />
                </div>
                <span className={styles.factorPoints}>
                  {factor.points ?? "–"}/{factor.weight}
                </span>
              </div>
            ))
          : DEFAULT_FACTOR_ORDER.map((key) => (
              <div key={key} className={styles.factorRow}>
                <span className={styles.factorName}>{FACTOR_LABELS[key]}</span>
                <div className={styles.factorBarTrack}>
                  <div className={styles.factorBarFill} style={{ width: "0%" }} />
                </div>
                <span className={styles.factorPoints}>–</span>
              </div>
            ))}
      </div>

      {isAlive && risk!.data_quality?.overall && (
        <div className={styles.dataQuality}>
          Data quality: {risk!.data_quality.overall}
          {risk!.data_quality.space_weather &&
            risk!.data_quality.space_weather !== risk!.data_quality.overall &&
            ` (space weather: ${risk!.data_quality.space_weather})`}
        </div>
      )}
    </div>
  );
}