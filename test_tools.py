from pathlib import Path

from src.tools.flights import FlightSearchTool
from src.tools.hotels import HotelSearchTool


PROJECT_ROOT = Path(__file__).resolve().parent
MOCK_DATA_DIR = PROJECT_ROOT / "benchmarks" / "mock_data"


def test_flight_search_returns_results_for_known_route():
    tool = FlightSearchTool(str(MOCK_DATA_DIR / "flights.json"))

    results = tool.search("Chicago", "New York", "2026-07-15")

    assert results["outbound_flights"]
    assert all(flight["from_city"] == "Chicago" for flight in results["outbound_flights"])
    assert all(flight["to_city"] == "New York" for flight in results["outbound_flights"])


def test_hotel_search_filters_city_and_accessibility():
    tool = HotelSearchTool(str(MOCK_DATA_DIR / "hotels.json"))

    results = tool.search("Chicago", max_price=250, wheelchair_accessible=True)

    assert results
    assert all(hotel["city"] == "Chicago" for hotel in results)
    assert all(hotel["price_per_night"] <= 250 for hotel in results)
    assert all(hotel["wheelchair_accessible"] is True for hotel in results)
