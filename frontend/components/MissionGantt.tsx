"use client";

import { useMemo, useEffect, useState } from "react";
import styles from "./MissionGantt.module.css";
import { Mission } from "../data/mockMissions";
import { fetchSchedule } from "../lib/api";

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
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    fetchSchedule()
      .then(setMissions)
      .catch((err) => console.error("Failed to load schedule:", err));
  }, []);

  // Live sweep line — updates every 30s, no need for per-second precision
  useEffect(() => {
  setNow(Date.now()); // set once on mount, client-side only — avoids SSR/client time mismatch
  const id = setInterval(() => setNow(Date.now()), 30000);
  return () => clearInterval(id);
  }, []);

  // Always show a full 24h window, anchored to the start of the day of the
  // earliest mission (or today, if nothing's loaded yet) — per team request,
  // rather than a horizon that shrinks to fit whatever data happens to exist.
  const horizonStart = useMemo(() => {
    const timed = missions.filter((m) => m.visibility_start);
    const anchor = timed.length
      ? Math.min(...timed.map((m) => new Date(m.visibility_start).getTime()))
      : Date.now();
    const d = new Date(anchor);
    d.setMinutes(0, 0, 0);
    d.setHours(0);
    return d.getTime();
  }, [missions]);

  const horizonEnd = horizonStart + 24 * 60 * 60 * 1000;
  const totalMinutes = 24 * 60;

  const stations = useMemo(
    () => Array.from(new Set(missions.filter((m) => m.visibility_start).map((m) => m.station))),
    [missions]
  );

  const ticks = useMemo(() => {
    const out: { label: string; pct: number }[] = [];
    for (let t = 0; t <= totalMinutes; t += 60) {
      const date = new Date(horizonStart + t * 60000);
      out.push({
        label: formatTime(date.getTime()),
        pct: (t / totalMinutes) * 100,
      });
    }
    return out;
  }, [horizonStart]);

  const rejected = missions.filter((m) => m.status === "rejected");

  // Sweep line position — only shown if "now" falls inside the visible horizon
  const sweepPct = now !== null ? ((now - horizonStart) / (horizonEnd - horizonStart)) * 100 : -1;
  const sweepVisible = now !== null && sweepPct >= 0 && sweepPct <= 100;

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.title}>Schedule — 24H Planning Horizon</span>
        <span className={styles.horizon}>
          {new Date(horizonStart).toISOString().slice(0, 10)} · {formatTime(horizonStart)} – {formatTime(horizonEnd)} (+24h)
        </span>
      </div>

      <div className={styles.scrollArea} style={{ position: "relative" }}>
        {sweepVisible && (
          <div className={styles.sweepLine} style={{ left: `${sweepPct}%` }}>
            <div className={styles.sweepDot} />
          </div>
        )}

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
                  const rawStartPct =
                    (toMinutes(m.visibility_start, horizonStart) / totalMinutes) * 100;
                  const widthPct = Math.max((m.duration_minutes / totalMinutes) * 100, 6);
                  const startPct = Math.min(Math.max(rawStartPct, 0), 100 - widthPct);
                  const isSelected = selectedMission?.mission_id === m.mission_id;
                  return (
                    <div
                      key={m.mission_id}
                      className={`${styles.block} ${
                        m.status === "rejected" ? styles.rejected : styles.scheduled
                      } ${isSelected ? styles.selected : ""}`}
                      style={{ left: `${startPct}%`, width: `${widthPct}%` }}
                      onClick={() =>
                        onSelectMission(selectedMission?.mission_id === m.mission_id ? null : m)
                      }
                      title={`${m.mission_id} — ${m.status}`}
                    >
                      <span className={styles.satelliteGlyph}>🛰</span>
                      {m.mission_id}
                    </div>
                  );
                })}
            </div>
          </div>
        ))}
      </div>

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
              onClick={() =>
                onSelectMission(selectedMission?.mission_id === m.mission_id ? null : m)
              }
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