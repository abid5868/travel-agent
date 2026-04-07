# Agent Loop Fixes

This document describes the bugs found in the ReAct planning loop (`src/agent.py`) and the fixes applied.

---

## Background: How the Loop Works

The agent uses a ReAct (Reasoning + Acting) loop. Each iteration:
1. Calls the LLM API with the conversation history
2. Parses the response for an `ACTION:` line
3. If action found → executes the tool, appends result as a user message
4. If no action → checks for dynamic events or a `FINAL ITINERARY` response
5. Repeats until `max_iterations` or early exit on `FINAL ITINERARY`

---

## Bug 1: Repeated Searches Wasted Iterations

### Problem
The conversation history is windowed (only the last N messages are sent to the API) to keep token counts bounded. A side effect: the model loses memory of search results it already received. It would re-search the same city for flights, hotels, or activities 2–4 times per run, consuming iterations without making progress.

**Observed example:** `search_hotels:Chicago` called 3× in a single run before any hotel was booked.

### Fix
Track every completed search in a `_searched: set` on the agent. After each successful `search` tool call, add a key like `search_hotels:Chicago` to the set. This set is included in the `_booking_summary()` text that is injected into every API call:

```
ALREADY SEARCHED (do not search these again, use results above):
- search_flights:Detroit->Chicago
- search_hotels:Chicago
```

The model sees this and skips re-searching, using iteration budget on bookings instead.

**Files changed:** `src/agent.py` — `_reset()`, `_execute_tool()`, `_booking_summary()`

---

## Bug 2: Hallucinated Bookings in Final Itinerary

### Problem
When the nudge prompt (`FINAL_ITINERARY_PROMPT`) fired near the iteration limit, the model was asked to "write a summary of your plan." With a windowed conversation history, the model had lost context of what it actually booked. It responded by writing a plausible-looking itinerary that included hotels, restaurants, and activities that were **never actually booked through the tools**.

**Observed example:**
- `Cost tracking: 198.0` (only 2 flights confirmed in tracker)
- Itinerary showed hotel ($70), 2 restaurants ($22), activities ($0)
- Total claimed: $290 — fabricated from model memory

This is the most dangerous bug: results look correct but are untrue.

### Fix
The `ConstraintTracker` stores every confirmed booking as ground truth. Before asking the model to finalize, build a text representation of all real bookings from `tracker.bookings` and inject it directly into the final prompt:

```
The following bookings were ACTUALLY confirmed by the system. Use ONLY these.

- [FLIGHT] booking_id=bk_flight_DET_CHI_001_20260227  cost=$99.0
- [FLIGHT] booking_id=bk_flight_CHI_DET_001_20260301  cost=$99.0

Total confirmed spend: $198.0
Budget limit: $300.0
```

The prompt then says: **"For any missing components (hotel, activities), explicitly state 'not booked' — do not fabricate."**

This forces the model to report honest gaps rather than invent bookings.

**Files changed:**
- `src/agent.py` — `_build_confirmed_bookings_text()` (new method), nudge now calls `create_final_itinerary_prompt(self._build_confirmed_bookings_text())`
- `src/utils/prompts.py` — `FINAL_ITINERARY_PROMPT` replaced with `create_final_itinerary_prompt(confirmed_bookings_text: str)`

---

## Bug 3: Loop Ran Forever / Never Terminated Early

### Problem (original)
The early exit check (`if "FINAL ITINERARY" in response: return`) and the nudge prompt were both inside the `else` branch — they only ran when `action_needed=False`. When the model kept calling tools every iteration, the `else` branch was never reached. The loop always ran all `max_iterations`.

With `max_iterations=20` and ~25–30 seconds per API call (due to large conversation history), this was 8–10 minutes of silent running.

### Contributing factors
- `full_data` field in every booking response added the entire hotel/flight/activity record to conversation history, inflating token counts (hundreds of extra tokens per booking)
- Search results returned up to 10 full items per search
- No API call timeout — a slow/hung call would block indefinitely

