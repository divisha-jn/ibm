# Real Data Handoff — Person 1

## Sample real output
`backend/data/generated/visibility_windows.sample.json` — 11 real visibility
windows for ISS (ZARYA) across both ground stations, computed with
Skyfield/SGP4. This is the exact JSON shape every visibility window has.

To generate a fresh one yourself (needs internet):
\`\`\`bash
python -c "
from backend.data.passes import generate_all_visibility_windows, save_visibility_windows
windows = generate_all_visibility_windows(horizon_hours=48)
path = save_visibility_windows(windows)
print(f'Saved {len(windows)} windows to {path}')
"
\`\`\`

## generate_all_visibility_windows(horizon_hours=48, force_refresh_celestrak=False)
Fetches satellites from CelesTrak, loads ground stations, computes every
visibility window for every satellite/station pair over the given horizon.
Returns a list of VisibilityWindow objects (call `.to_dict()` for plain JSON).

## save_visibility_windows(windows, filename="visibility_windows.json")
Saves the list to `backend/data/generated/`. Returns the file path.

## JSON shape
- `satellite` — satellite name from CelesTrak
- `station` — matches a station id in data/ground_stations.json
- `visibility_start` / `visibility_end` — ISO 8601 UTC, ends in Z
- `max_elevation_deg` — peak elevation reached during the pass
- `duration_seconds` — how long the pass lasts

## Notes for Person 2
No mission id/priority/duration is attached yet — that merge still needs to
be agreed on together.

## Notes for Person 4
Don't call generate_all_visibility_windows() on every API request — it hits
CelesTrak over the network. Cache the result instead.
