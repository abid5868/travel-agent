"""
src/utils/prompts.py - Prompt Templates for the Agent
"""

 
SYSTEM_PROMPT = """You are an expert travel planning agent that uses a ReAct (Reasoning + Acting) approach.
 
Your capabilities:
- Search for flights, hotels, restaurants, and activities using tools
- Track budget and constraints throughout planning
- Handle dynamic events and replan incrementally
 
CRITICAL RULES:

I. OPERATIONAL PROTOCOL (The ReAct Framework)
1. ALWAYS use tools to get real data - NEVER make up prices, availability, or IDs.
2. Use the exact ReAct format, THOUGHT -> ACTION -> OBSERVATION.
   THOUGHT: [Your reasoning about what to do next]
   ACTION: [Tool call with specific parameters]
   CRITICAL EXCEPTION: When the system tells you "STOP using tools. Planning is complete", you MUST break the ReAct format. Do NOT output "THOUGHT:". Your very first text MUST be "# FINAL ITINERARY".
3. BUDGET DISCIPLINE: Always check "Budget remaining" before any search. When searching, set max_price reasonably to ensure you save enough money for all remaining required components. Do not overspend on one item and leave zero budget for the others.
4. DYNAMIC REPLANNING: When a dynamic event occurs, ONLY replace the affected component. DO NOT cancel unaffected flights or hotels. 
5. NO EXCUSES & NO LOOPS: If you detect a mistake (e.g., timing conflict), you MUST CANCEL it and re-book. CRITICAL: When re-booking, you MUST choose a DIFFERENT time slot or date. Do not re-book the exact same error in a loop.

II. PHYSICS & TEMPORAL LOGIC (The Space-Time Rules)
6. THE TRANSIT RULE: You are physically "in transit" between flight departure and arrival. You MUST NOT book anything at the destination BEFORE the arrival time. 
   - All bookings MUST be in the destination city. 
   - NO "pre-departure meals in origin city", NO "takeout", NO "late arrival dining" excuses.
7. ARRIVAL DAY CALCULATION (THOUGHT REQUIRED): Before booking on an Arrival Day, your THOUGHT MUST explicitly calculate:
   "Flight arrives at [Time] + 90 min buffer = I am free at [Free Time]. Target booking is at [Booking Time]. Is [Booking Time] AFTER [Free Time]?"
   If NO, do not book.
8. BUFFER RULES: 
   - Post-Arrival: 90 mins before any booking.
   - Pre-Departure: 120 mins before flight.
   - Check-out: MUST leave at least a 30-minute gap before any meal/activity.
9. ANTI-CONCURRENCY (NO OVERLAPS): You are ONE party. You cannot be in two places at once. You MUST calculate `start_time` + `duration_hours`. If an event starts at 14:00 and lasts 4 hours, the next event CANNOT start until 18:00. DO NOT book multiple things at the same time!
10. DAILY TRANSPORTATION RULE: A 24-hour van rental only covers ONE day. If transportation is required for the whole trip, you MUST issue a separate `book_activity` action for the van for EVERY SINGLE DAY of the trip (e.g., Day 1, Day 2, Day 3, Day 4).

III. DATA INTEGRITY (The ID & Booking Rules)
10. NO ID, NO BOOKING: Every segment MUST have a unique bk_ prefix ID from a tool result. 
11. STRICT ID RULE: Using placeholders like 'system-matched' or 'included' is an automatic FAILURE.
12. CHECK-OUT ALIGNMENT: Hotel check-out date MUST match the return flight departure date.

IV. EXECUTION ORDER (The Workflow)
Follow this order strictly for new planning. MANDATORY events and TRANSPORTATION have the highest priority.
  Step 1: Search + Book ALL flights (outbound + return).
  Step 2: Search + Book hotel. (use remaining budget ÷ nights as max_price)
  Step 3: Search + Book activities/transportation (satisfy minimum requirements).
  Step 4: Search + Book restaurants (satisfy minimum requirements).
Do not move to the next step until the current one has a confirmed booking ID.

BUDGET DISCIPLINE:
  Before each search, check "Budget remaining" from the state block.
  Pass that value (divided by remaining components) as max_price.
  If no option fits the budget, report it clearly — do not skip booking silently.

Format for tool calls (EXAMPLES):

# 1. Searching Tools (Use EXACT parameter names)
ACTION: search_flights(original_city="Chicago", destination_city="Denver", departure_date="2026-07-15", max_price=300)
ACTION: search_hotels(city="Denver", max_price=150, wheelchair_accessible=True)
ACTION: search_restaurants(city="Denver", interests=["Italian"], party_size=2, target_date="2026-07-15", start_time="19:00")
ACTION: search_activities(city="Denver", interests=["Museum"], party_size=2, target_date="2026-07-16")

# 2. Booking Tools (Only book AFTER you have searched and found a valid ID)
ACTION: book_flight(flight_id="flight_CHI_NYC_003", outbound=True, origin_city="Chicago", destination_city="New York", departure_date="2026-07-15", party_size=2)
ACTION: book_hotel(hotel_id="hotel_CHI_001", check_in="2026-07-15", check_out="2026-07-18", party_size=2, num_rooms=1)
ACTION: book_restaurant(restaurant_id="rest_001", date="2026-07-15", time="19:00", party_size=2)
ACTION: book_activity(activity_id="act_CHI_001", date="2026-07-16", time="10:00", party_size=2)

# 3. Canceling Tools (Used when replanning is needed)
ACTION: cancel_hotel(booking_id="bk_hotel_CHI_001_20260715")
ACTION: cancel_flight(booking_id="bk_flight_CHI_NYC_003_20260715")
ACTION: cancel_restaurant(booking_id="bk_rest_001_20260715")
ACTION: cancel_activity(booking_id="bk_act_CHI_001_20260716")

# 4. Utility Tools
ACTION: record_surcharge(amount=800, description="Flight rebooking penalty")

Available tools (USE EXACT PARAMETER NAMES):
- search_flights(original_city, destination_city, departure_date, return_date, departure_time_earliest, return_time_latest, max_price, wheelchair_accessible): Find outbound and return flights between cities.
- book_flight(flight_id, outbound, origin_city, destination_city, departure_date, party_size): Book a specific flight.
- cancel_flight(booking_id): Cancel a flight booking.
- search_hotels(city, max_price, wheelchair_accessible): Find hotels in a city.
- book_hotel(hotel_id, check_in, check_out, party_size, num_rooms): Book a specific hotel.
- cancel_hotel(booking_id): Cancel a hotel booking.
- search_restaurants(city, special_needs, interests, preferences, max_price, party_size, target_date, start_time, wheelchair_accessible): Find restaurants in a city.
- book_restaurant(restaurant_id, date, time, party_size): Book a specific restaurant.
- cancel_restaurant(booking_id): Cancel a restaurant booking.
- search_activities(city, interests, preferences, max_price, party_size, target_date, start_time, wheelchair_accessible): Find tourist attractions and activities.
- book_activity(activity_id, date, time, party_size): Book a specific activity.
- cancel_activity(booking_id): Cancel an activity booking.
- record_surcharge(amount, description): Record a mandatory penalty fee or surcharge from a dynamic event. You MUST call this tool immediately when an event states a rebooking cost or fee, so the system deducts it from your budget.

"""
 
 
PLANNING_PROMPT_TEMPLATE = """Plan a trip with these details:
 
TRIP OVERVIEW:
- Origin: {origin_city}
- Destination(s): {destination_cities}
- Duration: {trip_days} days
- Party size: {party_size} person(s)
- Traveler type(s): {traveler_types}
 
HARD CONSTRAINTS (MUST satisfy ALL of these):
{hard_constraints}
 
PREFERENCES (Optimize for these when possible):
{soft_preferences}
 
START PLANNING:
Think step-by-step about what you need to book:
1. What flights are needed? (Check the EXACT arrival and departure times first)
2. What hotels for how many nights? (Ensure check-in is AFTER flight arrival)
3. What activities match the traveler's interests? (Ensure no timing overlaps)
4. What restaurants to recommend? (Verify you are actually in the city at that time!)
 
Begin with your first THOUGHT and ACTION."""
 
 
REPLANNING_PROMPT_TEMPLATE = """DYNAMIC EVENT OCCURRED:
 
Event Type: {event_type}
Description: {event_description}
 
CURRENT ITINERARY:
{current_itinerary}
 
AFFECTED COMPONENTS:
{affected_components}

AFFECTED CONFIRMED BOOKINGS:
{affected_bookings}

DEPENDENT BOOKINGS TO REVIEW:
{dependent_bookings}

RESOLUTION REQUIREMENTS:
{resolution_requirements}
 
REPLANNING INSTRUCTIONS:
1. When a component is invalidated by an event, you MUST explicitly call the corresponding CANCEL tool (e.g., cancel_flight) if it was already booked, to ensure your budget is correctly updated before booking a replacement. Do not assume the system handles the refund for you.
2. Find alternatives ONLY for affected components that are now missing — search then book
CRITICAL: You MUST select an alternative that is DIFFERENT from the cancelled one (e.g., different flight number, different departure time, or different hotel).
3. PRESERVE all unaffected bookings (do not cancel or re-search these)
4. Review dependent bookings and update them only if the new hotel/location makes them unsuitable
5. **DECISION LOGGING:** If the event offers multiple options, you **MUST** explicitly state in your next THOUGHT which one you choose and why (balancing budget, time, and trip quality).
6. **SURCHARGE TRACKING:** If your choice involves an additional fee or surcharge, you **MUST** explicitly state: "Surcharge of $[Amount] will be added to total cost" in your THOUGHT and reflect this in your next budget check.
7. **LABEL NEW BOOKINGS:** When you book a replacement, keep track that this is the [REPLACEMENT] for the [CANCELLED] item.
8. **NO GAPS:** Ensure inter-city transport (Paris -> Venice, etc.) has a confirmed Booking ID. Do not assume transport is satisfied without an ACTION: book_flight.
 
IMPORTANT: Do NOT write a prose analysis. Take action immediately.
Your very next response must be:
THOUGHT: [one sentence — the first search or dependent update needed]
ACTION: [the tool call — search_X, book_X, or cancel_X]"""
 
 
CONSTRAINT_REMINDER_PROMPT = """CONSTRAINT CHECK REMINDER:
 
Current budget used: ${current_budget_used}
Budget limit: ${budget_max}
Remaining: ${budget_remaining}
 
Before booking anything else, verify:
1. Total cost stays within ${budget_max}
2. All timing is feasible (flight arrival before hotel check-in, etc.)
3. All accessibility requirements are met
4. All required components are included
 
Continue planning if constraints allow, or explain if constraints cannot be satisfied."""
 
 
ERROR_HANDLING_PROMPT = """The tool call failed or returned no results.
 
Error: {error_message}
 
What should you do:
1. If no results found: Try relaxing some parameters (e.g., higher max_price)
2. If budget exhausted: Explain which constraint cannot be satisfied
3. If tool error: Try a different approach or tool
 
Think about how to proceed given this issue."""
 
 
def create_final_itinerary_prompt(
    confirmed_bookings_text: str,
    budget_context_text: str,
    requirement_status_text: str,
    success_criteria_status_text: str,
    operation_log_text: str,
) -> str:
    """
    Build the finalization prompt with ground-truth bookings injected.
    This prevents the model from hallucinating bookings that were never made.
    """
    return f"""STOP using tools. Planning is complete.

The following bookings were ACTUALLY confirmed by the system. Use ONLY these — do not invent any others.

{confirmed_bookings_text}

The following budget context was computed by the system. Treat it as ground truth.

{budget_context_text}

The following requirement status was computed by the system. Treat it as ground truth.

{requirement_status_text}

The following success-criteria status was computed by the system. Treat it as ground truth.

{success_criteria_status_text}

The following replanning action log was recorded by the system. Use it as the audit trail.

{operation_log_text}

Write a FINAL ITINERARY using the confirmed bookings above.
- Do NOT call any more tools.
- Do NOT write THOUGHT or ACTION lines.
- For any missing components (e.g. no hotel booked), explicitly state "not booked" — do not fabricate a booking.
- Do NOT claim unmet requirements are satisfied.
- Do NOT claim unmet success criteria are satisfied.
- Use the exact booked dates and times from the confirmed booking details. Do not replace them with vague phrases like "morning" or "afternoon" when an exact time exists.
- For flights, hotels, activities, and restaurants, use the exact booked name/type from the confirmed booking facts. Do not relabel a booking based on earlier reasoning.
- In the budget summary, use the system's current active budget limit. If the budget changed during replanning, do not present the original budget as the active limit.
- Under "Requirement status" and "Success criteria status", copy the system-computed status faithfully instead of paraphrasing it.
- Do NOT add a separate "All Hard Constraints Met" summary section.

Required headings and order:
1. Flights
2. Hotel
3. Activities
4. Restaurants
5. Budget Summary
6. Requirement Status
7. Success Criteria Status
8. Replanning Audit Trail

Formatting rules:
- Flights: include booking ID, route, exact date, exact time, and cost
- Hotel: include booking ID, name, dates, and cost — or "not booked"
- Activities: include booking ID, exact date, exact time, and cost — or "none booked"
- Restaurants: include booking ID, exact date, exact time, and cost — or "none booked"
- BUDGET SUMMARY TABLE: Display the system's "Total confirmed spend" directly as the GRAND TOTAL and the system's "current_active_budget_limit" as the active budget cap. If you mention the original budget at all, label it as historical context only. If you used the `record_surcharge` tool, list that fee as a line item for transparency, but DO NOT mathematically add it on top of the system total (the system has already included it).

Begin your response with: FINAL ITINERARY"""
 
 
CLARIFICATION_PROMPT_TEMPLATE = """The user's request is ambiguous or incomplete.
 
Missing information: {missing_info}
 
Ask the user a clarifying question to get the information you need.
Be specific about what you need to know."""
 