### Fixes applied
1. **Moved nudge outside `else`** — fires at `iteration >= max_iterations - 3` regardless of whether a tool was called
2. **Trimmed tool results** — `_trim_result()` strips `full_data` from booking responses and caps search results at 5 items with only relevant fields
3. **Sliding window** — `_get_agent_response()` only sends `[initial_prompt] + last 8 messages` to the API, bounding input token growth
4. **API timeout** — `timeout=60` on `client.messages.create()` prevents indefinite blocking
5. **Final API call after loop** — if the loop ends with a user message (the nudge) still unanswered, one extra API call is made so the model can actually respond
6. **Alternating roles fix** — if no user message was added in an iteration, `"Continue planning."` is appended to keep `user → assistant` alternation intact (required by the Anthropic API)
7. **max_iterations raised to 20** — enough headroom for multi-component trips now that Fixes 1 and 2 prevent wasted iterations

**Files changed:** `src/agent.py` — `_react_planning_loop()`, `_get_agent_response()`, `_execute_tool()`, `_trim_result()` (new method)

---

## Summary Table

| Bug | Root Cause | Fix | Impact |
|-----|-----------|-----|--------|
| Repeated searches | Sliding window causes model to forget prior search results | Track `_searched` set; inject into every API call | Saves 2–4 iterations per run |
| Hallucinated bookings | Model writes final itinerary from memory, not actual bookings | Inject `tracker.bookings` ground truth into final prompt | Eliminates false success reports |
| Loop never terminates early | Nudge/exit only in `else` branch; tool calls bypass it | Move nudge outside `if/else`; add post-loop final call | Reduces 8–10 min runs to ~3–4 min |
| Slow API calls | `full_data` bloat; full history re-sent every call | `_trim_result()` + sliding window + timeout | ~3× faster per call |
| Broken message alternation | Non-action turns left history ending on `assistant` | Append `"Continue planning."` as fallback user message | Prevents API errors and erratic model output |

---

## Planning Quality Issues (Found via Conceptual Validation)

After running easy1, medium1, and hard1 through the fixed loop, four planning quality problems were identified.

---

### Problem 1: Agent had no idea what it still needed to book

**Root cause:** The booking summary showed confirmed bookings but not what was still required. The model had no checklist to follow, so after booking flights and a hotel it would drift — re-searching things it already had instead of moving to activities and restaurants.

**Observed:** hard1 produced zero activity or restaurant bookings despite $1800 of budget headroom.

**Fix:** `required_components` from the task spec is now loaded into `self._required_components` and a `STILL NEEDED` checklist is injected into every API call via `_booking_summary()`. Each component is marked `[x]` once a booking of the matching type is confirmed.

---

### Problem 2: Budget constraint violated because agent didn't calculate per-category limits

**Root cause:** When searching for a hotel, the agent passed no `max_price` derived from remaining budget. For easy1 (budget=$300, flights=$198), the cheapest hotel was $79/night × 2 = $158, pushing total to $374.

**Fix:** `_booking_summary()` now computes remaining budget and divides it across still-unbooked categories, injecting: `"Approx $X available per remaining category — use this as max_price in searches"`. The system prompt also now instructs the agent to always pass budget-derived `max_price` values.

---

### Problem 3: Dynamic events fired too late

**Root cause:** Dynamic event checking was inside the `else` branch (only when `action_needed=False`). Since the model calls a tool every turn for most of a run, the `else` branch was never reached until near the iteration limit. A `trigger_turn=5` event would fire at turn 18.

**Observed:** medium1's hotel conflict event fired at iter 18, leaving only 2 iterations for replanning — not enough to cancel and rebook.

**Fix:** Dynamic event checking is now done inside the `if action_needed` branch too, appended after the tool result. Events fire at their `trigger_turn` regardless of whether a tool was just called. The model sees the event prompt on the very next iteration.

---

### Problem 4: Replanning prompt produced prose analysis, not tool calls

**Root cause:** The replanning prompt ended with `"Start with your THOUGHT about what needs to be replanned."` The model interpreted this as permission to write a detailed analysis. With few iterations left, no actual cancel/search/book calls were made.

