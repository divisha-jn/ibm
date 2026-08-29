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

function levelClass(level: string | null | undefined) {
  if (level === "LOW") return "Low";
  if (level === "HIGH") return "High";
  return "Medium";
}

export default function RiskPanel({ scenarioId, selectedMission }: Props) {
  const [risk, setRisk] = useState<RiskAssessment | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedMission) {
      setRisk(null);
      setError(null);
      return;
    }
    setLoading(true);
    setRisk(null);
    setError(null);
    fetchRiskAssessment(scenarioId, selectedMission.mission_id)
      .then(setRisk)
      .catch(() => setError("Failed to fetch risk assessment — is the backend running?"))
      .finally(() => setLoading(false));
  }, [selectedMission, scenarioId]);

  if (!selectedMission) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.title}>Operational Risk</div>
        <div className={styles.emptyState}>
          Select a mission on the Gantt to see its risk assessment.
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.title}>Operational Risk</div>
        <div className={styles.loadingText}>Assessing {selectedMission.mission_id}...</div>
      </div>
    );
  }

  if (error || !risk) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.title}>Operational Risk</div>
        <div className={styles.emptyState}>{error ?? "No risk data available."}</div>
      </div>
    );
  }

  // Backend-declared failure states — show plainly, no fabricated score.
  if (risk.assessment_status === "RISK_UNAVAILABLE" || risk.assessment_status === "UNRESOLVED") {
    return (
      <div className={styles.wrapper}>
        <div className={styles.title}>Operational Risk — {risk.request_id}</div>
        <div className={styles.emptyState}>
          {risk.assessment_status === "RISK_UNAVAILABLE"
            ? "Risk assessment unavailable (solver pipeline inactive)."
            : "Risk assessment could not be resolved for this request."}
        </div>
      </div>
    );
  }

  // Unscheduled requests never get a numeric score — show status instead.
  const hasScore = risk.schedule_status === "SCHEDULED" && risk.risk_score != null;

  return (
    <div className={styles.wrapper}>
      <div className={styles.title}>Operational Risk — {risk.request_id}</div>

      {hasScore ? (
        <div className={styles.scoreRow}>
          <div className={`${styles.scoreCircle} ${styles[`level${levelClass(risk.risk_level)}`]}`}>
            <span className={styles.scoreNumber}>{risk.risk_score}</span>
            <span className={styles.scoreMax}>/ 100</span>
          </div>
          <div>
            <span className={`${styles.levelBadge} ${styles[`badge${levelClass(risk.risk_level)}`]}`}>
              {risk.risk_level} RISK
            </span>
            {risk.contact && (
              <div className={styles.contactMeta}>
                {risk.contact.station_id} ·{" "}
                {new Date(risk.contact.scheduled_start).toISOString().slice(11, 16)}–
                {new Date(risk.contact.scheduled_end).toISOString().slice(11, 16)} UTC
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className={styles.emptyState}>
          {selectedMission.mission_id} is not scheduled — no risk score is calculated for
          unscheduled requests.
        </div>
      )}

      {risk.reason_codes.length > 0 && (
        <div className={styles.reasonCodes}>
          {risk.reason_codes.map((code) => (
            <span key={code} className={styles.reasonTag}>
              {code}
            </span>
          ))}
        </div>
      )}

      {hasScore && Object.keys(risk.factors).length > 0 && (
        <div className={styles.factorsGrid}>
          {Object.entries(risk.factors).map(([key, factor]) => (
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
          ))}
        </div>
      )}

      {risk.data_quality?.overall && (
        <div className={styles.dataQuality}>
          Data quality: {risk.data_quality.overall}
          {risk.data_quality.space_weather &&
            risk.data_quality.space_weather !== risk.data_quality.overall &&
            ` (space weather: ${risk.data_quality.space_weather})`}
        </div>
      )}
    </div>
  );
}