from src.utils.types import Constraint
from src.agent import TravelAgent
from src.utils.types import Booking


class StubTracker:
    def __init__(self, bookings, budget_max=1000, hard_constraints=None):
        self.bookings = bookings
        self.budget_max = budget_max
        self.budget_used = sum(booking.cost for booking in bookings)
        self._hard_constraints = hard_constraints or []

    def get_bookings_by_type(self, booking_type):
        return [booking for booking in self.bookings if booking.type == booking_type]

    def get_remaining_budget(self):
        return self.budget_max - self.budget_used

    def get_hard_constraints(self):
        return self._hard_constraints


def make_agent(bookings=None, budget_max=1000, hard_constraints=None):
    agent = TravelAgent.__new__(TravelAgent)
    agent.tracker = StubTracker(bookings or [], budget_max=budget_max, hard_constraints=hard_constraints)
    agent._searched = set()
    agent._required_components = []
    agent._operation_log = []
    agent._soft_preferences = {}
    agent.metadata = {}
    agent.conversation_history = []
    agent.turn_count = 0
    return agent


def test_required_components_need_minimum_counts():
    agent = make_agent([
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            cost=40,
            details={"name": "Beach Grill", "full_data": {"tags": ["beach"]}},
        )
    ])

    agent._required_components = ["restaurants_min_2"]

    assert agent._component_satisfied("restaurants_min_2") is False
    assert agent._all_required_components_satisfied() is False


def test_required_components_accept_matching_bookings():
    agent = make_agent([
        Booking(
            booking_id="bk_hotel_1",
            type="hotel",
            cost=200,
            details={"nights": 2, "full_data": {"wheelchair_accessible": True}},
        ),
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            cost=40,
            details={"name": "Beach Grill", "full_data": {"tags": ["beach"], "is_wheelchair_accessible": True}},
        ),
        Booking(
            booking_id="bk_rest_2",
            type="restaurant",
            cost=45,
            details={"name": "Beach Cafe", "full_data": {"tags": ["beach"], "is_wheelchair_accessible": True}},
        ),
        Booking(
            booking_id="bk_act_1",
            type="activity",
            cost=25,
            details={"name": "Beach Walk", "full_data": {"tags": ["beach"], "category": ["outdoor"]}},
        ),
        Booking(
            booking_id="bk_flight_out",
            type="flight",
            cost=99,
            details={"type": "Outbound_flight", "origin_city": "Detroit", "destination_city": "Chicago", "departure_time": "08:00"},
        ),
        Booking(
            booking_id="bk_flight_ret",
            type="flight",
            cost=120,
            details={"type": "Return_flight", "origin_city": "Chicago", "destination_city": "Detroit", "departure_time": "18:30"},
        ),
    ])

    agent._required_components = [
        "hotel_2_nights",
        "restaurants_min_2",
        "beach_activities_min_1",
        "accessible_restaurants_min_2",
        "outbound_flight",
        "return_flight_after_17:00",
    ]

    assert agent._all_required_components_satisfied() is True


def test_extract_tool_error_supports_status_error_payloads():
    agent = make_agent()

    assert agent._extract_tool_error({"status": "error", "message": "No results found"}) == "No results found"
    assert agent._extract_tool_error({"error": "Boom"}) == "Boom"
    assert agent._extract_tool_error({"status": "success"}) == ""


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


def test_requirement_status_text_reports_unmet_components():
    agent = make_agent([
        Booking(
            booking_id="bk_act_1",
            type="activity",
            cost=25,
            details={"name": "Beach Walk", "full_data": {"tags": ["beach"], "category": ["outdoor"]}},
        )
    ])
    agent._required_components = ["beach_activities_min_2"]

    assert agent._build_requirement_status_text() == (
        "- beach_activities_min_2: UNMET (matched 1 / required 2)"
    )


def test_record_operation_and_operation_log_text():
    agent = make_agent()
    agent.turn_count = 5

    agent._record_operation(
        "book_hotel",
        "book",
        {"booking_id": "bk_hotel_SAN_001_20260715"},
        {"hotel_id": "hotel_SAN_001"},
    )
    agent._record_operation(
        "cancel_hotel",
        "cancel",
        {"status": "success"},
        {"booking_id": "bk_hotel_SAN_001_20260715"},
    )

    assert agent._build_operation_log_text() == "\n".join([
        "- turn 5: book book_hotel -> confirmed bk_hotel_SAN_001_20260715",
        "- turn 5: cancel cancel_hotel -> cancelled bk_hotel_SAN_001_20260715",
    ])


def test_booking_order_blocks_activity_before_required_hotel():
    agent = make_agent()
    agent._required_components = ["hotel_2_nights", "beach_activities_min_2"]

    assert agent._validate_booking_order("search_activities", "search") == (
        "Booking order violation: complete required lodging before activities or restaurants."
    )


def test_remaining_required_categories_are_task_aware():
    agent = make_agent()
    agent._required_components = ["hotel_2_nights"]

    assert agent._remaining_required_categories() == ["required lodging"]


def test_hard_constraints_satisfied_checks_budget_and_accessibility():
    hard_constraints = [
        Constraint(name="budget_max", value=100, is_hard=True),
        Constraint(name="wheelchair_accessible", value=True, is_hard=True),
    ]
    agent = make_agent([
        Booking(
            booking_id="bk_rest_1",
            type="restaurant",
            cost=120,
            details={"name": "Cafe", "full_data": {"is_wheelchair_accessible": False}},
        )
    ], budget_max=100, hard_constraints=hard_constraints)

    assert agent._hard_constraints_satisfied() is False
