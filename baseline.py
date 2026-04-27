"""
baseline.py — Claude claude-sonnet-4-6 single-call baseline with mock data context.

Injects city-filtered mock data (flights, hotels, activities, restaurants) into the
prompt so the model plans from real inventory — no tools, no state, no ReAct loop.

Usage:
  python3 baseline.py benchmarks/tasks/easy/easy1.json
  python3 baseline.py benchmarks/tasks/easy/
  python3 baseline.py benchmarks/tasks/easy/ benchmarks/tasks/medium/ benchmarks/tasks/hard/
  python3 baseline.py benchmarks/tasks/          # all tiers at once
"""

import json
import os
import sys
import time
from pathlib import Path
from anthropic import Anthropic

OUTPUT_DIR  = Path("baseline_results")
MOCK_DIR    = Path("benchmarks/mock_data")
MODEL       = "claude-sonnet-4-6"
MAX_TOKENS  = 4096

SYSTEM_PROMPT = """\
You are an expert travel planner. You will be given a trip request AND the actual \
inventory of available flights, hotels, activities, and restaurants from our booking \
system. You MUST plan exclusively from this inventory — do not invent options that \
are not listed.

Your itinerary MUST:
- Use real IDs, names, and prices from the provided inventory
- Include outbound and return flights
- Include a hotel for every night
- Include all required activities and restaurants
- Show a day-by-day schedule with no time conflicts
- Show a full budget breakdown that stays within budget_max

Format your response as a Markdown document starting with:
# FINAL ITINERARY

Respect every hard constraint (budget, dates, party size, accessibility).
If dynamic events are described, incorporate replanning directly into the itinerary.
"""


# ── Mock data loading & filtering ─────────────────────────────────────────

def _load_list(filename: str) -> list:
    path = MOCK_DIR / filename
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    # all mock files are {"<key>": [...], "metadata": {...}}
    for k, v in data.items():
        if isinstance(v, list):
            return v
    return []


def _city_set(cities: list[str]) -> set[str]:
    return {c.lower().strip() for c in cities}


def filter_flights(origin: str, destinations: list[str]) -> list:
    all_flights = _load_list("flights.json")
    cities = _city_set([origin] + destinations)
    return [
        f for f in all_flights
        if f.get("from_city", "").lower() in cities
        and f.get("to_city", "").lower() in cities
    ]


def filter_hotels(destinations: list[str]) -> list:
    all_hotels = _load_list("hotels.json")
    cities = _city_set(destinations)
    return [h for h in all_hotels if h.get("city", "").lower() in cities]


def filter_activities(destinations: list[str]) -> list:
    all_acts = _load_list("activities.json")
    cities = _city_set(destinations)
    return [a for a in all_acts if a.get("city", "").lower() in cities]


def filter_restaurants(destinations: list[str]) -> list:
    all_rests = _load_list("restaurants.json")
    cities = _city_set(destinations)
    return [r for r in all_rests if r.get("city", "").lower() in cities]


def build_mock_context(origin: str, destinations: list[str]) -> str:
    flights     = filter_flights(origin, destinations)
    hotels      = filter_hotels(destinations)
    activities  = filter_activities(destinations)
    restaurants = filter_restaurants(destinations)

    sections = []

    if flights:
        sections.append("### Available Flights\n```json\n"
                        + json.dumps(flights, indent=2) + "\n```")
    if hotels:
        sections.append("### Available Hotels\n```json\n"
                        + json.dumps(hotels, indent=2) + "\n```")
    if activities:
        sections.append("### Available Activities\n```json\n"
                        + json.dumps(activities, indent=2) + "\n```")
    if restaurants:
        sections.append("### Available Restaurants\n```json\n"
                        + json.dumps(restaurants, indent=2) + "\n```")

    counts = (f"{len(flights)} flights, {len(hotels)} hotels, "
              f"{len(activities)} activities, {len(restaurants)} restaurants")
    header = f"## Booking Inventory  ({counts})\n"
    return header + "\n\n".join(sections)


# ── Prompt builder ─────────────────────────────────────────────────────────

