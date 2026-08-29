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

function levelClass(level: string) {
  if (level === "LOW") return "Low";
  if (level === "HIGH") return "High";
  return "Medium";
}

export default function RiskPanel({ scenarioId, selectedMission }: Props) {
  const [risk, setRisk] = useState<RiskAssessment | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedMission) {
      setRisk(null);
      return;
    }
    setLoading(true);
    setRisk(null);
    fetchRiskAssessment(scenarioId, selectedMission.mission_id)
      .then(setRisk)
      .catch(() => setRisk(null))
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

  if (loading || !risk) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.title}>Operational Risk</div>
        <div className={styles.loadingText}>Assessing {selectedMission.mission_id}...</div>
      </div>
    );
  }

  const lvl = levelClass(risk.risk_level);

  return (
    <div className={styles.wrapper}>
      <div className={styles.title}>Operational Risk — {risk.request_id}</div>

      <div className={styles.scoreRow}>
        <div className={`${styles.scoreCircle} ${styles[`level${lvl}`]}`}>
          <span className={styles.scoreNumber}>{risk.risk_score}</span>
          <span className={styles.scoreMax}>/ 100</span>
        </div>
        <div>
          <span className={`${styles.levelBadge} ${styles[`badge${lvl}`]}`}>
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

      {risk.reason_codes.length > 0 && (
        <div className={styles.reasonCodes}>
          {risk.reason_codes.map((code) => (
            <span key={code} className={styles.reasonTag}>
              {code}
            </span>
          ))}
        </div>
      )}

      <div className={styles.factorsGrid}>
        {Object.entries(risk.factors).map(([key, factor]) => (
          <div key={key} className={styles.factorRow}>
            <span className={styles.factorName}>{FACTOR_LABELS[key] ?? key}</span>
            <div className={styles.factorBarTrack}>
              <div
                className={styles.factorBarFill}
                style={{ width: `${(factor.points / factor.weight) * 100}%` }}
              />
            </div>
            <span className={styles.factorPoints}>
              {factor.points}/{factor.weight}
            </span>
          </div>
        ))}
      </div>

      <div className={styles.dataQuality}>
        Data quality: {risk.data_quality.overall}
        {risk.data_quality.space_weather !== risk.data_quality.overall &&
          ` (space weather: ${risk.data_quality.space_weather})`}
      </div>
    </div>
  );
}