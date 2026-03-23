import os
import json
from datetime import datetime

class FlightSearchTool:
    """
    Search for flights in mock data
    """
    
    def __init__(self, data_path: str):
        """
        Load flight data from JSON file
        
        Args:
            data_path: Path to flights.json
        """
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"Mock data not found at: {data_path}")

        with open(data_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            self.flights = raw_data['flights']
    
    def search(
        self,
        original_city: str,
        destination_city: str,
        departure_date: str,
        return_date: str = None,
        departure_time_earliest: str = None,
        return_time_latest: str = None,
        max_price: int = None,
        wheelchair_accessible: bool = None,
    ) -> dict:
        """
        Search for flights matching criteria
        
        Args:
            original_city: Original city name (e.g., "Chicago")
            destination_city: Destination city name (e.g., "New York")
            departure_date: Departure date (format: "YYYY"-"MM"-"DD"),
            return_date: Return date (format: "YYYY"-"MM"-"DD") (optional),
            departure_time_earliest: Earliest dparture time (e.g., "06:00") (optional),
            return_time_latest: Latest departure time (e.g., "18:00") (optional),
            max_price: int = Maximum price per seat (optional),
            wheelchair_accessible: bool = None (optional),
     
        Returns:
            Dict of outbound flight list and return flight list (up to 10 results, sorted by price)
            
        Example return:
        {
            "outbound_flights": [
                {
                    "flight_id": "flight_CHI_NYC_003",
                    "airline": "Delta",
                    "flight_number": "DL200",
                    "from_city": "Chicago",
                    "from_state": "IL",
                    "from_country": "USA",
                    "to_city": "New York",
                    "to_state": "NY",
                    "to_country": "USA",
                    "departure_time": "06:00",
                    "arrival_time": "10:00",
                    "duration_hours": 2.5,
                    "aircraft_type": "Airbus A350",
                    "stops": 0,
                    "price_per_seat": 159,
                    "baggage_allowance": 1,
                    "baggage_fee": 25,
                    "preferred_seat_selection_fee": 15,
                    "seats_available": 110,
                    "class": ["economy", "business"],
                    "amenities": ["wifi", "free_snacks", "seat_selection"],
                    "wheelchair_accessible": true,
                    "max_group_size": 9,
                    "days_available": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
                    "booking_required": true,
                    "advance_booking_days": 0,
                    "arrival_delay_minutes": 5,
                    "was_cancelled": false,
                    "distance_miles": 700,
                    "tags": ["domestic", "direct", "early_morning", "major_route", "business_friendly"]
                },
                ...
            ],
            "return_flights": []
        }
        """
        from_day_of_week = datetime.strptime(departure_date, "%Y-%m-%d").strftime("%A").lower() #transfer date to day of week

        to_day_of_week = None
        if return_date:
            to_day_of_week = datetime.strptime(return_date, "%Y-%m-%d").strftime("%A").lower()
        outbound_candidates = []
        return_candidates = []

        for flight in self.flights:
            if max_price is not None and max_price < flight['price_per_seat']:
                continue
            if wheelchair_accessible is True and flight['wheelchair_accessible'] != True:
                continue

            is_outbound = (
                original_city.lower() == flight['from_city'].lower() and 
                destination_city.lower() == flight['to_city'].lower()
            )
                
            if is_outbound:
                if from_day_of_week in flight['days_available']:
                    if departure_time_earliest is None or departure_time_earliest <= flight['departure_time']:
                        outbound_candidates.append(flight)
            
            if to_day_of_week:
                is_return = (
                    original_city.lower() == flight['to_city'].lower() and 
                    destination_city.lower() == flight['from_city'].lower()
                )
                    
                if is_return:
                    if to_day_of_week in flight['days_available']:
                        if return_time_latest is None or return_time_latest >= flight['departure_time']:
                            return_candidates.append(flight)


        outbound_candidates.sort(key=lambda x: x['price_per_seat'])   
        return_candidates.sort(key=lambda x: x['price_per_seat'])        

        return {
            "outbound_flights": outbound_candidates[:10],
            "return_flights": return_candidates[:10]
        }

    def book(
        self, 
        flight_id: str,
        outbound: bool,
        origin_city: str,
        destination_city: str,
        departure_date: str,
        party_size: int,
    ) -> dict:
        """
        Simulate booking a flight by interacting with a mock API.

        Args:
            flight_id: The unique identifier of the flight to book.
            outbound: True if outbound flight, otherwise, return flight.
            origin_city: Original city.
            destination_city: Destination city.
            departure_date: departure date in "YYYY-MM-DD" format.
            party_size: The number of guests. 

        Returns:
            dict: A dictionary containing the booking status.
                  - On success: Includes 'status': 'success', generated 'booking_id', 
                    total 'cost', and comprehensive booking 'details'.
                  - On error: Includes 'status': 'error' and an informative 'message'.
        """

        # find the target flight in the db
        selected_flight = None
        for flight in self.flights:
            if flight['flight_id'] == flight_id:
                selected_flight = flight
                break

        if not selected_flight:
            return {"status": "error", "message": f"Flight with ID '{flight_id}' not found."}
        

        # validate the origin city and destination city
        if outbound:
            if (origin_city.lower() != selected_flight['from_city'].lower() or 
                destination_city.lower() != selected_flight['to_city'].lower()):
                return {"status": "error", "message": f"Outbound flight original city or destination city not match."}
        else:
            if (origin_city.lower() != selected_flight['to_city'].lower() or 
                destination_city.lower() != selected_flight['from_city'].lower()):
                return {"status": "error", "message": f"Return flight original city or destination city not match."}

        
        # validate date format & availability
        try:
            day_of_week = datetime.strptime(departure_date, "%Y-%m-%d").strftime("%A").lower()
            if day_of_week not in selected_flight['days_available']:
                return {
                    "status": "error",
                    "message": f"Booking failed. This flight does not operate on {day_of_week.capitalize()}."
                }
        except ValueError:
            return {
                "status": "error",
                "message": "Invalid date format. Please use 'YYYY-MM-DD'."
            }
        
        # validate seats capacity
        if party_size > selected_flight['seats_available']:
            return {
                "status": "error",
                "message": f"Booking failed. Not enough seats available. Only {selected_flight['seats_available']} seats left."
            }

        if party_size > selected_flight['max_group_size']:
            return {
                "status": "error",
                "message": f"Booking failed. Party size ({party_size}) exceeds the maximum allowed per booking ({selected_flight['max_group_size']})."
            }
        
        # calculate total costs
        total_cost = selected_flight['price_per_seat'] * party_size
        
        return {
            "status": "success",
            "booking_id": f"bk_{flight_id}_{departure_date.replace('-', '')}",
            "cost": total_cost,
            "details": {
                "flight_id": flight_id,
                "type": "Outbound_flight" if outbound else "Return_flight",
                "flight_number": selected_flight['flight_number'],
                "origin_city": origin_city,
                "destination_city": destination_city,
                "departure_date": departure_date,
                "departure_time": selected_flight['departure_time'],
                "arrival_time": selected_flight['arrival_time'],
                "party_size": party_size,
                "full_data": selected_flight  
            }
        }

    def cancel(self, booking_id: str) -> dict:
        """
        Simulate canceling a flight booking by interacting with a mock API.

        Args:
            booking_id: The unique identifier for the booking to be canceled.

        Returns:
            dict: A dictionary containing the cancellation status.
                  - On success: Includes 'status': 'success' and a confirmation 'message'.
                  - On error: Includes 'status': 'error' and an informative 'message'.
        """
        if not booking_id or not isinstance(booking_id, str):
            return {"status": "error", "message": "Invalid booking ID provided."}

        # Basic validation of the booking ID format.
        # Example: bk_flight_CHI_NYC_003_20241025
        parts = booking_id.split('_')
        if len(parts) < 6 or parts[0] != 'bk' or parts[1] != 'flight':
            return {
                "status": "error",
                "message": f"Invalid flight booking ID format: '{booking_id}'."
            }

        # Since we don't have a database of bookings, we can't check if the booking
        # actually exists. We will simulate cancellation by checking if the flight
        # ID from the booking ID is valid.
        
        flight_id = "_".join(parts[1:-1]) # e.g., 'flight_CHI_NYC_003'
        
        flight_found = any(flight['flight_id'] == flight_id for flight in self.flights)

        if not flight_found:
            return {
                "status": "error",
                "message": f"Flight with ID '{flight_id}' from booking '{booking_id}' not found."
            }

        return {
            "status": "success",
            "cancellation_id": f"cancel_{booking_id}",
            "message": f"Booking '{booking_id}' has been successfully cancelled."
        }




 