import MissionGantt from "../../components/MissionGantt";
import WhatIfChat from "../../components/WhatIfChat";

export default function DashboardPage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0b0e11",
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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 24,
          alignItems: "start",
        }}
      >
        <MissionGantt />
        <WhatIfChat scenarioId="DEMO_001" />
      </div>
    </main>
  );
}