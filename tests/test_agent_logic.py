import json

from src.agent import TravelAgent
from src.core.constraints import ConstraintTracker
from src.tools.flights import FlightSearchTool
from src.utils.types import Booking


def make_agent():
    agent = TravelAgent.__new__(TravelAgent)

    class EmptyTool:
        pass

    agent.tracker = ConstraintTracker()
    agent.conversation_history = []
    agent._searched = set()
    agent._required_components = []
    agent._soft_preferences = {}
    agent._success_criteria = {}
    agent._scenario = {}
    agent._operation_log = []
    agent._triggered_events = []
    agent._post_requirements_turns = 0
    agent.turn_count = 0
    agent.metadata = {}
    agent.flight_tool = EmptyTool()
    agent.hotel_tool = EmptyTool()
    agent.restaurant_tool = EmptyTool()
    agent.activity_tool = EmptyTool()
    return agent


def test_required_component_counts_are_semantic():
    agent = make_agent()
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_act_1",
            type="activity",
            details={"name": "Mission Beach Surf & Swim", "full_data": {"tags": ["beach_activity", "family_friendly"]}},
            cost=40.0,
        )
    )

    assert agent._matched_component_count("beach_activities_min_2") == 1
    assert agent._component_satisfied("beach_activities_min_2") is False


def test_required_component_accessibility_and_counts_work():
    agent = make_agent()
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            details={"name": "Accessible Grill", "full_data": {"is_wheelchair_accessible": True}},
            cost=30.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_rest_2",
            type="restaurant",
            details={"name": "Accessible Pizza", "full_data": {"is_wheelchair_accessible": True}},
            cost=25.0,
        )
    )

    assert agent._matched_component_count("accessible_restaurants_min_2") == 2
    assert agent._component_satisfied("accessible_restaurants_min_2") is True


def test_booking_order_blocks_optional_activities_until_required_hotel_done():
    agent = make_agent()
    agent._required_components = ["hotel_2_nights"]

    assert agent._validate_booking_order("search_activities", "search") == (
        "Booking order violation: complete required lodging before activities or restaurants."
    )


def test_intercity_trip_requires_flights_even_without_explicit_flight_components():
    agent = make_agent()
    agent._required_components = ["hotel_2_nights"]
    agent._scenario = {"origin_city": "Detroit", "destination_cities": ["Chicago"]}
    agent.tracker.add_constraint("return_date", "2026-03-01", is_hard=True)
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"nights": 2, "full_data": {"wheelchair_accessible": True}},
            cost=158.0,
        )
    )

    assert agent._all_required_components_satisfied() is True
    assert agent._all_planning_requirements_satisfied() is False
    assert agent._current_booking_stage() == "flight"

    requirement_text = agent._build_requirement_status_text()
    assert "- intercity_outbound_flight: UNMET (matched 0 / required 1)" in requirement_text
    assert "- intercity_return_flight: UNMET (matched 0 / required 1)" in requirement_text


def test_train_or_flight_requirements_are_satisfied_by_flight_bookings():
    agent = make_agent()
    agent._required_components = ["outbound_train_or_flight", "return_train_or_flight"]
    agent._scenario = {"origin_city": "Philadelphia", "destination_cities": ["New York"]}
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_1",
            type="flight",
            details={
                "type": "outbound_flight",
                "origin_city": "Philadelphia",
                "destination_city": "New York",
                "departure_time": "08:00",
            },
            cost=89.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_2",
            type="flight",
            details={
                "type": "return_flight",
                "origin_city": "New York",
                "destination_city": "Philadelphia",
                "departure_time": "20:00",
            },
            cost=89.0,
        )
    )

    assert agent._matched_component_count("outbound_train_or_flight") == 1
    assert agent._matched_component_count("return_train_or_flight") == 1
    assert agent._component_satisfied("outbound_train_or_flight") is True
    assert agent._component_satisfied("return_train_or_flight") is True


