import { Mission } from "../data/mockMissions";

interface ScheduledContact {
  request_id: string;
  satellite_id: string;
  station_id: string;
  scheduled_start: string;
  scheduled_end: string;
  duration_seconds: number;
  priority: number;
}

interface UnscheduledRequest {
  request_id: string;
  satellite_id: string;
  reason_codes: string[];
}

interface ScheduleResponse {
  scenario_id: string;
  scheduled_contacts: ScheduledContact[];
  unscheduled_requests: UnscheduledRequest[];
}

export function mapScheduleToMissions(data: ScheduleResponse): Mission[] {
  const scheduled: Mission[] = data.scheduled_contacts.map((c) => ({
    mission_id: c.request_id,
    station: c.station_id,
    visibility_start: c.scheduled_start,
    visibility_end: c.scheduled_end,
    duration_minutes: c.duration_seconds / 60,
    priority: c.priority,
    status: "scheduled",
  }));

  const rejected: Mission[] = data.unscheduled_requests.map((u) => ({
    mission_id: u.request_id,
    station: "UNKNOWN", // not provided by /schedule — flag this to P4
    visibility_start: "",
    visibility_end: "",
    duration_minutes: 0,
    priority: 0,
    status: "rejected",
    rejection: {
      reason: u.reason_codes.join(", "),
      conflicts_with: "",
      overlap_minutes: 0,
      conflicting_priority: 0,
    },
  }));

  return [...scheduled, ...rejected];
}