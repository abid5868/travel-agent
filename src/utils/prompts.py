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
1. What flights are needed?
2. What hotels for how many nights?
3. What activities match the traveler's interests?
4. What restaurants to recommend?
 
Begin with your first THOUGHT and ACTION."""
 
 
REPLANNING_PROMPT_TEMPLATE = """DYNAMIC EVENT OCCURRED:
 
Event Type: {event_type}
Description: {event_description}
 
CURRENT ITINERARY:
{current_itinerary}
 
AFFECTED COMPONENTS:
{affected_components}
 
REPLANNING INSTRUCTIONS:
1. Identify exactly which bookings are affected by this event
2. Find alternatives ONLY for affected components
3. PRESERVE all unaffected bookings (do not regenerate the entire trip!)
4. Update any dependent bookings (e.g., if flight time changes, hotel check-in may need adjustment)
5. Verify all hard constraints are still satisfied
 
IMPORTANT: This is incremental replanning, not full regeneration.
 
Think about:
- What specifically needs to change?
- What can stay the same?
- What dependencies exist?
 
Start with your THOUGHT about what needs to be replanned."""
 
 
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
 
 
FINAL_ITINERARY_PROMPT = """You've completed the planning. Now create a FINAL ITINERARY summary.
 
Format it clearly with:
- All flights (with times and prices)
- All hotels (with dates and prices)
- All restaurants and activities
- Total cost
- Verification that all constraints are met
 
Begin your summary with: FINAL ITINERARY"""
 
 
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
    affected_components: list
) -> str:
    """
    Create replanning prompt for a dynamic event
    
    Args:
        event: Event dictionary
        current_itinerary: Current planned itinerary
        affected_components: List of affected component names
    
    Returns:
        Formatted replanning prompt
    """
    return REPLANNING_PROMPT_TEMPLATE.format(
        event_type=event.get("event_type", "Unknown"),
        event_description=event.get("description", ""),
        current_itinerary=current_itinerary,
        affected_components=", ".join(affected_components)
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