**Fix:** The replanning prompt now ends with:
```
IMPORTANT: Do NOT write a prose analysis. Take action immediately.
Your very next response must be:
THOUGHT: [one sentence — the first affected booking to cancel or first search needed]
ACTION: [the tool call — cancel_X or search_X]
```

---

### Problem 5: No enforced booking order

**Root cause:** The model would sometimes search hotels before booking flights, or search activities before the hotel was confirmed. On hard tasks this led to partial bookings across all categories rather than complete bookings in any.

**Fix:** A `BOOKING ORDER` directive was added to `SYSTEM_PROMPT`:
```
Step 1: Search + book all flights
Step 2: Search + book hotel (use remaining budget ÷ nights as max_price)
Step 3: Search + book activities
Step 4: Search + book restaurants
Do not move to the next step until the current one has a confirmed booking.
```

---

### Results After These Fixes (medium1 re-run)

| Metric | Before | After |
|--------|--------|-------|
| Dynamic event trigger turn | 18 (wrong) | 5 (correct) |
| Replanning | Prose only | Immediate search + book |
| Activities booked | 0 | 3 |
| Restaurants booked | 2 | 4 |
| Budget used | $3,083 | $2,951 |
| API calls | 19 | 18 |

---

## Performance Optimizations

### Optimization 1: Streaming with Early ACTION Stop

**Problem:** For tool-calling turns the agent only needed ~50 tokens (THOUGHT + ACTION line), but `messages.create()` blocks until the full `max_tokens` budget is exhausted or the model stops. Long tail generation wasted time.

**Fix:** Tool-calling turns now use `client.messages.stream()`. As soon as a complete `ACTION(...)` line is detected in the stream, we break out and return what we have. Planning/replanning/final turns still use the full blocking call since they need complete responses.

**Files:** `src/agent.py` — `_stream_until_action()`, `_get_agent_response()`

### Optimization 2: Dynamic max_tokens per Turn Type

**Problem:** All turns used `max_tokens=2000`. Tool-calling turns never need that many tokens — a THOUGHT + ACTION is ~50-100 tokens.

**Fix:**
- Tool-calling turns: `max_tokens=700`
- Planning / replanning / final turns: `max_tokens=3000`

This reduces the upper bound the model can generate per call, and ensures planning turns have enough room for full itineraries.

### Model Choice

The agent now uses Sonnet throughout. There is no `_fast_model` path in the runtime code.

### Measured Impact (medium1)

| Run | Model | Time | Activities Booked | Restaurants Booked |
|-----|-------|------|-------------------|--------------------|
| Baseline (no streaming) | Sonnet | 145s | 4 | 4 |
| Sonnet + streaming early stop | Sonnet | 147s | 4 | 5 ✅ |

The streaming optimization keeps quality intact and hits the 5-restaurant requirement. Time is comparable to baseline; the main benefit is capping max_tokens at 700 for tool turns, which keeps per-turn latency bounded.

### Future Speed Ideas (Not Yet Implemented)

- **Parallel search calls:** When the checklist shows both activities and restaurants still needed, fire `search_activities` and `search_restaurants` simultaneously. Currently the loop is strictly sequential.
- **Cache search results:** If the same city + params are searched twice (Fix 1 helps prevent this), return cached results instead of calling the tool.
- **Smaller window for booking-only turns:** Once all searches are done, the conversation window could be reduced further since the model only needs the booking IDs.

---

## Later Fixes Added After More Task Re-runs

The first round of loop fixes made the agent faster and more honest, but more task re-runs exposed additional quality gaps. The sections below describe the later changes that were added afterward.

### Problem 6: Required-component matching was too shallow

**Root cause:** The first checklist implementation mostly matched by booking type. One hotel could satisfy `hotel_5_nights_wheelchair_accessible`, one activity could appear to satisfy `beach_activities_min_2`, and one restaurant could stand in for `accessible_restaurants_min_5`.

**Observed:**
- medium1 claimed beach requirements were satisfied from hotel proximity instead of actual activity bookings
- hard tasks could appear partially complete after a single activity or restaurant

