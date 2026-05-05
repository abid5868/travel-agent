# TravelBench

A multi-difficulty benchmark and ReAct agent for evaluating LLM travel planning under dynamic replanning scenarios.

---

## Table of Contents

1. [Overview](#overview)
2. [Project Structure](#project-structure)
3. [Setup](#setup)
4. [Running the Agent](#running-the-agent)
5. [Reproducing Experiments](#reproducing-experiments)
6. [Baseline](#baseline)
7. [Evaluation](#evaluation)
8. [Benchmark Design](#benchmark-design)
9. [Mock Data](#mock-data)

---

## Overview

Travel planning requires coordinating flights, hotels, activities, and restaurants under hard budget and date constraints — and adapting when things go wrong mid-trip. TravelBench tests AI agents on:

- End-to-end itinerary planning (single and multi-city)
- Hard constraint satisfaction (budget, dates, accessibility, party size)
- Dynamic replanning when disruptions occur (hotel cancellations, weather, budget cuts)

The benchmark contains **21 structured tasks** across three difficulty tiers. A custom **LLM-as-a-judge** evaluator scores each itinerary across 5 dimensions. A zero-shot **baseline** (same model, single call, real mock data injected as context) is provided for comparison.

---

## Project Structure

```
travel-agent/
├── src/
│   ├── agent.py              # ReAct agent (main implementation)
│   ├── main.py               # CLI runner for a single task
│   ├── tools/
│   │   ├── flights.py        # search_flights / book_flight / cancel_flight
│   │   ├── hotels.py         # search_hotels / book_hotel / cancel_hotel
│   │   ├── restaurants.py    # search_restaurants / book_restaurant
│   │   └── activities.py     # search_activities / book_activity
│   ├── core/
│   │   └── constraints.py    # ConstraintTracker (budget, bookings, hard constraints)
│   └── utils/
│       ├── prompts.py        # System prompt, planning/replanning/final templates
│       └── types.py          # Booking dataclass and shared types
│
├── benchmarks/
│   ├── tasks/
│   │   ├── easy/             # easy1–5.json   (task_001–005)
│   │   ├── medium/           # medium1–10.json (task_006–015)
│   │   └── hard/             # hard1–6.json   (task_016–021)
│   └── mock_data/
│       ├── flights.json      # Flight routes between all city pairs
│       ├── hotels.json       # 75 hotels across 24 cities
│       ├── activities.json   # 98 activities across 24 cities
│       └── restaurants.json  # ~175 restaurants across 24 cities
│
├── evaluations/
│   └── llm_judge.py          # LLM-as-a-judge: single task or batch folder mode
│
├── tests/
│   ├── test_agent_class.py   # Integration runner (edit TASKS list to choose tasks)
│   ├── test_llm_judge.py     # Unit tests for judge helper functions
│   ├── test_constraints.py   # Unit tests for ConstraintTracker
│   └── test_tools.py         # Unit tests for tool implementations
│
├── agent_planning_results/   # Agent outputs: <taskname>.md + <taskname>.json
├── baseline_results/         # Baseline outputs: <taskname>.md
│
├── baseline.py               # Zero-shot single-call baseline with mock data context
```

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd travel-agent
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install anthropic pytest
```

### 3. Set your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Running the Agent

### Single task via CLI

```bash
python3 src/main.py --task benchmarks/tasks/easy/easy1.json
```

Prints the itinerary to stdout. No files written.

### Run tasks and save results

Edit the `TASKS` list in `tests/test_agent_class.py` to select which tasks to run:

```python
TASKS = [
    "benchmarks/tasks/easy/easy1.json",
    "benchmarks/tasks/medium/medium1.json",
    "benchmarks/tasks/hard/hard1.json",
]
```

Then run:

```bash
python3 tests/test_agent_class.py
```

Results are saved to `agent_planning_results/`:
- `<taskname>.md` — full itinerary in Markdown
- `<taskname>.json` — metadata (success, tokens, time, API call count)

---

## Reproducing Experiments

### Step 1 — Run the ReAct agent on all 21 tasks

Set `TASKS` in `tests/test_agent_class.py` to all 21 tasks:

```python
TASKS = [
    "benchmarks/tasks/easy/easy1.json",
    "benchmarks/tasks/easy/easy2.json",
    "benchmarks/tasks/easy/easy3.json",
    "benchmarks/tasks/easy/easy4.json",
    "benchmarks/tasks/easy/easy5.json",
    "benchmarks/tasks/medium/medium1.json",
    "benchmarks/tasks/medium/medium2.json",
    "benchmarks/tasks/medium/medium3.json",
    "benchmarks/tasks/medium/medium4.json",
    "benchmarks/tasks/medium/medium5.json",
    "benchmarks/tasks/medium/medium6.json",
    "benchmarks/tasks/medium/medium7.json",
    "benchmarks/tasks/medium/medium8.json",
    "benchmarks/tasks/medium/medium9.json",
    "benchmarks/tasks/medium/medium10.json",
    "benchmarks/tasks/hard/hard1.json",
    "benchmarks/tasks/hard/hard2.json",
    "benchmarks/tasks/hard/hard3.json",
    "benchmarks/tasks/hard/hard4.json",
    "benchmarks/tasks/hard/hard5.json",
    "benchmarks/tasks/hard/hard6.json",
]
```

```bash
python3 tests/test_agent_class.py
```

### Step 2 — Evaluate agent results with the LLM judge

```bash
# Per tier
python3 evaluations/llm_judge.py benchmarks/tasks/easy/   agent_planning_results/
python3 evaluations/llm_judge.py benchmarks/tasks/medium/ agent_planning_results/
python3 evaluations/llm_judge.py benchmarks/tasks/hard/   agent_planning_results/
```

### Step 3 — Run the baseline on all tasks

```bash
python3 baseline.py benchmarks/tasks/easy/ benchmarks/tasks/medium/ benchmarks/tasks/hard/
```

Results go to `baseline_results/`.

### Step 4 — Evaluate baseline results

```bash
python3 evaluations/llm_judge.py benchmarks/tasks/easy/   baseline_results/
python3 evaluations/llm_judge.py benchmarks/tasks/medium/ baseline_results/
python3 evaluations/llm_judge.py benchmarks/tasks/hard/   baseline_results/
```

---

## Baseline

`baseline.py` makes a single API call per task. It injects city-filtered mock inventory (flights, hotels, activities, restaurants) as context into the prompt — no tools, no state, no ReAct loop.

```bash
# Single task
python3 baseline.py benchmarks/tasks/easy/easy1.json

# Whole tier
python3 baseline.py benchmarks/tasks/medium/

# All tiers at once
python3 baseline.py benchmarks/tasks/easy/ benchmarks/tasks/medium/ benchmarks/tasks/hard/
```

Output: `baseline_results/<taskname>.md`

| | Baseline | ReAct Agent |
|---|---|---|
| API calls | 1 | 10–50 |
| Tools | None | 10 real mock-data tools |
| State | None | ConstraintTracker + booking log |
| Dynamic events | Described in prompt | Fired at `trigger_turn`, auto-replanned |
| Booking IDs | May hallucinate | Real `bk_*` IDs from tool results |
| Budget tracking | Estimated | Live per-category tracking |

---

## Evaluation

### LLM-as-a-Judge (`evaluations/llm_judge.py`)

Scores itineraries using `claude-sonnet-4-6` across 5 weighted dimensions:

| Dimension | Weight | What it measures |
|---|---|---|
| Hard Constraints | 30% | Budget, dates, accessibility, party size |
| Required Components | 25% | All required bookings present |
| Soft Preferences | 15% | Interests and preferences reflected |
| Replanning Quality | 20% | Dynamic events handled (N/A if no events) |
| Itinerary Coherence | 10% | Logical schedule, no conflicts, full duration |

Pass threshold: **70 / 100**. Replanning weight is redistributed when not applicable.

#### Single task

```bash
python3 evaluations/llm_judge.py \
    benchmarks/tasks/easy/easy1.json \
    agent_planning_results/easy1.md
```

#### Batch (whole folder)

```bash
python3 evaluations/llm_judge.py benchmarks/tasks/medium/ agent_planning_results/
```

Batch mode matches by filename stem (`medium1.json` ↔ `medium1.md`), prefers `.md` over `.json` when both exist, and prints a scored table with an average row.

#### Options

| Flag | Default | Description |
|---|---|---|
| `--threshold` | `70.0` | Pass/fail score threshold |
| `--max-tokens` | `4096` | Judge response token limit (increase to `8192` for hard tasks) |

### Unit tests

```bash
pytest tests/
```

---

## Benchmark Design

### Difficulty tiers

| Tier | Tasks | Key challenge |
|---|---|---|
| Easy | 5 | Single city, no dynamic events, basic constraints |
| Medium | 10 | Single city + 1 dynamic event requiring partial replanning |
| Hard | 6 | Multi-city + 1–2 complex events with cascading effects |

### Example tasks

| Task | Title | Dynamic Event |
|---|---|---|
| easy1 | Detroit → Chicago weekend, $300, student | None |
| medium1 | Denver → San Diego, family of 4, wheelchair | Hotel unavailable (turn 5) |
| medium6 | New Orleans jazz weekend, $2,500 | Budget cut forced (turn 6) |
| hard1 | NYC → Anchorage + Fairbanks, 8 days | Glacier tour weather-cancelled (turn 8) |
| hard2 | European honeymoon: Paris → Venice → Barcelona | Mid-trip flight cancellation |
| hard5 | California wine & nature, group of 8 | Group size change + venue closes |

### Task schema

```json
{
  "task_id": "task_006",
  "difficulty": "medium",
  "title": "Accessible Family Beach Vacation",
  "scenario": {
    "origin_city": "Denver",
    "destination_cities": ["San Diego"],
    "trip_duration_days": 5
  },
  "user_profile": {
    "party_size": 4,
    "traveler_types": ["adult", "adult", "teen", "child"],
    "special_needs": ["wheelchair_accessible"]
  },
  "initial_constraints": {
    "hard": { "budget_max": 4500, "departure_date": "2026-07-15", "return_date": "2026-07-20", "wheelchair_accessible": true },
    "soft": { "interests": ["beach", "family_activities", "zoo"] }
  },
  "dynamic_events": [{
    "event_id": "event_1",
    "trigger_turn": 5,
    "event_type": "accommodation_unavailable",
    "description": "Hotel accessible rooms fully booked. Find alternative.",
    "affected_components": ["hotel"],
    "resolution_requirements": ["Find wheelchair-accessible hotel for full stay", "Verify within budget"]
  }],
  "required_components": [
    "outbound_flight", "return_flight",
    "hotel_5_nights_wheelchair_accessible",
    "beach_activities_min_2", "family_activities_min_3",
    "accessible_restaurants_min_5"
  ],
  "success_criteria": {
    "total_cost_max": 4500,
    "all_venues_wheelchair_accessible": true,
    "replanning_successful": true
  }
}
```

### Agent architecture

The agent (`src/agent.py`) uses a **ReAct (Reasoning + Acting)** loop:

```
Task JSON
   │
   ▼
THOUGHT → ACTION (tool call) → OBSERVATION (tool result)
   └──────────────────────────────┘  (up to 50 iterations)
   │
   ▼  (all required components satisfied)
FINAL ITINERARY
```

Key design decisions:

| Decision | Detail |
|---|---|
| ConstraintTracker | Tracks budget, all bookings, hard constraints live across turns |
| Message windowing | Context = first message + last 8 messages — bounds token growth |
| Dynamic event firing | Events fire at `trigger_turn` in both action and non-action branches |
| Required-component nudge | STILL NEEDED checklist injected mid-conversation |
| Booking order | Enforced: flights → hotel → activities → restaurants |
| Streaming + early stop | Breaks as soon as complete `ACTION(...)` line is detected |

---

## Mock Data

All tools query local JSON files. Data covers **24 cities**:

**US:** Chicago, Miami, Austin, New York, San Francisco, San Diego, Seattle, Washington D.C., Orlando, New Orleans, Las Vegas, Portland, Anchorage, Fairbanks, Napa Valley, Lake Tahoe, Zion NP, Bryce Canyon NP, Moab

**International:** Paris, Venice, Barcelona, Tokyo, Kyoto

| File | Records | Key fields |
|---|---|---|
| `flights.json` | ~160 routes | airline, route, departure/arrival, price_per_seat, stops, wheelchair_accessible |
| `hotels.json` | 75 | stars, price_per_night, amenities, wheelchair_accessible, room_types, tags |
| `activities.json` | 98 | type, duration_hours, price_per_person, wheelchair_accessible, permit_required |
| `restaurants.json` | ~175 | price_level, avg_cost_per_person, meal_type, is_wheelchair_accessible |

---
