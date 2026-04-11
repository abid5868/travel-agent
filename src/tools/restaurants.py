import os
import json
from datetime import datetime

class RestaurantSearchTool:
    """
    Search for restaurants in mock data
    """
    
    def __init__(self, data_path: str):
        """
        Load restaurant data from JSON file
        
        Args:
            data_path: Path to restaurants.json
        """
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"Mock data not found at: {data_path}")

        with open(data_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            self.restaurants = raw_data['restaurants']
    
    def search(
        self,
        city: str,
        special_needs: list[str] = None,
        interests: list[str] = None,
        preferences: list[str] = None,
        max_price: int = None,
        party_size: int = None,
        target_date: str = None,
        start_time: str = None,
        wheelchair_accessible: bool = None
    ) -> list:
        """
        Search for restaurants matching criteria
        
        Args:
            city: City name (e.g., "Chicago")
            special_needs: User's special needs (optional)
            intereste: User's interests keywords (optional)
            preferences: User's preferences
            max_price: Maximum price per person (optional)
            party_size: party size (optional)
            target_date: Activity targets date (optional)
            start_time: Activity starts time (optional)
            wheelchair_accessible: Filter for accessibility (optional)
        
        Returns:
            List of restaurants dicts (up to 10 results, sorted by price)
            
        Example return:
        [
            {
            "restaurant_id": "rest_001",
            "name": "Windy City Blues & Bites",
            "city": "Chicago",
            "state": "IL",
            "country": "USA",
            "coordinates": {
                "latitude": 41.8901,
                "longitude": -87.6300
            },
            "price_level": "$",
            "average_cost_per_person": 18,
            "max_group_size": 20,
            "meal_type": [
                "dinner",
                "late_night"
            ],
            "opening_hours": {
                "Monday": "Closed",
                "Tuesday": "17:00-01:00",
                "Wednesday": "17:00-01:00",
                "Thursday": "17:00-01:00",
                "Friday": "17:00-02:00",
                "Saturday": "17:00-02:00",
                "Sunday": "17:00-00:00"
            },
            "is_wheelchair_accessible": true,
            "dietary_options": [],
            "tags": [
                "live_music",
                "local_food_scene",
                "walkable"
            ]
            },
            ...
        ]
        """
        candidates = []
        user_interests_expanded = (interests or []) + (preferences or []) + (special_needs or [])
        user_interests = set()

        if user_interests_expanded:
            for interest in user_interests_expanded:
                user_interests.update(self.helper(interest))
        
        day_of_week = None
        if target_date:
            day_of_week = datetime.strptime(target_date, "%Y-%m-%d").strftime("%A").lower()
        
        for r in self.restaurants:
            if city.lower() != r['city'].lower():
                continue

            if party_size is not None and party_size > r['max_group_size']:
                continue
                
            if max_price is not None and max_price < r['average_cost_per_person']:
                continue
            
            if wheelchair_accessible is True and r['is_wheelchair_accessible'] != True:
                continue
            
            # fix for strictly filtering by special needs
            if special_needs:
                rest_dietary_keywords = set()
                for opt in r.get('dietary_options', []):
                    rest_dietary_keywords.update(self.helper(opt))
                
                is_safe = True
                for need in special_needs:
                    need_lower = need.lower()
                    
                    
                    if "wheelchair" in need_lower or "mobility" in need_lower:
                        if r.get('is_wheelchair_accessible') != True:
                            is_safe = False
                            break  
                        continue
                        
        
                    need_keywords = self.helper(need)
                    if not need_keywords.intersection(rest_dietary_keywords):
                        is_safe = False
                        break  
    
                if not is_safe:
                    continue

            if day_of_week:
                day_key = day_of_week.capitalize()
                op_hours = r['opening_hours'].get(day_key, "Closed")

                if op_hours == "Closed":
                    continue
        
                if start_time:
                    open_time, close_time = op_hours.split("-")
                    if open_time < close_time:
                        if start_time > close_time or start_time < open_time:
                            continue
                    else: # (20:00 ~ 02:00)
                        if start_time < open_time and start_time > close_time:
                            continue

            match_score = 0
            if user_interests:
                keywords = set()
                for m_type in r['meal_type']:
                    keywords.update(self.helper(m_type))
                for dietary_option in r['dietary_options']:
                    keywords.update(self.helper(dietary_option))
                for tag in r['tags']:
                    keywords.update(self.helper(tag))
                match_score = len(user_interests.intersection(keywords))

            candidates.append((match_score, r))
        
        candidates.sort(key=lambda item: (-item[0], item[1]['average_cost_per_person']))

        return [restaurant for _, restaurant in candidates[:10]]
    
    @staticmethod
    def helper(word: str) -> set:
        """
        Normalize and expand a keyword into a set of related terms.
        e.g., "Architecture_Tour" -> {"architecture_tour", "architecture tour", "architecture", "tour"}
        """
        word = word.lower()
        res = set([word])

        word = word.replace("_", " ")
        res.add(word)

        res.update(word.split())

        return res
    
    def book(
        self, 
        restaurant_id: str,
        date: str,
        time: str,
        party_size: int,
    ) -> dict:
        """
        Simulate booking a restaurant by interacting with a mock API.

        Args:
            restaurant_id: The unique identifier of the restaurant to book.
            date: The date of the restaurant to book.
            time: The time of the restaurant to book.
            party_size: The number of guests. 

        Returns:
            dict: A dictionary containing the booking status.
                  - On success: Includes 'status': 'success', generated 'booking_id', 
                    total 'cost', and comprehensive booking 'details'.
                  - On error: Includes 'status': 'error' and an informative 'message'.
        """

        # find the target restaurant in the db
        selected_restaurant = None
        for restaurant in self.restaurants:
            if restaurant['restaurant_id'] == restaurant_id:
                selected_restaurant = restaurant
                break

        if not selected_restaurant:
            return {"status": "error", "message": f"Restaurant with ID '{restaurant_id}' not found."}
        
        
        # validate date format & availability
        try:
            day_of_week = datetime.strptime(date, "%Y-%m-%d").strftime("%A").capitalize()
            operating_hours = selected_restaurant['opening_hours'][day_of_week]
            if operating_hours == "Closed":
                return {
                    "status": "error",
                    "message": f"Booking failed. This restaurant does not operate on {day_of_week}."
                }
        except ValueError:
            return {
                "status": "error",
                "message": "Invalid date format. Please use 'YYYY-MM-DD'."
            }
        
        # validate time format & availabitiy
        try:
            datetime.strptime(time, "%H:%M")
            open_time, close_time = selected_restaurant['opening_hours'][day_of_week].split("-")
        
            is_open = False
            if open_time <= close_time:
                is_open = open_time <= time <= close_time
            else:
                is_open = time >= open_time or time <= close_time
            
            if not is_open:
                return {
                    "status": "error",
                    "message": f"Booking failed. The time {time} is outside operating hours ({open_time} - {close_time})."
                }
            
        except ValueError:
            return {
                "status": "error",
                "message": "Invalid time format. Please use 'HH:MM' (24-hour format)."
            }

        # validate seats capacity
        if party_size > selected_restaurant['max_group_size']:
            return {
                "status": "error",
                "message": f"Booking failed. Party size ({party_size}) exceeds the maximum capacity ({selected_restaurant['max_group_size']}) of the restaurant."
            }
        
        # calculate total costs
        total_cost = selected_restaurant['average_cost_per_person'] * party_size
        
        return {
            "status": "success",
            "booking_id": f"bk_{restaurant_id}_{date.replace('-', '')}",
            "cost": total_cost,
            "details": {
                "restaurant_id": restaurant_id,
                "name": selected_restaurant['name'],
                "date": date,
                "time": time,
                "party_size": party_size,
                "full_data": selected_restaurant
            }
        }

    def cancel(self, booking_id: str) -> dict:
        """
        Simulate canceling a restaurant booking by interacting with a mock API.

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
        # Example: bk_rest_001_20241025
        parts = booking_id.split('_')
        if len(parts) < 4 or parts[0] != 'bk' or parts[1] != 'rest':
            return {
                "status": "error",
                "message": f"Invalid restaurant booking ID format: '{booking_id}'."
            }

        # Since we don't have a database of bookings, we can't check if the booking
        # actually exists. We will simulate cancellation by checking if the restaurant
        # ID from the booking ID is valid.
        
        restaurant_id = "_".join(parts[1:-1]) # e.g., 'rest_001'
        
        restaurant_found = any(r['restaurant_id'] == restaurant_id for r in self.restaurants)

        if not restaurant_found:
            return {
                "status": "error",
                "message": f"Restaurant with ID '{restaurant_id}' from booking '{booking_id}' not found."
            }

        return {
            "status": "success",
            "cancellation_id": f"cancel_{booking_id}",
            "message": f"Booking '{booking_id}' has been successfully cancelled."
        }





 