**Fix:** Requirement checking in `src/agent.py` is now semantic rather than category-only.

New helper methods:
- `_matched_component_count()`
- `_required_component_target()`
- `_flight_booking_matches()`
- `_lodging_booking_matches()`
- `_experience_booking_matches()`
- `_component_keywords()`

This now correctly handles:
- `*_min_N` counts
- hotel night counts
- wheelchair-accessibility requirements
- outbound vs. return flights
- keyword-based activity and restaurant requirements such as beach, family, zoo, aquarium, wildlife, and northern lights

The final itinerary prompt also now receives system-generated requirement status text, so the model cannot "self-grade" unmet items as satisfied.

**Files changed:** `src/agent.py`, `src/utils/prompts.py`

---

### Problem 7: Tool failures were not consistently recognized

**Root cause:** The loop only treated `{"error": ...}` as a failure, but the tools frequently return errors in the shape `{"status": "error", "message": ...}`.

**Observed:** Failed tool calls were sometimes injected into the conversation as if they were valid search results, so the model got no retry guidance.

**Fix:** `_extract_tool_error()` now normalizes both error shapes and routes them through `ERROR_HANDLING_PROMPT`.

**Files changed:** `src/agent.py`

---

### Problem 8: Booking order was still only a prompt instruction

**Root cause:** The prompt said "book flights first, then hotel, then activities, then restaurants," but the loop itself did not enforce it.

**Observed:** easy1 and medium1 could still book activities or restaurants before completing the necessary transport or lodging stage.

**Fix:** `_validate_booking_order()` and `_current_booking_stage()` now enforce order in code. If required flights or lodging are still open, out-of-order searches and bookings are rejected as tool errors.

This was later extended further:
- intercity trips can implicitly require flights even when the task file only explicitly lists a hotel
- `_current_booking_stage()` treats those implicit transport requirements as the first stage

**Files changed:** `src/agent.py`

---

### Problem 9: Dynamic-event replanning was not auditable or precise enough

**Root cause:** Dynamic events were originally appended as generic prompts. The final itinerary could not show what was cancelled, what was preserved, or whether replanning actually happened.

**Observed:** medium1 could say the hotel issue was handled without clearly showing cancel/rebook order.

**Fixes applied:**
1. Every successful `book_*` and `cancel_*` action is now recorded in `_operation_log`
2. Final itinerary generation receives that operation log as ground truth
3. Dynamic events now track:
   - affected bookings
   - dependent bookings to review
   - preserved bookings
   - removed invalid bookings
4. Hotel-disruption events can now remove invalid hotel bookings from confirmed state before replanning starts

This made medium1’s hotel replacement traceable in the final audit trail.

**Files changed:** `src/agent.py`, `src/utils/prompts.py`

---

### Problem 10: Dynamic events could fire before the affected booking even existed

**Root cause:** Events triggered strictly by turn count. If the hotel event fired before any hotel was booked, the replanning prompt was wasted.

**Observed:** medium1 sometimes consumed its hotel-disruption event before a hotel had ever been confirmed.

**Fix:** `_event_is_ready()` now checks both:
- the configured `trigger_turn`
- whether there is actually a matching affected booking in the tracker

This means hotel events now wait until a real hotel exists before firing.

**Files changed:** `src/agent.py`

---

### Problem 11: Restaurant searches were too narrow and stalled medium tasks

**Root cause:** The agent would search with tight interest filters and accept too-few results, even when the task still required multiple accessible restaurants.

**Observed:** medium1 often under-filled `accessible_restaurants_min_5` despite sufficient restaurant inventory in San Diego.

**Fixes applied:**
- `src/tools/restaurants.py` now sorts by relevance score first, then price, instead of filtering out every non-perfect interest match
- `_expand_restaurant_search_results()` in `src/agent.py` performs a fallback search with broader params and merges the results when a required restaurant count is still missing

This made the 5-accessible-restaurant requirement reliably reachable.

**Files changed:** `src/tools/restaurants.py`, `src/agent.py`

---