def test_extract_tool_error_supports_both_error_shapes():
    agent = make_agent()

    assert agent._extract_tool_error({"error": "boom"}) == "boom"
    assert agent._extract_tool_error({"status": "error", "message": "no results"}) == "no results"
    assert agent._extract_tool_error({"status": "success"}) == ""


def test_requirement_status_and_operation_log_text_are_built_from_state():
    agent = make_agent()
    agent._required_components = ["hotel_2_nights", "beach_activities_min_2"]
    agent.turn_count = 5
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"nights": 2, "full_data": {"wheelchair_accessible": True}},
            cost=158.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_act_1",
            type="activity",
            details={"name": "Mission Beach Surf & Swim", "full_data": {"tags": ["beach_activity"]}},
            cost=40.0,
        )
    )
    agent._record_operation("book_hotel", "book", {"booking_id": "bk_hotel_1"}, {})

    requirement_text = agent._build_requirement_status_text()
    operation_text = agent._build_operation_log_text()

    assert "- hotel_2_nights: SATISFIED (matched 1 / required 1)" in requirement_text
    assert "- beach_activities_min_2: UNMET (matched 1 / required 2)" in requirement_text
    assert operation_text == "- turn 5: book book_hotel -> confirmed bk_hotel_1"


def test_trim_result_reduces_flight_search_payload():
    agent = make_agent()

    trimmed = agent._trim_result(
        {
            "outbound_flights": [
                {
                    "flight_id": "flight_1",
                    "from_city": "Detroit",
                    "to_city": "Chicago",
                    "price_per_seat": 99,
                    "amenities": ["wifi"],
                    "full_payload": "x" * 200,
                }
            ],
            "return_flights": [],
        },
        "search",
    )

    assert trimmed == {
        "outbound_flights": [
            {
                "flight_id": "flight_1",
                "from_city": "Detroit",
                "to_city": "Chicago",
                "price_per_seat": 99,
            }
        ],
        "return_flights": [],
    }


def test_success_criteria_fail_when_trip_has_no_transport():
    agent = make_agent()
    agent._scenario = {"origin_city": "Detroit", "destination_cities": ["Chicago"]}
    agent._success_criteria = {"timing_feasible": True}

    assert agent._success_criteria_satisfied() is False


def test_hard_constraints_fail_on_accessibility_violation():
    agent = make_agent()
    agent.tracker.add_constraint("wheelchair_accessible", True, is_hard=True)
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            details={"name": "Cafe", "full_data": {"is_wheelchair_accessible": False}},
            cost=20.0,
        )
    )

    assert agent._hard_constraints_satisfied() is False


def test_dynamic_event_removes_invalid_hotel_and_marks_dependent_restaurants_for_review():
    agent = make_agent()

    class FakeHotelTool:
        def cancel(self, booking_id):
            return {"status": "success", "cancellation_id": f"cancel_{booking_id}"}

    agent.hotel_tool = FakeHotelTool()
    agent.turn_count = 5
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_1",
            type="flight",
            details={"type": "outbound_flight"},
            cost=200.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"hotel_name": "Mission Bay Family Resort", "nights": 5, "full_data": {"wheelchair_accessible": True}},
            cost=995.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            details={"name": "Mission Bay Family Grill", "full_data": {"is_wheelchair_accessible": True}},
            cost=120.0,
        )
    )

    prompt = agent._handle_dynamic_event(
        {
            "event_type": "accommodation_unavailable",
            "description": "Accessible rooms are unavailable.",
            "affected_components": ["hotel"],
            "resolution_requirements": ["Book a replacement hotel"],
        },
        "CURRENT ITINERARY",
        {},
    )

    assert agent.tracker.get_booking("bk_hotel_1") is None
    assert agent.tracker.get_booking("bk_flight_1") is not None
    assert "bk_hotel_1" in prompt
    assert "bk_rest_1" in prompt
    assert agent._triggered_events[0]["preserved_booking_ids"] == ["bk_flight_1"]
    assert agent._operation_log[-1]["summary"] == (
        "removed unavailable hotel bk_hotel_1 due to accommodation_unavailable"
    )


