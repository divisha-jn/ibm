"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

// Simple shared-password gate — no backend, no real security.
// Good enough for a hackathon demo to keep casual visitors out of the dashboard.
const DEMO_PASSWORD = "missionops2026"; // change this to whatever your team agrees on

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);
  const router = useRouter();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password === DEMO_PASSWORD) {
      sessionStorage.setItem("mission-ops-authed", "true");
      router.push("/dashboard");
    } else {
      setError(true);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0a0d10",
        backgroundImage: "repeating-linear-gradient(0deg, rgba(255,255,255,0.018) 0px, rgba(255,255,255,0.018) 1px, transparent 1px, transparent 40px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "IBM Plex Sans, system-ui, sans-serif",
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          background: "#12161b",
          border: "1px solid #232931",
          borderRadius: 6,
          padding: "40px 36px",
          width: 340,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ marginBottom: 8 }}>
          <div
            style={{
              color: "#e4e7eb",
              fontSize: 18,
              letterSpacing: "0.04em",
              fontWeight: 600,
            }}
          >
            🛰 MISSION OPS COPILOT
          </div>
          <div style={{ color: "#7c8792", fontSize: 12, marginTop: 4 }}>
            Enter the access code to continue
          </div>
        </div>

        <input
          type="password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            setError(false);
          }}
          placeholder="Access code"
          autoFocus
          style={{
            background: "#0a0d10",
            border: `1px solid ${error ? "#da1e28" : "#232931"}`,
            borderRadius: 4,
            padding: "10px 12px",
            color: "#e4e7eb",
            fontFamily: "IBM Plex Mono, monospace",
            fontSize: 14,
            outline: "none",
          }}
        />

        {error && (
          <div style={{ color: "#da1e28", fontSize: 12, fontFamily: "IBM Plex Mono, monospace" }}>
            Incorrect code — try again.
          </div>
        )}

        <button
          type="submit"
          style={{
            background: "#0f62fe",
            color: "white",
            border: "none",
            borderRadius: 4,
            padding: "10px 0",
            fontFamily: "IBM Plex Sans, system-ui, sans-serif",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            marginTop: 4,
          }}
        >
          Enter
        </button>
      </form>
    </main>
  );
}