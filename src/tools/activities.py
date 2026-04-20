import os
import json
from datetime import datetime

class ActivitySearchTool:
    """
    Search for activities in mock data
    """
    
    def __init__(self, data_path: str):
        """
        Load activity data from JSON file
        
        Args:
            data_path: Path to activities.json
        """
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"Mock data not found at: {data_path}")

        with open(data_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            self.activities = raw_data['activities']
    
    def search(
        self,
        city: str,
        interests: list[str] = None,
        preferences: list[str] = None,
        max_price: int = None,
        party_size: int = None,
        target_date: str = None,
        start_time: str = None,
        wheelchair_accessible: bool = None
    ) -> list:
        """
        Search for activities matching criteria
        
        Args:
            city: City name (e.g., "Chicago")
            interests: User's interests keywords (optional)
            preferences: User's preferences (optional)
            max_price: Maximum price per person (optional)
            party_size: party size (optional)
            target_date: Activity targets date (optional)
            start_time: Activity starts time (optional)
            wheelchair_accessible: Filter for accessibility (optional)
        
        Returns:
            List of activities dicts (up to 10 results, sorted by price)
            
        Example return:
        [
            {
                "activity_id": "act_CHI_001",
                "name": "Chicago Architecture Foundation River Cruise",
                "city": "Chicago",
                "state": "IL",
                "country": "USA",
                "type": "architecture_tour",
                "category": ["architecture", "tour", "sightseeing", "guided"],
                "description": "90-minute guided boat tour narrating 50+ landmark buildings along the Chicago River. Covers skyscrapers, bridges, and the story of Chicago's post-fire rebuild.",
                "duration_hours": 1.5,
                "price_per_person": 49,
                "wheelchair_accessible": true,
                "family_friendly": true,
                "indoor": false,
                "min_group": 1,
                "max_group": 150,
                "operating_hours": {"open": "09:00", "close": "18:00"},
                "days_available": ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"],
                "booking_required": true,
                "advance_booking_days": 1,
                "location": {"address": "112 E Wacker Dr, Chicago, IL 60601", "neighborhood": "Riverwalk / Loop"},
                "tags": ["architecture_tour", "guided_tour", "river", "chicago", "outdoor", "sightseeing"]
            },
            ...
        ]
        """
        candidates = []
        user_interests_expanded = (interests or []) + (preferences or [])

        user_interests = set()
        if user_interests_expanded:
            for interest in user_interests_expanded:
                user_interests.update(self.helper(interest))
        
        day_of_week = None
        if target_date:
            day_of_week = datetime.strptime(target_date, "%Y-%m-%d").strftime("%A").lower()
        
        for activity in self.activities:
            if city.lower() != activity['city'].lower():
                continue
                
            if max_price is not None and max_price < activity['price_per_person']:
                continue

            if party_size:
                if party_size < activity['min_group'] or party_size > activity['max_group']:
                    continue
            
            if wheelchair_accessible is True and activity['wheelchair_accessible'] != True:
                continue

            if day_of_week:
                if day_of_week not in activity['days_available']:
                    continue
            
            if start_time:
                open_time = activity['operating_hours']['open']
                close_time = activity['operating_hours']['close']
                if open_time < close_time:
                    if start_time > close_time or start_time < open_time:
                        continue
                else: # (20:00 ~ 02:00)
                    if start_time < open_time and start_time > close_time:
                        continue
            
            if user_interests:

                keywords = set()
                keywords.update(self.helper(activity['type']))
                for category in activity['category']:
                    keywords.update(self.helper(category))
                
                for tag in activity['tags']:
                    keywords.update(self.helper(tag))
                
                if not user_interests.intersection(keywords):
                    continue

            candidates.append(activity)
        
        candidates.sort(key=lambda x: x['price_per_person'])        

        return candidates[:10]
    
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
        activity_id: str,
        date: str,
        time: str,
        party_size: int,
    ) -> dict:
        """
        Simulate booking an activity by interacting with a mock API.

        Args:
            activity_id: The unique identifier of the activity to book.
            date: The date of the activity to book.
            time: The time of the activity to book.
            party_size: The number of guests. 

        Returns:
            dict: A dictionary containing the booking status.
                  - On success: Includes 'status': 'success', generated 'booking_id', 
                    total 'cost', and comprehensive booking 'details'.
                  - On error: Includes 'status': 'error' and an informative 'message'.
        """

        # find the target activity in the db
        selected_activity = None
        for activity in self.activities:
            if activity['activity_id'] == activity_id:
                selected_activity = activity
                break

        if not selected_activity:
            return {"status": "error", "message": f"Activity with ID '{activity_id}' not found."}
        
        # validate date format & availability
        try:
            day_of_week = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()
            if day_of_week not in selected_activity['days_available']:
                return {
                    "status": "error",
                    "message": f"Booking failed. This activity does not operate on {day_of_week.capitalize()}."
                }
        except ValueError:
            return {
                "status": "error",
                "message": "Invalid date format. Please use 'YYYY-MM-DD'."
            }
        
        # validate time format & availabitiy
        try:
            datetime.strptime(time, "%H:%M")
            open_time = selected_activity['operating_hours']['open']
            close_time = selected_activity['operating_hours']['close']

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
        if party_size > selected_activity['max_group'] or party_size < selected_activity['min_group']:
            return {
                "status": "error",
                "message": f"Booking failed. Party size ({party_size}) does not meet the required party size of the activity."
            }
        
        # calculate total costs
        total_cost = selected_activity['price_per_person'] * party_size
        
        return {
            "status": "success",
            "booking_id": f"bk_{activity_id}_{date.replace('-', '')}t{time.replace(':', '')}",
            "cost": total_cost,
            "details": {
                "activity_id": activity_id,
                "name": selected_activity['name'],
                "date": date,
                "time": time,
                "party_size": party_size,
                "full_data": selected_activity  
            }
        }

    def cancel(self, booking_id: str) -> dict:
        """
        Simulate canceling an activity booking by interacting with a mock API.

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
        # Example: bk_act_CHI_001_20241025
        parts = booking_id.split('_')
        if len(parts) < 5 or parts[0] != 'bk' or parts[1] != 'act':
            return {
                "status": "error",
                "message": f"Invalid activity booking ID format: '{booking_id}'."
            }

        # Since we don't have a database of bookings, we can't check if the booking
        # actually exists. We will simulate cancellation by checking if the activity
        # ID from the booking ID is valid.
        
        activity_id = "_".join(parts[1:-1]) # e.g., 'act_CHI_001'
        
        activity_found = any(act['activity_id'] == activity_id for act in self.activities)

        if not activity_found:
            return {
                "status": "error",
                "message": f"Activity with ID '{activity_id}' from booking '{booking_id}' not found."
            }

        return {
            "status": "success",
            "cancellation_id": f"cancel_{booking_id}",
            "message": f"Booking '{booking_id}' has been successfully cancelled."
        }




 
