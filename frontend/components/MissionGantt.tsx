"use client";

import { useMemo, useEffect } from "react";
import styles from "./MissionGantt.module.css";
import { Mission } from "../data/mockMissions";
import { fetchSchedule } from "../lib/api";
import { useState } from "react";

function toMinutes(iso: string, horizonStart: number) {
  return (new Date(iso).getTime() - horizonStart) / 60000;
}

function formatTime(ms: number) {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

interface Props {
  selectedMission: Mission | null;
  onSelectMission: (m: Mission | null) => void;
}

export default function MissionGantt({ selectedMission, onSelectMission }: Props) {
  const [missions, setMissions] = useState<Mission[]>([]);

  useEffect(() => {
    fetchSchedule()
      .then(setMissions)
      .catch((err) => console.error("Failed to load schedule:", err));
  }, []);

  const horizonStart = useMemo(() => {
    if (missions.length === 0) return Date.now();
    const starts = missions
      .filter((m) => m.visibility_start)
      .map((m) => new Date(m.visibility_start).getTime());
    return starts.length ? Math.min(...starts) : Date.now();
  }, [missions]);

  const horizonEnd = useMemo(() => {
    if (missions.length === 0) return Date.now() + 3600000;
    const ends = missions
      .filter((m) => m.visibility_end)
      .map((m) => new Date(m.visibility_end).getTime());
    return ends.length ? Math.max(...ends) : Date.now() + 3600000;
  }, [missions]);

  const totalMinutes = Math.max((horizonEnd - horizonStart) / 60000, 1);

  const stations = useMemo(
    () => Array.from(new Set(missions.filter((m) => m.visibility_start).map((m) => m.station))),
    [missions]
  );

  const ticks = useMemo(() => {
    const out: { label: string; pct: number }[] = [];
    const stepMinutes = totalMinutes > 180 ? 30 : totalMinutes > 60 ? 15 : 5;
    for (let t = 0; t <= totalMinutes; t += stepMinutes) {
      const date = new Date(horizonStart + t * 60000);
      out.push({
        label: formatTime(date.getTime()),
        pct: (t / totalMinutes) * 100,
      });
    }
    return out;
  }, [totalMinutes, horizonStart]);

  const rejected = missions.filter((m) => m.status === "rejected");

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.title}>Schedule — Planning Horizon</span>
        <span className={styles.horizon}>
          {formatTime(horizonStart)} – {formatTime(horizonEnd)}
        </span>
      </div>

      <div className={styles.axis}>
        {ticks.map((t, i) => (
          <span key={`${t.label}-${i}`} className={styles.axisTick} style={{ left: `${t.pct}%` }}>
            {t.label}
          </span>
        ))}
      </div>

      {stations.map((station) => (
        <div key={station} className={styles.row}>
          <div className={styles.stationLabel}>{station}</div>
          <div className={styles.track}>
            {missions
              .filter((m) => m.station === station && m.visibility_start)
              .map((m) => {
                const startPct =
                  (toMinutes(m.visibility_start, horizonStart) / totalMinutes) * 100;
                const widthPct = (m.duration_minutes / totalMinutes) * 100;
                const isSelected = selectedMission?.mission_id === m.mission_id;
                return (
                  <div
                    key={m.mission_id}
                    className={`${styles.block} ${
                      m.status === "rejected" ? styles.rejected : styles.scheduled
                    } ${isSelected ? styles.selected : ""}`}
                    style={{ left: `${startPct}%`, width: `${Math.max(widthPct, 6)}%` }}
                    onClick={() => onSelectMission(selectedMission?.mission_id === m.mission_id ? null : m)}
                    title={`${m.mission_id} — ${m.status}`}
                  >
                    {m.mission_id}
                  </div>
                );
              })}
          </div>
        </div>
      ))}

      <div className={styles.legend}>
        <span>
          <span className={styles.legendSwatch} style={{ background: "#0f62fe" }} />
          Scheduled
        </span>
        <span>
          <span className={styles.legendSwatch} style={{ background: "#ff9f1c" }} />
          Rejected — conflict
        </span>
        <span style={{ color: "#7c8792", fontSize: 11 }}>
          Click any bar to explore in the AI Copilot →
        </span>
      </div>

      {rejected.length > 0 && (
        <div className={styles.rejectedList}>
          {rejected.map((m) => (
            <div
              key={m.mission_id}
              className={styles.rejectedItem}
              onClick={() => onSelectMission(selectedMission?.mission_id === m.mission_id ? null : m)}
              style={{ cursor: "pointer" }}
            >
              ⚠ {m.mission_id} rejected
              {m.rejection?.reason ? ` — ${m.rejection.reason}` : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
