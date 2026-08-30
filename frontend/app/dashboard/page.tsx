"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import MissionGantt from "../../components/MissionGantt";
import WhatIfChat from "../../components/WhatIfChat";
import RiskPanel from "../../components/RiskPanel";
import { Mission } from "../../data/mockMissions";

export default function DashboardPage() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    if (sessionStorage.getItem("mission-ops-authed") !== "true") {
      router.push("/login");
    } else {
      setAuthed(true);
    }
  }, [router]);

  const [selectedMission, setSelectedMission] = useState<Mission | null>(null);

  if (!authed) return null; // brief blank screen while checking, avoids flashing the dashboard

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0a0d10",
        padding: "40px 24px",
        fontFamily: "IBM Plex Sans, system-ui, sans-serif",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
  <h1
    style={{
      color: "#e4e7eb",
      fontSize: 20,
      letterSpacing: "0.04em",
    }}
  >
    MISSION OPS COPILOT
  </h1>
  <button
    onClick={() => {
      sessionStorage.removeItem("mission-ops-authed");
      router.push("/login");
    }}
    style={{
      background: "transparent",
      border: "1px solid #232931",
      color: "#7c8792",
      borderRadius: 4,
      padding: "6px 14px",
      fontFamily: "IBM Plex Mono, monospace",
      fontSize: 12,
      cursor: "pointer",
    }}
  >
    Log out
  </button>
</div>

      <MissionGantt
        selectedMission={selectedMission}
        onSelectMission={setSelectedMission}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 24,
          alignItems: "stretch",
          marginTop: 24,
        }}
      >
        <RiskPanel scenarioId="DEMO_001" selectedMission={selectedMission} />
        <WhatIfChat scenarioId="DEMO_001" selectedMission={selectedMission} />
      </div>
    </main>
  );
}