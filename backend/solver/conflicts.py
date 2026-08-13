import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

WINDOWS_PATH = (
    ROOT / "backend/tests/fixtures/visibility_windows_p2_test.json"
)

REQUESTS_PATH = (
    ROOT / "backend/tests/fixtures/mission_requests_p2_test.json"
)

SCHEDULE_PATH = (
    ROOT / "backend/data/generated/schedule_result.json"
)

OUTPUT_PATH = (
    ROOT / "backend/data/generated/conflict_evidence.json"
)

def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file) # same idea as scheduler.py

def parse_iso(timestamp):
    return datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    ) # need to compare times so get actual python datetime 

def overlap_seconds(
    start_a,
    end_a,
    start_b,
    end_b
):
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)

    overlap = (
        earliest_end - latest_start
    ).total_seconds()

    return max(0, int(overlap)) #  tells how much two time intervals overlap 

def calculate_free_segments(
    window_start,
    window_end,
    scheduled_contacts
):
    blocked = []

    for contact in scheduled_contacts:

        contact_start = parse_iso(
            contact["scheduled_start"]
        )

        contact_end = parse_iso(
            contact["scheduled_end"]
        )

        start = max(
            window_start,
            contact_start
        )

        end = min(
            window_end,
            contact_end
        )

        if start < end:
            blocked.append(
                (start, end)
            )

    blocked.sort(
        key=lambda item: item[0]
    )

    merged = []

    for start, end in blocked:

        if (
            not merged
            or start > merged[-1][1]
        ):
            merged.append(
                [start, end]
            )

        else:
            merged[-1][1] = max(
                merged[-1][1],
                end
            )

    free = []

    cursor = window_start

    for start, end in merged:

        if cursor < start:
            free.append(
                (cursor, start)
            )

        cursor = max(
            cursor,
            end
        )

    if cursor < window_end:
        free.append(
            (cursor, window_end)
        )

    return free # helper that finds free time inside a pass for accuracy

def build_conflict_evidence(
    visibility_data,
    mission_data,
    schedule_result
): #main conflict function

    windows = visibility_data[
        "visibility_windows"
    ]

    requests = mission_data[
        "requests"
    ]

    windows_by_satellite = defaultdict(list)

    for window in windows:
        windows_by_satellite[
            window["satellite_id"]
        ].append(window)

    request_lookup = {
        request["request_id"]: request
        for request in requests
    } # lets you quickly ask to give all windows for sat_b/ give all details of req_a


    scheduled_by_station = defaultdict(list)

    for contact in schedule_result[
        "scheduled_contacts"
    ]:

        scheduled_by_station[
            contact["station_id"]
        ].append(contact) # groups currently scheduled contacts by station


    evidence_records = []

    for unscheduled in schedule_result[
        "unscheduled_requests"
    ]:

        request_id = unscheduled[
            "request_id"
        ]

        request = request_lookup[
            request_id
        ] # starts examining each unscheduled request

        required_seconds = int(
            request[
                "required_contact_seconds"
            ]
        )

        eligible_stations = set(
            request[
                "eligible_station_ids"
            ]
        )


        satellite_windows = [
            window
            for window in windows_by_satellite.get(
                request["satellite_id"],
                []
            )
            if window["station_id"]
            in eligible_stations
        ]


        reason_codes = []
        conflicts = []
        alternative_window_ids = []

        if not satellite_windows:

            reason_codes.append(
                "NO_ELIGIBLE_VISIBILITY_WINDOW"
            ) # handle simplest failure first

        else:

            has_duration_feasible_window = False
            has_free_window = False

            for window in satellite_windows:
                window_start = parse_iso(
                    window["aos"]
                )

                window_end = parse_iso(
                    window["los"]
                )

                window_duration = int(
                    (
                        window_end
                        - window_start
                    ).total_seconds()
                )

                if (
                    window_duration
                    < required_seconds
                ):
                    continue

                has_duration_feasible_window = True

                station_id = window[
                    "station_id"
                ]

                station_contacts = (
                    scheduled_by_station.get(
                        station_id,
                        []
                    )
                )

                free_segments = (
                    calculate_free_segments(
                        window_start,
                        window_end,
                        station_contacts
                    )
                )

                max_free_seconds = max(
                    [
                        int(
                            (end - start)
                            .total_seconds()
                        )
                        for start, end
                        in free_segments
                    ],
                    default=0
                )

                if (
                    max_free_seconds
                    >= required_seconds
                ):

                    has_free_window = True

                    alternative_window_ids.append(
                        window["window_id"]
                    )

                for contact in station_contacts:

                    contact_start = parse_iso(
                            contact[
                                "scheduled_start"
                        ]
                    )

                    contact_end = parse_iso(
                            contact[
                                "scheduled_end"
                        ]
                    )

                    overlap = overlap_seconds(
                            window_start,
                            window_end,
                            contact_start,
                            contact_end
                    )

                    if overlap <= 0:
                            continue

                    conflicting_request = (
                        request_lookup.get(
                            contact["request_id"]
                        )
                    )

                    conflicts.append({
                            "conflicting_request_id":
                                contact["request_id"],

                            "station_id":
                                station_id,

                            "overlap_start":
                                max(
                                    window_start,
                                    contact_start
                                )
                                .isoformat()
                                .replace(
                                    "+00:00",
                                    "Z"
                            ),  

                            "overlap_end":
                                min(
                                    window_end,
                                    contact_end
                            )
                                .isoformat()
                                .replace(
                                    "+00:00",
                                    "Z"
                            ),

                            "overlap_seconds":
                                overlap,

                            "request_priority":
                                request["priority"],

                            "conflicting_request_priority":
                                (
                                    conflicting_request[
                                        "priority"
                                    ]
                                    if conflicting_request
                                    else None
                            )
                    })


            if not has_duration_feasible_window:

                reason_codes.append(
                    "INSUFFICIENT_WINDOW_DURATION"
                )

            elif not has_free_window:

                reason_codes.append(
                    "ANTENNA_RESOURCE_CONFLICT"
                )

            else:

                reason_codes.append(
                    "OPTIMIZATION_TRADEOFF"
                )


        evidence_records.append({
            "request_id":
                request_id,

            "status":
                "UNSCHEDULED",

            "reason_codes":
                reason_codes,

            "conflicts":
                conflicts,

            "feasibility": {
                "requested_contact_seconds":
                    required_seconds
            },

            "alternative_window_ids":
                sorted(
                    set(
                        alternative_window_ids
                    )
                )
        })

    return {
        "scenario_id":
            mission_data["scenario_id"],

        "evidence":
            evidence_records
    }


def main():

    visibility_data = load_json(
        WINDOWS_PATH
    )

    mission_data = load_json(
        REQUESTS_PATH
    )

    schedule_result = load_json(
        SCHEDULE_PATH
    )

    evidence = build_conflict_evidence(
        visibility_data,
        mission_data,
        schedule_result
    )

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            evidence,
            file,
            indent=2
        )

    print(
        "Saved:",
        OUTPUT_PATH
    )

    for record in evidence[
        "evidence"
    ]:

        print(
            record["request_id"],
            "->",
            record["reason_codes"]
        )


if __name__ == "__main__":
    main()
