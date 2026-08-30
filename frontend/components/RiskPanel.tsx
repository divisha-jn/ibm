"use client";

import { useEffect, useState } from "react";
import styles from "./RiskPanel.module.css";
import { fetchRiskAssessment, RiskAssessment } from "../lib/api";
import { Mission } from "../data/mockMissions";

interface Props {
  scenarioId: string;
  selectedMission: Mission | null;
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

export default function RiskPanel({ scenarioId, selectedMission }: Props) {
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
    fetchRiskAssessment(scenarioId, selectedMission.mission_id)
      .then((r) => setRisk(r))
      .catch(() => setDimReason("Failed to reach the backend."))
      .finally(() => setLoading(false));
  }, [selectedMission, scenarioId]);

  // Decide whether we have a real score to show "alive," or should stay dimmed.
  const hasScore =
    risk?.schedule_status === "SCHEDULED" &&
    risk?.assessment_status === "ASSESSED" &&
    risk?.risk_score != null;

  let dimText: string | null = dimReason;
  if (!dimText && !loading) {
    if (!selectedMission) dimText = "Select a mission to assess";
    else if (risk?.assessment_status === "RISK_UNAVAILABLE") dimText = "Risk pipeline unavailable";
    else if (risk?.assessment_status === "UNRESOLVED") dimText = "Could not be resolved";
    else if (risk && !hasScore) dimText = `${risk.request_id} is not scheduled`;
  }

  const lvl = hasScore ? levelClass(risk!.risk_level) : "NoData";
  const isAlive = hasScore && !loading;

  return (
    <div className={`${styles.wrapper} ${isAlive ? styles.alive : styles.dimmed}`}>
      <div className={styles.title}>
        Operational Risk{risk ? ` — ${risk.request_id}` : ""}
      </div>

      <div className={styles.scoreRow}>
        <div className={`${styles.scoreCircle} ${styles[`level${lvl}`]}`}>
          <span className={styles.scoreNumber}>
            {isAlive ? risk!.risk_score : "—"}
          </span>
          <span className={styles.scoreMax}>/ 100</span>
        </div>
        <div>
          <span className={`${styles.levelBadge} ${styles[`badge${lvl}`]}`}>
            {isAlive ? `${risk!.risk_level} RISK` : "NO DATA"}
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
        {isAlive
          ? Object.entries(risk!.factors).map(([key, factor]) => (
              <div key={key} className={styles.factorRow}>
                <span className={styles.factorName}>{FACTOR_LABELS[key] ?? key}</span>
                <div className={styles.factorBarTrack}>
                  <div
                    className={styles.factorBarFill}
                    style={{
                      width: `${
                        factor.points != null && factor.weight
                          ? (factor.points / factor.weight) * 100
                          : 0
                      }%`,
                    }}
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