# Travel Agent

An LLM-powered travel planning agent built with Claude and LangChain. The agent handles end-to-end trip planning — flights, hotels, restaurants, and activities — while gracefully managing dynamic disruptions like cancellations, budget changes, and weather events through real-time replanning.

---

## Overview

Travel planning is a complex, multi-constraint problem that requires reasoning over preferences, budgets, schedules, and logistics — and adapting when things go wrong mid-trip. This project builds and benchmarks an AI agent capable of:

- Planning complete itineraries across one or multiple cities
- Satisfying hard constraints (budget, dates, accessibility) and soft preferences (interests, cuisine)
- Replanning when dynamic events occur mid-conversation (e.g., hotel cancellation, flight delay, budget reduction)
- Handling specialized requirements: family travel, accessibility needs, group trips, international itineraries

---

## Architecture

```
User Request
     │
     ▼
  Agent (Claude + LangChain)
     │
     ├── FlightsTool     →  Search & book flights
     ├── HotelsTool      →  Search & book hotels
     ├── RestaurantsTool →  Search & reserve restaurants
     └── ActivitiesTool  →  Search & book activities
                               │
                               ▼
                         Mock Data Layer
                    (flights / hotels / restaurants / activities)
```

The agent uses **tool calling** to query a structured mock database. When a dynamic event is injected mid-conversation, the agent must identify affected components and replan accordingly.

---

## Tech Stack

