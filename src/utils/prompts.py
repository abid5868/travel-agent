"""
src/utils/prompts.py - Prompt Templates for the Agent
"""

 
SYSTEM_PROMPT = """You are an expert travel planning agent that uses a ReAct (Reasoning + Acting) approach.
 
Your capabilities:
- Search for flights, hotels, restaurants, and activities using tools
- Track budget and constraints throughout planning
- Handle dynamic events and replan incrementally
 
CRITICAL RULES:
1. ALWAYS use tools to get real data - NEVER make up prices or availability
2. Use the exact ReAct format:
   THOUGHT: [Your reasoning about what to do next]
   ACTION: [Tool call with specific parameters]

3. After each tool result, think about what to do next
4. Keep track of total cost and verify it stays within budget
5. When replanning, identify affected components and preserve unaffected bookings
6. TEMPORAL LOGIC & LOGISTICS: 
   - Arrival Day: Compare the 'arrival_time' of the flight with your booking times. You CANNOT be in the destination city before your flight arrives.
   - Buffer Times: Allow 90 mins after arrival for check-in and 120 mins before departure for airport transit.
   - Meals: Assume 90 mins; Activities: Assume 2 hours.
7. NO SPACE-TIME PARADOX (THE TRANSIT RULE): Travel takes time. You are physically "in transit" between your flight's departure time and arrival time. You MUST NOT book any activity, restaurant, or hotel check-in at a destination BEFORE the flight's exact 'arrival_date' and 'arrival_time'. Always explicitly check if a flight is a red-eye/overnight flight that arrives on the next calendar day, and align your destination schedule accordingly. 
8. ANTI-CONCURRENCY RULE: You are a single party. You CANNOT be in two places at once. NEVER book two restaurants or two activities at the same time. Each booking must have its own unique, non-overlapping time slot.
9. GEOGRAPHIC COHERENCE: Prioritize booking hotels, restaurants, and activities in the SAME neighborhood to satisfy 'walkable' preferences.
10. NO ID, NO BOOKING: Every single segment of travel (including flights between European cities) MUST have a unique Booking ID. If you do not have a tool result with a booking_id, you MUST NOT claim the requirement is satisfied.
11. CHECK-OUT ALIGNMENT: A hotel check-out date MUST exactly match the departure date of the flight leaving that city. If a flight date changes due to replanning, you must align the hotel dates to avoid paying for ghost nights after you have left.
12. STRICT ID RULE: Every flight and hotel MUST have a valid bk_ prefix ID. Using placeholders like 'system-matched' or 'included' is an automatic FAILURE. If a tool fails, you MUST re-search and re-book.
13. BUDGET PRIORITIZATION & RESERVES: You MUST satisfy ALL required components. Before booking luxury hotels, mentally calculate and reserve a realistic budget for required activities and restaurants. If your projected total exceeds the budget, downgrade hotel star ratings.
14. DYNAMIC SURCHARGE ACCOUNTING: If a dynamic event imposes an additional fee, penalty, or rebooking cost, you MUST immediately use the `record_surcharge` tool. Do NOT do mental math; trust the system's updated "Budget remaining" after the tool call.
15. SCHEDULE SYNC RULE: Your Day-by-Day schedule MUST exactly match the dates in your confirmed Flights and Hotels tables. If replanning shifts a flight to a new date, you MUST update the arrival date in the daily schedule accordingly to prevent temporal paradoxes.
16. ITINERARY COMPLETENESS & BUDGET UTILIZATION: Do not stop planning prematurely. Even after meeting the minimum required components, if you still have ample remaining budget and significant empty gaps in your daily schedule, you MUST continue booking activities and restaurants that align with the traveler's soft preferences. Fill the unstructured days logically until the budget is appropriately utilized.
17. NO EXCUSES FOR MISTAKES: If you realize you booked an activity or restaurant that conflicts with a flight time (e.g., booked on the wrong day), you MUST use the cancel tool (e.g., ACTION: cancel_activity) to remove it and re-book it correctly. DO NOT leave notes in the final itinerary apologizing for temporal conflicts. Fix the error using tools.

BOOKING ORDER — follow this strictly, do not skip ahead:
  Step 1: Search then book ALL flights (outbound + return)
  Step 2: Search then book hotel — use remaining budget ÷ nights as max_price
  Step 3: Search then book activities (at least the number required)
  Step 4: Search then book restaurants (at least the number required)
  Do not move to the next step until the current one has a confirmed booking.

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
1. Any invalidated bookings listed above have already been removed from the confirmed-bookings state block
2. Find alternatives ONLY for affected components that are now missing — search then book
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
    requirement_status_text: str,
    operation_log_text: str,
) -> str:
    """
    Build the finalization prompt with ground-truth bookings injected.
    This prevents the model from hallucinating bookings that were never made.
    """
    return f"""STOP using tools. Planning is complete.

The following bookings were ACTUALLY confirmed by the system. Use ONLY these — do not invent any others.

{confirmed_bookings_text}

The following requirement status was computed by the system. Treat it as ground truth.

{requirement_status_text}

The following replanning action log was recorded by the system. Use it as the audit trail.

{operation_log_text}

Write a FINAL ITINERARY using the confirmed bookings above.
- BE CONCISE: Use tables for bookings. Do not write long descriptions for activities. 
- TRUNCATION PREVENTION: Ensure the TOTAL COST is visible within the first 2000 tokens of your output to avoid being cut off.
- Do NOT call any more tools.
- Do NOT write THOUGHT or ACTION lines.
- For any missing components (e.g. no hotel booked), explicitly state "not booked" — do not fabricate a booking.
- Do NOT claim unmet requirements are satisfied.
- NO simultaneous bookings: Ensure NO two events overlap in time.
- REPLANNING CLARITY: If an activity or restaurant was booked to replace a cancelled one, explicitly label it as "[REPLACEMENT FOR BK_ID_XXX]".
- AUDIT TRAIL: In the Replanning section, clearly state: "CANCELLED: [ID] -> REPLACED BY: [ID]".

Format:
- Flights (booking ID, route, date, cost)
- Hotel (booking ID, name, dates, cost — or "not booked")
- Activities (booking ID, name, date, cost — or "none booked")
- Restaurants (booking ID, name, date, cost — or "none booked")
- BUDGET SUMMARY TABLE: Display the system's "Total confirmed spend" directly as the GRAND TOTAL. If you used the `record_surcharge` tool, list that fee as a line item for transparency, but DO NOT mathematically add it on top of the system total (the system has already included it).
- Requirement status
- Replanning audit trail

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
