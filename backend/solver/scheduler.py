import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from ortools.sat.python import cp_model  #cp_model gives us access to CP-SAT scheduler

ROOT = Path(__file__).resolve().parents[2]

WINDOWS_PATH = (
    ROOT / "backend/tests/fixtures/visibility_windows_p2_test.json"
)

REQUESTS_PATH = (
    ROOT / "backend/tests/fixtures/mission_requests_p2_test.json"
)

OUTPUT_PATH = (
    ROOT / "backend/data/generated/schedule_result.json"
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)

def parse_iso(timestamp):
    return datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    )


def to_seconds(timestamp, horizon_start):
    current_time = parse_iso(timestamp)

    return int(
        (current_time - horizon_start).total_seconds()
    )    

def from_seconds(seconds, horizon_start):
    timestamp = horizon_start + timedelta(seconds=seconds)

    return (
        timestamp
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    ) # converts answer back to ISO format for output

def solve_schedule(
    visibility_data,
    mission_data,
    *,
    required_request_ids=None,
    required_window_by_request=None,
    deterministic=False,
):

    required_request_ids = set(required_request_ids or ())
    required_window_by_request = dict(required_window_by_request or {})

    horizon_start = parse_iso(
        visibility_data["planning_horizon"]["start"]
    )

    windows = visibility_data["visibility_windows"]
    requests = mission_data["requests"]

    if required_request_ids or required_window_by_request:
        request_ids = [request["request_id"] for request in requests]
        duplicate_request_ids = {
            request_id
            for request_id in request_ids
            if request_ids.count(request_id) > 1
        }
        if duplicate_request_ids:
            raise ValueError(
                "Constrained scheduling requires unique request IDs; duplicates: "
                f"{sorted(duplicate_request_ids)}"
            )

        request_lookup = {
            request["request_id"]: request
            for request in requests
        }
        unknown_required_requests = (
            required_request_ids | set(required_window_by_request)
        ) - set(request_lookup)
        if unknown_required_requests:
            raise ValueError(
                "Required request IDs do not exist: "
                f"{sorted(unknown_required_requests)}"
            )

        windows_by_id = defaultdict(list)
        for window in windows:
            windows_by_id[window["window_id"]].append(window)

        unique_windows = []
        for window_id, matching_windows in windows_by_id.items():
            first_window = matching_windows[0]
            if any(window != first_window for window in matching_windows[1:]):
                raise ValueError(
                    f"Required scheduling input has conflicting window ID {window_id!r}."
                )
            unique_windows.append(first_window)
        windows = unique_windows

        for request_id, window_id in required_window_by_request.items():
            matching_windows = windows_by_id.get(window_id, [])
            if not matching_windows:
                raise ValueError(
                    f"Required window {window_id!r} does not exist for {request_id!r}."
                )
            request = request_lookup[request_id]
            window = matching_windows[0]
            if window["satellite_id"] != request["satellite_id"]:
                raise ValueError(
                    f"Required window {window_id!r} belongs to satellite "
                    f"{window['satellite_id']!r}, not request {request_id!r}."
                )
            if window["station_id"] not in set(request["eligible_station_ids"]):
                raise ValueError(
                    f"Required window {window_id!r} uses ineligible station "
                    f"{window['station_id']!r} for request {request_id!r}."
                )

            window_duration = int(
                (parse_iso(window["los"]) - parse_iso(window["aos"])).total_seconds()
            )
            required_duration = int(request["required_contact_seconds"])
            if window_duration < required_duration:
                raise ValueError(
                    f"Required window {window_id!r} is too short for request "
                    f"{request_id!r}: {window_duration}s < {required_duration}s."
                )

    model = cp_model.CpModel() # creates a new optimization problem

    windows_by_satellite = defaultdict(list)

    for window in windows:
        satellite_id = window["satellite_id"]

        windows_by_satellite[satellite_id].append(window) # to make matching a mission request to its satellite's possible passes much easier

    candidates = {} # will store all the possible scheduling choices

    request_candidate_vars = defaultdict(list) # enforce that one mission req cannot accidentally be scheduled many times
    station_intervals = defaultdict(list) # group contacts by ground station so no overlapping contacts at same time


    for request in requests:

        request_id = request["request_id"]
        satellite_id = request["satellite_id"]
        duration = int(request["required_contact_seconds"])

        eligible_stations = set(
            request["eligible_station_ids"]
        )

        satellite_windows = windows_by_satellite.get(
            satellite_id,
            []
        )

        for window in satellite_windows:

            station_id = window["station_id"]

            if station_id not in eligible_stations:
                continue # checks if VW is at GS this mission is allowed to use

            aos = to_seconds(
                window["aos"],
                horizon_start
            )

            los = to_seconds(
                window["los"],
                horizon_start
            )

            latest_start = los - duration

            if latest_start < aos:
                continue # required contact duration must fit in VW


            window_id = window["window_id"]

            presence = model.new_bool_var( 
                f"present_{request_id}_{window_id}"
            ) # presence can only be 0 or 1 


            start = model.new_int_var(
                aos,
                latest_start,
                f"start_{request_id}_{window_id}"
            )

            end = model.new_int_var(
                aos + duration,
                los,
                f"end_{request_id}_{window_id}"
            ) # OR-Tools gets to choose a start time within valid range 


            interval = model.new_optional_interval_var(
                start,
                duration,
                end,
                presence,
                f"interval_{request_id}_{window_id}"
            ) # scheduling interval 


            candidates[(request_id, window_id)] = {
                "request": request,
                "window": window,
                "presence": presence,
                "start": start,
                "end": end,
                "interval": interval
            }

            request_candidate_vars[request_id].append(
                presence
            )

            station_intervals[station_id].append(
                interval
            )

    for request in requests:

        request_id = request["request_id"]

        candidate_vars = request_candidate_vars.get(
            request_id,
            []
        )

        if candidate_vars:
            model.add(
                sum(candidate_vars) <= 1
            ) # each mission request can only be scheduled once 

    for request_id in sorted(
        required_request_ids | set(required_window_by_request)
    ):
        candidate_vars = request_candidate_vars.get(request_id, [])
        if not candidate_vars:
            raise ValueError(
                f"Required request {request_id!r} has no feasible candidate windows."
            )
        model.add(sum(candidate_vars) == 1)

    for request_id, window_id in required_window_by_request.items():
        candidate = candidates.get((request_id, window_id))
        if candidate is None:
            raise ValueError(
                f"Required window {window_id!r} is not a feasible candidate for "
                f"request {request_id!r}."
            )
        model.add(candidate["presence"] == 1)


    for station_id, intervals in station_intervals.items():

        if len(intervals) > 1:
            model.add_no_overlap(intervals) # tells OR-Tools that contacts assigned to same station resource cannot overlap, rn 1 station = 1 antenna/resource, later can group by antenna_id if model as multiple antennas per station


    objective_terms = []

    for candidate in candidates.values():

        priority = int(
            candidate["request"]["priority"]
        )

        objective_terms.append(
            priority * candidate["presence"]
        )

    model.maximize(
        sum(objective_terms)
    ) # maximize the sum of priorities of scheduled requests 

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    if deterministic:
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0

    status = solver.solve(model)
    status_name = solver.status_name(status)

    scheduled_contacts = []
    scheduled_request_ids = set()

    # Only try to READ solver variable values when a solution exists
    if status in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE
    ):

        for candidate in candidates.values():

            if solver.boolean_value(
                candidate["presence"]
            ):

                request = candidate["request"]
                window = candidate["window"]

                start_seconds = solver.value(
                    candidate["start"]
                )

                end_seconds = solver.value(
                    candidate["end"]
                )

                contact = {
                    "request_id":
                        request["request_id"],

                    "satellite_id":
                        request["satellite_id"],

                    "station_id":
                        window["station_id"],

                    "window_id":
                        window["window_id"],

                    "scheduled_start":
                        from_seconds(
                            start_seconds,
                            horizon_start
                        ),

                    "scheduled_end":
                        from_seconds(
                            end_seconds,
                            horizon_start
                        ),

                    "duration_seconds":
                        request[
                            "required_contact_seconds"
                        ],

                    "priority":
                        request["priority"]
                }

                scheduled_contacts.append(
                    contact
                )

                scheduled_request_ids.add(
                    request["request_id"]
                )

    scheduled_contacts.sort(
        key=lambda contact:
            contact["scheduled_start"]
    )


    # IMPORTANT:
    # This is OUTSIDE the status/candidate processing above.
    #
    # Every request not selected by the solver is unscheduled,
    # including requests that had ZERO valid candidates.

    unscheduled_requests = []

    for request in requests:

        if (
            request["request_id"]
            not in scheduled_request_ids
        ):

            unscheduled_requests.append({
                "request_id":
                    request["request_id"],

                "satellite_id":
                    request["satellite_id"],

                "priority":
                    request["priority"]
            })


    result = {
        "scenario_id":
            mission_data["scenario_id"],

        "solver": {
            "engine":
                "OR-Tools CP-SAT",

            "status":
                status_name,

            "objective_value": (
                solver.objective_value
                if status in (
                    cp_model.OPTIMAL,
                    cp_model.FEASIBLE
                )
                else None
            )
        },

        "scheduled_contacts":
            scheduled_contacts,

        "unscheduled_requests":
            unscheduled_requests
    }

    return result
    print(
        "Solver status:",
        solver.status_name(status)
    )

    print("\nSCHEDULED CONTACTS")

    scheduled_request_ids = set()

    for candidate in candidates.values():

        if solver.boolean_value(
            candidate["presence"]
        ):

            request = candidate["request"]
            window = candidate["window"]

            scheduled_request_ids.add(
                request["request_id"]
            )

            print(
                request["request_id"],
                "->",
                window["station_id"],
                "| priority:",
                request["priority"]
            )

    print("\nUNSCHEDULED REQUESTS")

    for request in requests:

        if (
            request["request_id"]
            not in scheduled_request_ids
        ):
            print(
                request["request_id"],
                "| priority:",
                request["priority"]
            )



     
def main():

    visibility_data = load_json(WINDOWS_PATH)
    mission_data = load_json(REQUESTS_PATH)

    print("Visibility windows:")
    print(len(visibility_data["visibility_windows"]))

    print("Mission requests:")
    print(len(mission_data["requests"]))

    print("\nRunning scheduler...")

    result = solve_schedule(
        visibility_data,
        mission_data
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
            result,
            file,
            indent=2
        )

    print(
        "\nSolver status:",
        result["solver"]["status"]
    )

    print("\nSCHEDULED CONTACTS")

    for contact in result["scheduled_contacts"]:

        print(
            contact["request_id"],
            "->",
            contact["station_id"],
            "|",
            contact["scheduled_start"],
            "to",
            contact["scheduled_end"],
            "| priority:",
            contact["priority"]
        )

    print("\nUNSCHEDULED REQUESTS")

    for request in result["unscheduled_requests"]:

        print(
            request["request_id"],
            "| priority:",
            request["priority"]
        )

    print(
        "\nSaved schedule to:",
        OUTPUT_PATH
    )


if __name__ == "__main__":
    main()
