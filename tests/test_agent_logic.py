from src.agent import TravelAgent
from src.core.constraints import ConstraintTracker
from src.utils.types import Booking


def make_agent():
    agent = TravelAgent.__new__(TravelAgent)
    agent.tracker = ConstraintTracker()
    agent._searched = set()
    agent._required_components = []
    agent.conversation_history = []
    return agent


def test_split_params_preserves_list_literals():
    agent = make_agent()

    parts = agent._split_params('interests=["live music", "food"], city="Chicago", max_price=50')

    assert parts == ['interests=["live music", "food"]', 'city="Chicago"', "max_price=50"]


def test_process_tool_params_converts_basic_types():
    agent = make_agent()

    processed = agent._process_tool_params({
        "party_size": "2",
        "max_price": "49.5",
        "wheelchair_accessible": "true",
        "interests": '["beach", "food"]',
        "city": '"San Diego"',
    })

    assert processed == {
        "party_size": 2,
        "max_price": 49.5,
        "wheelchair_accessible": True,
        "interests": ["beach", "food"],
        "city": "San Diego",
    }


def test_trim_result_removes_full_data_from_booking_details():
    agent = make_agent()

    trimmed = agent._trim_result(
        {
            "status": "success",
            "booking_id": "bk_hotel_1",
            "details": {
                "hotel_id": "hotel_1",
                "hotel_name": "Test Hotel",
                "full_data": {"large": "payload"},
            },
        },
        "book",
    )

    assert trimmed == {
        "status": "success",
        "booking_id": "bk_hotel_1",
        "details": {
            "hotel_id": "hotel_1",
            "hotel_name": "Test Hotel",
        },
    }


def test_trim_result_caps_and_filters_search_results():
    agent = make_agent()

    trimmed = agent._trim_result(
        [
            {
                "hotel_id": "hotel_1",
                "name": "Hotel One",
                "city": "Chicago",
                "price_per_night": 100,
                "stars": 4,
                "full_data": {"ignored": True},
            },
            {
                "hotel_id": "hotel_2",
                "name": "Hotel Two",
                "city": "Chicago",
                "price_per_night": 120,
                "neighborhood": "Loop",
                "other": "ignored",
            },
        ],
        "search",
    )

    assert trimmed == [
        {
            "hotel_id": "hotel_1",
            "name": "Hotel One",
            "city": "Chicago",
            "price_per_night": 100,
            "stars": 4,
        },
        {
            "hotel_id": "hotel_2",
            "name": "Hotel Two",
            "city": "Chicago",
            "price_per_night": 120,
            "neighborhood": "Loop",
        },
    ]


def test_build_confirmed_bookings_text_uses_tracker_state():
    agent = make_agent()
    agent.tracker.add_constraint("budget_max", 300, is_hard=True)
    agent.tracker.add_booking(
        Booking(
            booking_id="bk_flight_1",
            type="flight",
            details={"origin_city": "Detroit", "destination_city": "Chicago"},
            cost=99.0,
        )
    )

    text = agent._build_confirmed_bookings_text()

    assert "bk_flight_1" in text
    assert "Total confirmed spend: $99.0" in text
    assert "Budget limit: $300.0" in text
