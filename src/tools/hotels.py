import os
import json
from datetime import datetime

class HotelSearchTool:
    """
    Search for hotels in mock data
    """
    
    def __init__(self, data_path: str):
        """
        Load hotel data from JSON file
        
        Args:
            data_path: Path to hotels.json
        """
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"Mock data not found at: {data_path}")

        with open(data_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            self.hotels = raw_data['hotels']
    
    def search(
        self,
        city: str,
        max_price: int = None,
        wheelchair_accessible: bool = None
    ) -> list:
        """
        Search for hotels matching criteria
        
        Args:
            city: City name (e.g., "Chicago")
            max_price: Maximum price per night (optional)
            wheelchair_accessible: Filter for accessibility (optional)
        
        Returns:
            List of hotel dicts (up to 10 results, sorted by price)
            
        Example return:
        [
            {
                "hotel_id": "hotel_CHI_001",
                "name": "The Riverwalk Grand Hotel",
                "city": "Chicago",
                "state": "IL",
                "country": "USA",
                "address": "225 N Michigan Ave, Chicago, IL 60601",
                "stars": 4,
                "price_per_night": 229,
                "amenities": ["wifi", "gym", "restaurant", "bar", "concierge", "business_center"],
                "wheelchair_accessible": true,
                "room_types": [
                    {"type": "standard_king", "capacity": 2, "price_per_night": 229},
                    {"type": "lake_view_queen", "capacity": 2, "price_per_night": 279},
                    {"type": "family_suite", "capacity": 4, "price_per_night": 429}
                ],
                "max_guests": 4,
                "neighborhood": "Millennium Park / Loop",
                "tags": ["lake_view", "business_friendly", "walkable", "near_museums"],
                "proximity_to_attractions": {
                    "millennium_park": "0.2 miles",
                    "art_institute": "0.3 miles",
                    "navy_pier": "0.8 miles",
                    "lake_michigan": "0.4 miles"
                }
            },
            ...
        ]
        """
        candidates = []
        for hotel in self.hotels:
            if city.lower() != hotel['city'].lower():
                continue
                
            if max_price is not None and max_price < hotel['price_per_night']:
                continue
            
            if wheelchair_accessible is True and hotel['wheelchair_accessible'] != True:
                continue

            candidates.append(hotel)
        
        candidates.sort(key=lambda x: x['price_per_night'])        

        return candidates[:10]

    def book(
        self, 
        hotel_id: str,
        check_in: str,
        check_out: str,
        party_size: int,
        num_rooms: int = 1
    ) -> dict:
        """
        Simulate booking a hotel by interacting with a mock API.

        Args:
            hotel_id: The unique identifier of the hotel to book.
            check_in: The check-in date in "YYYY-MM-DD" format.
            check_out: The check-out date in "YYYY-MM-DD" format.
            party_size: The number of guests.
            num_rooms: The number of rooms required per night. (optional)

        Returns:
            dict: A dictionary containing the booking status.
                  - On success: Includes 'status': 'success', generated 'booking_id', 
                    total 'cost', and comprehensive booking 'details'.
                  - On error: Includes 'status': 'error' and an informative 'message'.
        """

        # find the target hotel in the db
        selected_hotel = None
        for hotel in self.hotels:
            if hotel['hotel_id'] == hotel_id:
                selected_hotel = hotel
                break

        if not selected_hotel:
            return {"status": "error", "message": f"Hotel with ID '{hotel_id}' not found."}
        

        # validate if the total rooms capacity is enough
        total_capacity = selected_hotel.get('max_guests', 2) * num_rooms
        if party_size > total_capacity:
            return {
                "status": "error",
                "message": f"Booking failed. You need more rooms. {num_rooms} room(s) can only hold {total_capacity} guests, but party size is {party_size}."
            }
        
        # calculate nights
        try:
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d").date()
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d").date()
            nights = (check_out_date - check_in_date).days
            
            if nights <= 0:
                return {
                    "status": "error",
                    "message": "Check out date must be after the check in date."
                }
        except ValueError:
            return {
                "status": "error",
                "message": "Invalid date format. Please use 'YYYY-MM-DD'."
            }
        
        # calculate total costs
        total_cost = selected_hotel['price_per_night'] * nights * num_rooms
        
        return {
            "status": "success",
            "booking_id": f"bk_{hotel_id}_{check_in.replace('-', '')}",
            "cost": total_cost,
            "details": {
                "hotel_id": hotel_id,
                "hotel_name": selected_hotel['name'],
                "check_in": check_in,
                "check_out": check_out,
                "nights": nights,
                "party_size": party_size,
                "num_rooms": num_rooms,
                "full_data": selected_hotel  
            }
        }

    def cancel(self, booking_id: str) -> dict:
        """
        Simulate canceling a hotel booking by interacting with a mock API.

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
        # Example: bk_hotel_CHI_001_20241025
        parts = booking_id.split('_')
        if len(parts) < 5 or parts[0] != 'bk' or parts[1] != 'hotel':
            return {
                "status": "error",
                "message": f"Invalid hotel booking ID format: '{booking_id}'."
            }

        # Since we don't have a database of bookings, we can't check if the booking
        # actually exists. We will simulate cancellation by checking if the hotel
        # ID from the booking ID is valid.
        
        hotel_id = "_".join(parts[1:-1]) # e.g., 'hotel_CHI_001'
        
        hotel_found = any(hotel['hotel_id'] == hotel_id for hotel in self.hotels)

        if not hotel_found:
            return {
                "status": "error",
                "message": f"Hotel with ID '{hotel_id}' from booking '{booking_id}' not found."
            }

        return {
            "status": "success",
            "cancellation_id": f"cancel_{booking_id}",
            "message": f"Booking '{booking_id}' has been successfully cancelled."
        }



 