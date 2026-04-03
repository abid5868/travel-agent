from src.tools.flights import FlightSearchTool
t = FlightSearchTool('benchmarks/mock_data/flights.json')
print(t.search('Chicago', 'New York', '2026-07-15'))


print('\n')

from src.tools.hotels import HotelSearchTool
t = HotelSearchTool('benchmarks/mock_data/hotels.json')
print(t.search('Chicago', max_price=200, wheelchair_accessible=True))