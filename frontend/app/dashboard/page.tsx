"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import MissionGantt from "../../components/MissionGantt";
import WhatIfChat from "../../components/WhatIfChat";
import RiskPanel from "../../components/RiskPanel";
import { Mission } from "../../data/mockMissions";
import { ChatTurnOut } from "../../lib/api";

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
  const [riskHistory, setRiskHistory] = useState<ChatTurnOut[]>([]);

  // Shared session ID for the current scenario — used by both RiskPanel and WhatIfChat
  const sessionId = `chat_session__DEMO_001__${selectedMission?.mission_id ?? "global"}`;

  const handleRiskSaved = useCallback((turn: ChatTurnOut) => {
    setRiskHistory((h) => [...h, turn]);
  }, []);

  if (!authed) return null; // brief blank screen while checking, avoids flashing the dashboard

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0a0d10",
        borderTop: "3px solid #0f62fe",
        padding: "40px 24px",
        fontFamily: "IBM Plex Sans, system-ui, sans-serif",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24, paddingBottom: 20, borderBottom: "1px solid #2d3540" }}>
  <h1
    style={{
      color: "#e4e7eb",
      fontSize: 16,
      letterSpacing: "0.1em",
      textTransform: "uppercase",
      fontWeight: 600,
    }}
  >
    Mission Ops Copilot
  </h1>
  <button
    onClick={() => {
      sessionStorage.removeItem("mission-ops-authed");
      router.push("/login");
    }}
    onMouseEnter={(e) => { (e.target as HTMLButtonElement).style.borderColor = "#0f62fe"; (e.target as HTMLButtonElement).style.color = "#cfe0ff"; }}
    onMouseLeave={(e) => { (e.target as HTMLButtonElement).style.borderColor = "#232931"; (e.target as HTMLButtonElement).style.color = "#7c8792"; }}
    style={{
      background: "transparent",
      border: "1px solid #232931",
      color: "#7c8792",
      borderRadius: 4,
      padding: "6px 14px",
      fontFamily: "IBM Plex Mono, monospace",
      fontSize: 12,
      cursor: "pointer",
      transition: "border-color 0.15s ease, color 0.15s ease",
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
        <RiskPanel
          scenarioId="DEMO_001"
          selectedMission={selectedMission}
          sessionId={sessionId}
          conversationHistory={riskHistory}
          onRiskSaved={handleRiskSaved}
        />
        <WhatIfChat scenarioId="DEMO_001" selectedMission={selectedMission} />
      </div>
    </main>
  );
}