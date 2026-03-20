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
        pass
    
    def search(
        self,
        city: str,
        max_price: int = None,
        wheelchair_accessible: bool = None
    ) -> list:
        """
        Search for hotels matching criteria
        
        Args:
            city: City name (e.g., "Denver")
            max_price: Maximum price per night (optional)
            wheelchair_accessible: Filter for accessibility (optional)
        
        Returns:
            List of hotel dicts (up to 5 results, sorted by price)
            
        Example return:
        [
            {
                "hotel_id": "HTL0001",
                "name": "Budget Inn Denver",
                "city": "Denver",
                "price_per_night": 70,
                "wheelchair_accessible": False,
                "amenities": ["wifi"],
                "check_in_time": "15:00",
                "check_out_time": "11:00",
                "rating": 3.0,
                "distance_to_downtown": "15min",
                "has_parking": False
            },
            ...
        ]
        """
        pass
 