"use client";
import { useState } from "react";
import MissionGantt from "../../components/MissionGantt";
import WhatIfChat from "../../components/WhatIfChat";
import RiskPanel from "../../components/RiskPanel";
import { Mission } from "../../data/mockMissions";

export default function DashboardPage() {
  const [selectedMission, setSelectedMission] = useState<Mission | null>(null);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0a0d10",
        padding: "40px 24px",
        fontFamily: "IBM Plex Sans, system-ui, sans-serif",
      }}
    >
      <h1
        style={{
          color: "#e4e7eb",
          fontSize: 20,
          letterSpacing: "0.04em",
          marginBottom: 24,
        }}
      >
        MISSION OPS COPILOT
      </h1>

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