def test_restaurant_search_fallback_broadens_results_when_required_count_is_missing():
    agent = make_agent()
    agent._required_components = ["accessible_restaurants_min_5"]
    agent.metadata = {"tool_calls": 0}

    class FakeRestaurantTool:
        def __init__(self):
            self.calls = []

        def search(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("interests"):
                return [{"restaurant_id": "rest_a", "name": "Focused Match", "average_cost_per_person": 15}]
            return [
                {"restaurant_id": "rest_a", "name": "Focused Match", "average_cost_per_person": 15},
                {"restaurant_id": "rest_b", "name": "Broader Option", "average_cost_per_person": 18},
                {"restaurant_id": "rest_c", "name": "Broader Option 2", "average_cost_per_person": 20},
            ]

    agent.restaurant_tool = FakeRestaurantTool()

    result = agent._execute_tool(
        "search_restaurants",
        {
            "city": '"San Diego"',
            "interests": '["beach"]',
            "party_size": "4",
            "wheelchair_accessible": "true",
            "max_price": "40",
        },
    )

    assert [item["restaurant_id"] for item in result] == ["rest_a", "rest_b", "rest_c"]
    assert len(agent.restaurant_tool.calls) == 2
    assert "interests" not in agent.restaurant_tool.calls[1]


def test_medium_data_supports_two_accessible_beach_activities_in_san_diego():
    data = json.load(open("benchmarks/mock_data/activities.json", encoding="utf-8"))
    activities = [
        activity for activity in data["activities"]
        if activity["city"] == "San Diego"
        and activity["wheelchair_accessible"] is True
        and (
            activity["type"] == "beach_activity"
            or "beach_activity" in activity.get("tags", [])
        )
    ]

    assert len(activities) >= 2


def test_dynamic_event_waits_until_affected_booking_exists():
    agent = make_agent()
    agent.turn_count = 5

    assert agent._event_is_ready({"trigger_turn": 5, "affected_components": ["hotel"]}) is False

    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"hotel_name": "Mission Bay Family Resort", "nights": 5, "full_data": {"wheelchair_accessible": True}},
            cost=995.0,
        )
    )

    assert agent._event_is_ready({"trigger_turn": 5, "affected_components": ["hotel"]}) is True


def test_return_flight_booking_accepts_actual_route_cities():
    tool = FlightSearchTool("benchmarks/mock_data/flights.json")

    result = tool.book(
        flight_id="flight_SAN_DEN_001",
        outbound=False,
        origin_city="San Diego",
        destination_city="Denver",
        departure_date="2026-07-20",
        party_size=4,
    )

    assert result["status"] == "success"
    assert result["details"]["type"] == "return_flight"
    assert result["details"]["origin_city"] == "San Diego"
    assert result["details"]["destination_city"] == "Denver"


def test_budget_reduced_event_updates_live_budget_cap():
    agent = make_agent()

    class FakeHotelTool:
        def cancel(self, booking_id):
            return {"status": "success", "cancellation_id": f"cancel_{booking_id}"}

    agent.hotel_tool = FakeHotelTool()
    agent.turn_count = 5
    agent.tracker.add_constraint("budget_max", 2200, is_hard=True)
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"hotel_name": "French Quarter Grand Hotel", "check_in": "2026-11-06", "check_out": "2026-11-08", "nights": 2},
            cost=538.0,
        )
    )

    agent._handle_dynamic_event(
        {
            "event_type": "budget_reduced",
            "description": (
                "You decide to set aside $500 from your trip budget to purchase a piece "
                "of local art you just saw online. Your new maximum budget for the trip "
                "booking is now $1700 instead of $2200."
            ),
            "affected_components": ["hotel", "restaurants"],
            "resolution_requirements": ["Stay under $1700"],
        },
        "CURRENT ITINERARY",
        {"success_criteria": {"total_cost_max": 1700}},
    )

    assert agent.tracker.budget_max == 1700
    assert agent._operation_log[0]["summary"] == "updated budget cap to $1700 due to budget_reduced"