def build_prompt(task: dict) -> str:
    scenario = task.get("scenario", {})
    profile  = task.get("user_profile", {})
    hard     = task.get("initial_constraints", {}).get("hard", {})
    soft     = task.get("initial_constraints", {}).get("soft", {})
    required = task.get("required_components", [])
    dynamic  = task.get("dynamic_events", [])
    success  = task.get("success_criteria", {})

    origin       = scenario.get("origin_city", "")
    destinations = scenario.get("destination_cities", [])

    lines = [
        f"## Trip Request: {task.get('title', '')}",
        "",
        "### Scenario",
        f"- Origin: {origin}",
        f"- Destinations: {', '.join(destinations)}",
        f"- Duration: {scenario.get('trip_duration_days', '?')} days",
        f"- Description: {scenario.get('description', '')}",
        "",
        "### Traveler Profile",
        f"- Party size: {profile.get('party_size', 1)}",
        f"- Traveler types: {', '.join(profile.get('traveler_types', []))}",
        f"- Special needs: {', '.join(profile.get('special_needs', [])) or 'none'}",
        "",
        "### Hard Constraints (MUST satisfy all)",
    ]
    for k, v in hard.items():
        lines.append(f"- {k}: {v}")

    lines += ["", "### Preferences"]
    for k, v in soft.items():
        lines.append(f"- {k}: {v}")

    if required:
        lines += ["", "### Required Components (all must appear in the itinerary)"]
        for r in required:
            lines.append(f"- {r}")

    if dynamic:
        lines += ["", "### Dynamic Events (must be handled in the itinerary)"]
        for ev in dynamic:
            lines.append(f"- [{ev.get('event_type')}] {ev.get('description', '')}")
            for rr in ev.get("resolution_requirements", []):
                lines.append(f"  · {rr}")

    if success:
        lines += ["", "### Success Criteria"]
        for k, v in success.items():
            lines.append(f"- {k}: {v}")

    # inject filtered mock data
    mock_ctx = build_mock_context(origin, destinations)
    lines += ["", "---", "", mock_ctx, "", "---",
              "Using ONLY the inventory above, produce the complete travel itinerary now."]

    return "\n".join(lines)


# ── Runner ─────────────────────────────────────────────────────────────────

def run_task(client: Anthropic, task_file: Path) -> dict:
    with task_file.open(encoding="utf-8") as f:
        task = json.load(f)

    prompt = build_prompt(task)
    t0 = time.time()

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = round(time.time() - t0, 2)

    return {
        "task_id":    task.get("task_id", task_file.stem),
        "title":      task.get("title", ""),
        "difficulty": task.get("difficulty", ""),
        "itinerary":  response.content[0].text.strip(),
        "tokens_in":  response.usage.input_tokens,
        "tokens_out": response.usage.output_tokens,
        "elapsed":    elapsed,
    }


def collect_task_files(inputs: list[str]) -> list[Path]:
    files = []
    for inp in inputs:
        p = Path(inp)
        if p.is_file() and p.suffix == ".json":
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.json")))
        else:
            print(f"  [warn] skipping: {inp}", file=sys.stderr)
    seen, unique = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def save_result(result: dict, stem: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / f"{stem}.md"
    out.write_text(result["itinerary"], encoding="utf-8")
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    task_files = collect_task_files(sys.argv[1:])
    if not task_files:
        print("No task JSON files found.", file=sys.stderr)
        sys.exit(1)

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    print(f"Baseline ({MODEL}) + mock data context  ·  {len(task_files)} task(s)  →  {OUTPUT_DIR}/")
    print()

    total_tokens, total_time = 0, 0.0
    for i, task_file in enumerate(task_files, 1):
        stem = task_file.stem
        print(f"  [{i}/{len(task_files)}] {stem} ... ", end="", flush=True)
        try:
            result   = run_task(client, task_file)
            out_path = save_result(result, stem)
            tok = result["tokens_in"] + result["tokens_out"]
            total_tokens += tok
            total_time   += result["elapsed"]
            print(f"done  ({result['elapsed']}s  in={result['tokens_in']:,}  out={result['tokens_out']:,})  →  {out_path}")
        except Exception as exc:
            print(f"FAILED: {exc}", file=sys.stderr)

    print()
    print(f"Done.  {total_time:.1f}s  {total_tokens:,} tokens  across {len(task_files)} task(s).")


if __name__ == "__main__":
    main()