| Component | Library |
|-----------|---------|
| LLM | [Anthropic Claude](https://www.anthropic.com) (`anthropic`) |
| Agent Framework | [LangChain](https://www.langchain.com) |
| Data Validation | [Pydantic](https://docs.pydantic.dev) |
| UI (optional) | [Streamlit](https://streamlit.io) |
| Testing | [pytest](https://pytest.org) |
| Config | python-dotenv |

---

## Project Structure

```
travel-agent/
├── src/
│   ├── agent.py              # Main agent implementation
│   ├── tools/
│   │   ├── flights.py        # Flight search & booking tool
│   │   ├── hotels.py         # Hotel search & booking tool
│   │   └── restaurants.py    # Restaurant search & reservation tool
│   ├── core/                 # Core utilities and shared logic
│   └── utils/                # Helper functions
│
├── benchmarks/
│   ├── tasks/
│   │   ├── easy/             # 5 tasks (task_001–005): single city, no disruptions
│   │   ├── medium/           # 10 tasks (task_006–015): single city + 1 dynamic event
│   │   └── hard/             # 6 tasks (task_016–021): multi-city + complex events
│   └── mock_data/
│       ├── hotels.json        # 75 hotels across 24 cities
│       ├── restaurants.json   # ~160 restaurants
│       ├── activities.json    # 98 activities
│       └── flights.json       # Flight data
│
├── evaluations/              # Evaluation framework & scoring
├── tests/                    # Unit and integration tests
├── scripts/
│   └── generate_mock_data.py # Mock data generation script
├── requirements.txt
└── .env                      # API keys (not committed)
```

---

## Benchmark Suite

The benchmark consists of **21 tasks** across three difficulty tiers, designed to test both planning quality and replanning ability under disruption.

### Easy (5 tasks) — `task_001` to `task_005`

Single destination, no dynamic events. Tests core planning capability.

| Task | Scenario | Key Constraints |
|------|----------|-----------------|
| task_001 | Weekend trip: Detroit → Chicago | $300 budget, student traveler |
| task_002 | Long weekend: Boston → Miami | Beach focus, couple |
| task_003 | 4-day trip: Houston → Austin | Live music, local food |
| task_004 | 5-day trip: LA → New York | Art & culture, moderate budget |
| task_005 | 4-day trip: Denver → San Diego | Family of 4, beach + zoo |

### Medium (10 tasks) — `task_006` to `task_015`

Single destination with **one dynamic event** injected mid-planning, requiring partial or full replanning.

| Task | Scenario | Dynamic Event |
|------|----------|---------------|
| task_006 | San Diego family trip (wheelchair accessible) | Hotel becomes unavailable |
| task_007 | New Orleans jazz weekend | Luxury hotel → budget forced downgrade |
| task_008 | Portland accessible wedding venue | Preferred venue closes |
| task_009 | Napa Valley bachelor party | Restaurant cancellation |
| task_010 | Seattle arts trip | Flight delayed, loses a day |
| task_011 | DC monuments & museums | Outdoor tour rained out |
| task_012 | Las Vegas tech conference | Emergency early return (trip shortened) |
| task_013 | Austin music & food tour | Concert cancelled mid-trip |
| task_014 | Orlando family theme parks | Budget increase, can add activities |
| task_015 | New York art museums | Preferred museum closes, find alternative |

### Hard (6 tasks) — `task_016` to `task_021`

Multi-city itineraries with **one or two complex dynamic events**, often with cascading effects.

| Task | Scenario | Cities | Challenge |
|------|----------|--------|-----------|
| task_016 | Alaska wilderness adventure | Anchorage + Fairbanks | Glacier tour weather-cancelled; 3 imperfect alternatives |
| task_017 | European honeymoon | Paris → Venice → Barcelona | Mid-trip flight cancellation cascades to hotels & next leg |
| task_018 | National parks road trip | Zion + Bryce Canyon + Moab | Arches permit unavailable; group injury limits activities |
| task_019 | Japan cultural immersion | Tokyo + Kyoto | Business hotel fully booked; ryokan traditional vs modern preference conflict |
| task_020 | California wine & nature | Napa + Lake Tahoe | Wine tour cancelled + group size changes |
| task_021 | Southeast US food & music | New Orleans + Austin | Flight missed; must resequence cities |

### Task Schema

Each benchmark task is a structured JSON file:

```json
{
  "task_id": "task_006",
  "difficulty": "medium",
  "title": "San Diego Family Beach Trip",
  "scenario": {
    "description": "...",
    "origin_city": "Phoenix",
    "destination_cities": ["San Diego"],
    "trip_duration_days": 5
  },
  "user_profile": {
    "party_size": 4,
    "traveler_types": ["family", "kids"],
    "special_needs": ["wheelchair_accessible"]
  },
  "initial_constraints": {
    "hard": { "budget_max": 3500, "departure_date": "...", "return_date": "..." },
    "soft": { "interests": ["beach", "zoo", "aquarium"] }
  },
  "dynamic_events": [{
    "event_id": "event_001",
    "trigger_turn": 5,
    "event_type": "hotel_unavailable",
    "description": "Booked hotel reports a double booking and cancels the reservation.",
    "affected_components": ["hotel"],
    "resolution_requirements": { "must_remain_wheelchair_accessible": true }
  }],
  "success_criteria": { ... }
}
```

---

## Mock Data

All agent tools query a local mock database covering **24 destinations**.

**US Domestic:** Chicago, Miami, Austin, New York, San Francisco, San Diego, Seattle, Washington D.C., Orlando, New Orleans, Las Vegas, Portland, Anchorage, Fairbanks, Napa Valley, Lake Tahoe, Zion NP, Bryce Canyon NP, Moab

**International:** Paris, Venice, Barcelona, Tokyo, Kyoto

| Dataset | Records | Notes |
|---------|---------|-------|
| Hotels | 75 | Stars 2–5, $79–$1200+/night, tagged by type |
| Restaurants | ~160 | Price levels $–$$$$, dietary options, opening hours |
| Activities | 98 | Duration, price, accessibility, booking requirements |
| Flights | — | In progress |

Hotels and activities are tagged for easy filtering: `wheelchair_accessible`, `family_friendly`, `luxury`, `budget_friendly`, `boutique`, `beachfront`, `near_live_music`, `northern_lights`, `traditional_ryokan`, `wedding_friendly`, and more.

---

## Setup

```bash
# Clone the repo
git clone <repo-url>
cd travel-agent

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

---

## Usage

```bash
# Run the agent (interactive)
python src/agent.py

# Run a specific benchmark task
python src/agent.py --task benchmarks/tasks/easy/easy1.json

# Launch the Streamlit UI
streamlit run src/app.py
```

---

## Evaluation

Benchmark tasks are evaluated against structured success criteria:

- **Constraint satisfaction** — budget, dates, accessibility, party size
- **Component completeness** — all required bookings made (flight, hotel, activities, etc.)
- **Replanning correctness** — dynamic events handled without violating hard constraints
- **Preference alignment** — soft preferences honored where possible

```bash
# Run the full benchmark suite
pytest evaluations/
```

---

## Development Status

| Component | Status |
|-----------|--------|
| Benchmark tasks (21 tasks) | Complete |
| Mock data (hotels, restaurants, activities) | Complete |
| Agent core | In progress |
| Tool implementations | In progress |
| Evaluation framework | Planned |
| Test suite | Planned |

---

## License

MIT