def test_trip_cut_short_event_matches_only_the_shortened_part_of_the_trip():
    agent = make_agent()

    class FakeHotelTool:
        def __init__(self):
            self.cancelled = []

        def cancel(self, booking_id):
            self.cancelled.append(booking_id)
            return {"status": "success", "cancellation_id": f"cancel_{booking_id}"}

    agent.hotel_tool = FakeHotelTool()
    agent.turn_count = 5
    agent.tracker.add_constraint("departure_date", "2026-03-05", is_hard=True)
    agent.tracker.add_constraint("return_date", "2026-03-08", is_hard=True)
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_out",
            type="flight",
            details={"type": "outbound_flight", "departure_date": "2026-03-05", "departure_time": "07:00"},
            cost=89.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_ret",
            type="flight",
            details={"type": "return_flight", "departure_date": "2026-03-08", "departure_time": "16:30"},
            cost=119.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"hotel_name": "Vegas Convention Center Hotel", "check_in": "2026-03-05", "check_out": "2026-03-07", "nights": 2},
            cost=258.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            details={"name": "Silicon Desert Steakhouse", "date": "2026-03-06", "time": "19:00"},
            cost=120.0,
        )
    )

    agent._handle_dynamic_event(
        {
            "event_type": "trip_cut_short",
            "description": "You must change your return flight to depart Las Vegas no later than Saturday (2026-03-07) at 1:00 PM. You also need to cancel your Saturday night hotel stay and any weekend entertainment you had planned.",
            "affected_components": ["return_flight", "saturday_hotel", "saturday_activities", "sunday_activities"],
            "resolution_requirements": ["Return before Saturday afternoon"],
        },
        "CURRENT ITINERARY",
        {},
    )

    event_state = agent._triggered_events[0]

    assert "bk_flight_ret" in event_state["affected_booking_ids"]
    assert "bk_hotel_1" not in event_state["affected_booking_ids"]
    assert "bk_hotel_1" in event_state["dependent_booking_ids"]
    assert agent.hotel_tool.cancelled == []
    assert agent.tracker.get_booking("bk_hotel_1") is not None


def test_trip_cut_short_success_criteria_accept_valid_unchanged_dependents():
    agent = make_agent()
    agent._scenario = {"origin_city": "San Jose", "destination_cities": ["Las Vegas"]}
    agent._success_criteria = {
        "total_cost_max": 2000,
        "timing_feasible": True,
        "early_return_executed": True,
        "unaffected_bookings_preserved": True,
        "dependent_bookings_updated": True,
    }

    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_out",
            type="flight",
            details={"type": "outbound_flight", "departure_date": "2026-03-05", "departure_time": "07:00"},
            cost=89.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_ret",
            type="flight",
            details={"type": "return_flight", "departure_date": "2026-03-07", "departure_time": "09:00"},
            cost=89.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            details={"hotel_name": "Vegas Convention Center Hotel", "check_in": "2026-03-05", "check_out": "2026-03-07", "nights": 2},
            cost=258.0,
        )
    )
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            details={"name": "Silicon Desert Steakhouse", "date": "2026-03-06", "time": "19:00"},
            cost=120.0,
        )
    )

    event_state = {
        "turn": 5,
        "event_type": "trip_cut_short",
        "description": "You must change your return flight to depart Las Vegas no later than Saturday (2026-03-07) at 1:00 PM. You also need to cancel your Saturday night hotel stay and any weekend entertainment you had planned.",
        "affected_components": ["return_flight", "saturday_hotel", "saturday_activities", "sunday_activities"],
        "affected_booking_ids": ["bk_flight_ret"],
        "dependent_booking_ids": ["bk_hotel_1", "bk_rest_1"],
        "preserved_booking_ids": ["bk_flight_out"],
        "removed_booking_ids": [],
    }
    agent._triggered_events = [event_state]

    assert agent._event_resolved(event_state) is True
    assert agent._dependent_bookings_reviewed(event_state) is True
    assert agent._success_criteria_satisfied() is True
