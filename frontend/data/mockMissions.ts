// mock data for day 1

export type MissionStatus = "scheduled" | "rejected";

export interface Mission {
  mission_id: string;
  station: string;
  visibility_start: string; // ISO timestamp
  visibility_end: string;   // ISO timestamp
  duration_minutes: number;
  priority: number;
  status: MissionStatus;
  // Only present when status === "rejected" — mirrors P2's evidence format
  rejection?: {
    reason: string;
    conflicts_with: string;
    overlap_minutes: number;
    conflicting_priority: number;
  };
}

export const PLANNING_HORIZON = {
  start: "2026-08-20T09:30:00",
  end: "2026-08-20T12:00:00",
};

export const mockMissions: Mission[] = [
  {
    mission_id: "SAT-A",
    station: "GS-SG",
    visibility_start: "2026-08-20T10:00:00",
    visibility_end: "2026-08-20T10:12:00",
    duration_minutes: 12,
    priority: 9,
    status: "scheduled",
  },
  {
    mission_id: "SAT-B",
    station: "GS-SG",
    visibility_start: "2026-08-20T10:05:00",
    visibility_end: "2026-08-20T10:14:00",
    duration_minutes: 7,
    priority: 5,
    status: "rejected",
    rejection: {
      reason: "antenna_conflict",
      conflicts_with: "SAT-A",
      overlap_minutes: 7,
      conflicting_priority: 9,
    },
  },
  {
    mission_id: "SAT-C",
    station: "GS-SG",
    visibility_start: "2026-08-20T10:30:00",
    visibility_end: "2026-08-20T10:40:00",
    duration_minutes: 10,
    priority: 6,
    status: "scheduled",
  },
  {
    mission_id: "SAT-D",
    station: "GS-AU",
    visibility_start: "2026-08-20T10:20:00",
    visibility_end: "2026-08-20T10:35:00",
    duration_minutes: 15,
    priority: 8,
    status: "scheduled",
  },
  {
    mission_id: "SAT-E",
    station: "GS-AU",
    visibility_start: "2026-08-20T11:00:00",
    visibility_end: "2026-08-20T11:09:00",
    duration_minutes: 9,
    priority: 4,
    status: "scheduled",
  },
];