def create_planning_prompt(task: dict) -> str:
    """
    Create initial planning prompt from task specification
    
    Args:
        task: Task dictionary
    
    Returns:
        Formatted planning prompt
    """
    scenario = task.get("scenario", {})
    user_profile = task.get("user_profile", {})
    constraints = task.get("initial_constraints", {})
    
    # Format hard constraints
    hard = constraints.get("hard", {})
    hard_list = []
    for key, value in hard.items():
        if value not in [None, "", []]:
            hard_list.append(f"  • {key}: {value}")
    hard_constraints = "\n".join(hard_list) if hard_list else "  • None specified"
    
    # Format soft preferences
    soft = constraints.get("soft", {})
    soft_list = []
    
    if soft.get("interests"):
        soft_list.append(f"  • Interests: {', '.join(soft['interests'])}")
    if soft.get("preferences"):
        soft_list.append(f"  • Preferences: {', '.join(soft['preferences'])}")
    
    soft_preferences = "\n".join(soft_list) if soft_list else "  • None specified"
    
    return PLANNING_PROMPT_TEMPLATE.format(
        origin_city=scenario.get("origin_city", "Unknown"),
        destination_cities=", ".join(scenario.get("destination_cities", [])),
        trip_days=scenario.get("trip_duration_days", "?"),
        party_size=user_profile.get("party_size", 1),
        traveler_types=", ".join(user_profile.get("traveler_types", ["leisure"])),
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences
    )
 
 
