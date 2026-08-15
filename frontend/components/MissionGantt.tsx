"use client";

import { useMemo, useState } from "react";
import styles from "./MissionGantt.module.css";
import { mockMissions, PLANNING_HORIZON, Mission } from "../data/mockMissions";

function toMinutes(iso: string, horizonStart: number) {
  return (new Date(iso).getTime() - horizonStart) / 60000;
}

function formatTime(ms: number) {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export default function MissionGantt() {
  const [selected, setSelected] = useState<Mission | null>(null);

  const horizonStart = new Date(PLANNING_HORIZON.start).getTime();
  const horizonEnd = new Date(PLANNING_HORIZON.end).getTime();
  const totalMinutes = (horizonEnd - horizonStart) / 60000;

  const stations = useMemo(
    () => Array.from(new Set(mockMissions.map((m) => m.station))),
    []
  );

  const ticks = useMemo(() => {
    const out: { label: string; pct: number }[] = [];
    for (let t = 0; t <= totalMinutes; t += 30) {
      const date = new Date(horizonStart + t * 60000);
      out.push({
        label: formatTime(date.getTime()),
        pct: (t / totalMinutes) * 100,
      });
    }
    return out;
  }, [totalMinutes, horizonStart]);

  const rejected = mockMissions.filter((m) => m.status === "rejected");

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.title}>Schedule — Planning Horizon</span>
        <span className={styles.horizon}>
          {PLANNING_HORIZON.start.slice(11, 16)}Z – {PLANNING_HORIZON.end.slice(11, 16)}Z
        </span>
      </div>

      <div className={styles.axis}>
        {ticks.map((t) => (
          <span key={t.label} className={styles.axisTick} style={{ left: `${t.pct}%` }}>
            {t.label}
          </span>
        ))}
      </div>

      {stations.map((station) => (
        <div key={station} className={styles.row}>
          <div className={styles.stationLabel}>{station}</div>
          <div className={styles.track}>
            {mockMissions
              .filter((m) => m.station === station)
              .map((m) => {
                const startPct =
                  (toMinutes(m.visibility_start, horizonStart) / totalMinutes) * 100;
                const widthPct = (m.duration_minutes / totalMinutes) * 100;
                return (
                  <div
                    key={m.mission_id}
                    className={`${styles.block} ${
                      m.status === "rejected" ? styles.rejected : styles.scheduled
                    }`}
                    style={{ left: `${startPct}%`, width: `${Math.max(widthPct, 6)}%` }}
                    onClick={() => setSelected(m)}
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
      </div>

      {rejected.length > 0 && (
        <div className={styles.rejectedList}>
          {rejected.map((m) => (
            <div key={m.mission_id} className={styles.rejectedItem}>
              ⚠ {m.mission_id} rejected — conflicts with {m.rejection?.conflicts_with} on{" "}
              {m.station} ({m.rejection?.overlap_minutes}min overlap, priority {m.priority} vs{" "}
              {m.rejection?.conflicting_priority})
              {selected?.mission_id === m.mission_id && (
                <span> — click "Why?" in the AI Copilot panel (coming Day 2) for the explanation</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}