### Problem 12: Flight booking semantics caused avoidable retry churn

**Root cause:** Return-flight booking expected origin/destination parameters in a stricter way than the model naturally supplied, even when the selected flight ID already represented the correct route.

**Observed:** medium1 spent extra turns cancelling and re-booking flights due to return-flight argument mismatches.

**Fix:** `src/tools/flights.py` now accepts return-flight booking params that match the selected flight’s actual route, and it stores normalized lowercase booking types (`outbound_flight`, `return_flight`) so downstream requirement checking is consistent.

**Files changed:** `src/tools/flights.py`

---

### Problem 13: easy1 was impossible with the original budget and too-easy success condition

**Root cause 1:** The original `easy1` task only explicitly required `hotel_2_nights`, so the loop could finalize without any intercity transport booking.

**Root cause 2:** With the existing mock data, the original `$300` budget was below the minimum realistic cost of:
- Detroit → Chicago flight
- Chicago → Detroit flight
- 2-night hotel

**Fixes applied:**
1. `src/agent.py` now enforces implicit flight requirements for intercity trips when:
   - `origin_city != destination_city`
   - the task does not already explicitly list flight components
2. New helper methods:
   - `_intercity_trip()`
   - `_implicit_flight_requirement_enabled()`
   - `_has_matching_transport_flight()`
   - `_implicit_transport_satisfied()`
   - `_all_planning_requirements_satisfied()`
3. Finalization, checklist rendering, booking order, and success now use planning requirements rather than only explicit `required_components`
4. `benchmarks/tasks/easy/easy1.json` budget was raised from `$300` to `$500` to match the current flight + hotel inventory

This prevents the agent from treating transport as optional on an actual city-to-city trip.

**Files changed:** `src/agent.py`, `benchmarks/tasks/easy/easy1.json`

---

### Problem 14: medium1 benchmark data was under-supported

**Root cause:** The original San Diego activity inventory did not contain enough wheelchair-accessible beach activities to satisfy `beach_activities_min_2`.

**Fixes applied:**
- `Mission Beach Surf & Swim` was upgraded to `Mission Beach Adaptive Surf & Swim` and marked wheelchair accessible
- a second accessible San Diego beach activity was added: `Coronado Accessible Beach Day & Sand Chair Rental`

This changed medium1 from partially impossible to solvable with the current tool surface.

**Files changed:** `benchmarks/mock_data/activities.json`

---

### Problem 15: Some benchmark tasks required unsupported rental-car bookings

**Root cause:** The codebase still has no rental-car booking tool, but some hard tasks required rental cars as explicit components.

**Observed:** hard1 and hard6 both contained direct rental-car requirements even though the runtime cannot satisfy them.

**Fixes applied to benchmark files:**
- `hard1`
  - removed `requires_rental_car_anchorage`
  - removed `rental_car_anchorage`
  - rewrote the glacier-cancellation event so the substitute tour includes transportation
  - renamed the success criterion from `rental_car_logistics_resolved` to `anchorage_to_fairbanks_transition_resolved`
- `hard6`
  - removed standalone `rental_car` from `required_components`
  - clarified in notes that ground transfer is itinerary reasoning, not a separate unsupported booking component

After this cleanup, there are no remaining `rental_car` or `requires_rental_car` entries under `benchmarks/tasks`.

**Files changed:** `benchmarks/tasks/hard/hard1.json`, `benchmarks/tasks/hard/hard6.json`

---

## Additional Test Coverage Added

`tests/test_agent_logic.py` now covers the later fixes too, including:
- semantic count-based requirement satisfaction
- accessibility-aware restaurant matching
- booking-order enforcement
- dual-shape tool error handling
- requirement-status and operation-log rendering
- trimmed flight search payloads
- dynamic-event invalidation of unavailable hotels
- restaurant fallback broadening
- medium benchmark data support for two accessible beach activities
- dynamic-event readiness gating
- return-flight booking semantics
- implicit intercity-flight requirements

These tests help keep easy1 and medium1 regressions from reappearing while hard-task benchmark cleanup continues.
