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

function dayKey(iso: string) {
  return new Date(iso).toISOString().slice(0, 10); // YYYY-MM-DD
}

interface Props {
  selectedMission: Mission | null;
  onSelectMission: (m: Mission | null) => void;
}

export default function MissionGantt({ selectedMission, onSelectMission }: Props) {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [now, setNow] = useState<number | null>(null);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  useEffect(() => {
    fetchSchedule()
      .then(setMissions)
      .catch((err) => console.error("Failed to load schedule:", err));
  }, []);

  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);

  // Distinct calendar days present in the scheduled data, sorted chronologically.
  const availableDays = useMemo(() => {
    const days = new Set(
      missions.filter((m) => m.visibility_start).map((m) => dayKey(m.visibility_start))
    );
    return Array.from(days).sort();
  }, [missions]);

  // Default to the first available day once data loads, or today if none.
  useEffect(() => {
    if (!selectedDay && availableDays.length > 0) {
      setSelectedDay(availableDays[0]);
    }
  }, [availableDays, selectedDay]);

  const activeDay = selectedDay ?? new Date().toISOString().slice(0, 10);

  const horizonStart = useMemo(() => {
    const d = new Date(`${activeDay}T00:00:00Z`);
    return d.getTime();
  }, [activeDay]);

  const horizonEnd = horizonStart + 24 * 60 * 60 * 1000;
  const totalMinutes = 24 * 60;

  // Only missions scheduled on the currently selected day appear on the chart.
  const dayMissions = useMemo(
    () => missions.filter((m) => m.visibility_start && dayKey(m.visibility_start) === activeDay),
    [missions, activeDay]
  );

  const stations = useMemo(
    () => Array.from(new Set(dayMissions.map((m) => m.station))),
    [dayMissions]
  );

  const ticks = useMemo(() => {
    const out: { label: string; pct: number }[] = [];
    for (let t = 0; t <= totalMinutes; t += 60) {
      const date = new Date(horizonStart + t * 60000);
      out.push({ label: formatTime(date.getTime()), pct: (t / totalMinutes) * 100 });
    }
    return out;
  }, [horizonStart]);

  // Rejected missions have no timing data at all, so they're independent of
  // which day is selected — always show the full list.
  const rejected = missions.filter((m) => m.status === "rejected");

  const sweepPct = now !== null ? ((now - horizonStart) / (horizonEnd - horizonStart)) * 100 : -1;
  const sweepVisible = now !== null && sweepPct >= 0 && sweepPct <= 100;

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.title}>Schedule — 24H Planning Horizon</span>
        <span className={styles.horizon}>
          {activeDay} · 00:00 – 00:00 (+24h)
        </span>
      </div>

      {availableDays.length > 1 && (
        <div className={styles.dayNav}>
          <button
            className={styles.dayNavArrow}
            onClick={() => {
              const idx = availableDays.indexOf(activeDay);
              if (idx > 0) setSelectedDay(availableDays[idx - 1]);
            }}
            disabled={availableDays.indexOf(activeDay) <= 0}
            aria-label="Previous day"
          >
            ‹
          </button>
          <span className={styles.dayNavLabel}>
            {activeDay} <span className={styles.dayNavCount}>
              ({availableDays.indexOf(activeDay) + 1} of {availableDays.length})
            </span>
          </span>
          <button
            className={styles.dayNavArrow}
            onClick={() => {
              const idx = availableDays.indexOf(activeDay);
              if (idx < availableDays.length - 1) setSelectedDay(availableDays[idx + 1]);
            }}
            disabled={availableDays.indexOf(activeDay) >= availableDays.length - 1}
            aria-label="Next day"
          >
            ›
          </button>
        </div>
      )}

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

        {stations.length === 0 && (
          <div className={styles.emptyDay}>No scheduled contacts on this day.</div>
        )}

        {stations.map((station) => (
          <div key={station} className={styles.row}>
            <div className={styles.stationLabel}>{station}</div>
            <div className={styles.track}>
              {dayMissions
                .filter((m) => m.station === station)
                .map((m) => {
                  const rawStartPct = (toMinutes(m.visibility_start, horizonStart) / totalMinutes) * 100;
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