def create_replanning_prompt(
    event: dict,
    current_itinerary: str,
    affected_components: list,
    affected_bookings_text: str,
    dependent_bookings_text: str,
    resolution_requirements_text: str,
) -> str:
    """
    Create replanning prompt for a dynamic event
    
    Args:
        event: Event dictionary
        current_itinerary: Current planned itinerary
        affected_components: List of affected component names
        affected_bookings_text: Ground-truth affected bookings
        dependent_bookings_text: Bookings that should be reviewed after replanning
        resolution_requirements_text: Event-specific resolution criteria

    Returns:
        Formatted replanning prompt
    """
    return REPLANNING_PROMPT_TEMPLATE.format(
        event_type=event.get("event_type", "Unknown"),
        event_description=event.get("description", ""),
        current_itinerary=current_itinerary,
        affected_components=", ".join(affected_components),
        affected_bookings=affected_bookings_text,
        dependent_bookings=dependent_bookings_text,
        resolution_requirements=resolution_requirements_text,
    )
 
 
def create_constraint_reminder(
    current_budget: float,
    budget_max: float
) -> str:
    """
    Create a constraint reminder prompt
    
    Args:
        current_budget: Currently spent budget
        budget_max: Maximum budget
    
    Returns:
        Formatted reminder prompt
    """
    remaining = budget_max - current_budget
    
    return CONSTRAINT_REMINDER_PROMPT.format(
        current_budget_used=f"{current_budget:.2f}",
        budget_max=f"{budget_max:.2f}",
        budget_remaining=f"{remaining:.2f}"
    )
 
 
# Example usage
if __name__ == "__main__":
    # Example task
    example_task = {
        "scenario": {
            "origin_city": "Chicago",
            "destination_cities": ["Denver"],
            "trip_duration_days": 3
        },
        "user_profile": {
            "party_size": 2,
            "traveler_types": ["leisure"]
        },
        "initial_constraints": {
            "hard": {
                "budget_max": 1000,
                "departure_date": "2026-07-15",
                "wheelchair_accessible": True
            },
            "soft": {
                "interests": ["hiking", "nature"],
                "preferences": ["outdoor activities"]
            }
        }
    }
    
    prompt = create_planning_prompt(example_task)
    print(prompt)
    print("\n" + "="*70 + "\n")
    print("SYSTEM PROMPT:")
    print(SYSTEM_PROMPT)
