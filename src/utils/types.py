"""
src/utils/types.py - Pydantic Data Models
These models define the structure of data used throughout the agent.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class Constraint(BaseModel):
    """Represents a single constraint (hard or soft)"""
    name: str = Field(..., description="Constraint name (e.g., 'budget_max', 'wheelchair_accessible')")
    value: Any = Field(..., description="Constraint value")
    is_hard: bool = Field(True, description="True = must satisfy, False = preference")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "budget_max",
                "value": 1000,
                "is_hard": True
            }
        }


class Booking(BaseModel):
    """Represents a booking (flight, hotel, restaurant, activity)"""
    booking_id: str = Field(..., description="Unique identifier")
    type: str = Field(..., description="Type: 'flight', 'hotel', 'restaurant', 'activity'")
    details: Dict[str, Any] = Field(..., description="Actual booking details from tool")
    cost: float = Field(..., description="Cost in USD")
    dependencies: List[str] = Field(default_factory=list, description="IDs of bookings this depends on")
    
    class Config:
        json_schema_extra = {
            "example": {
                "booking_id": "flight_001",
                "type": "flight",
                "details": {
                    "flight_id": "FL0123",
                    "origin": "Chicago",
                    "destination": "Denver",
                    "departure_time": "10:00",
                    "price": 250
                },
                "cost": 250.0,
                "dependencies": []
            }
        }


class ConversationState(BaseModel):
    """Current state of the planning conversation"""
    constraints: List[Constraint] = Field(default_factory=list)
    bookings: List[Booking] = Field(default_factory=list)
    current_budget_used: float = Field(0.0)
    messages: List[Dict[str, str]] = Field(default_factory=list)
    turn_count: int = Field(0)
    
    def add_constraint(self, constraint: Constraint):
        """Add a constraint to the state"""
        self.constraints.append(constraint)
    
    def add_booking(self, booking: Booking):
        """Add a booking and update budget"""
        self.bookings.append(booking)
        self.current_budget_used += booking.cost
    
    def get_booking_by_id(self, booking_id: str) -> Optional[Booking]:
        """Find a booking by its ID"""
        for booking in self.bookings:
            if booking.booking_id == booking_id:
                return booking
        return None
    
    def remove_booking(self, booking_id: str):
        """Remove a booking and update budget"""
        booking = self.get_booking_by_id(booking_id)
        if booking:
            self.bookings.remove(booking)
            self.current_budget_used -= booking.cost


class Flight(BaseModel):
    """Flight data structure (matches mock data format)"""
    flight_id: str
    airline: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    duration_hours: float
    price: int
    distance_miles: int
    available_seats: int


class Hotel(BaseModel):
    """Hotel data structure (matches mock data format)"""
    hotel_id: str
    name: str
    city: str
    price_per_night: int
    wheelchair_accessible: bool
    amenities: List[str]
    check_in_time: str
    check_out_time: str
    rating: float
    distance_to_downtown: str
    has_parking: bool


class Restaurant(BaseModel):
    """Restaurant data structure (matches mock data format)"""
    restaurant_id: str
    name: str
    city: str
    cuisine: str
    avg_meal_cost: int
    wheelchair_accessible: bool
    rating: float
    price_range: str
    hours: Dict[str, str]
    reservations_recommended: bool
    outdoor_seating: bool


class Activity(BaseModel):
    """Activity data structure (matches mock data format)"""
    activity_id: str
    name: str
    city: str
    type: str
    cost: int
    duration_hours: int
    wheelchair_accessible: bool
    rating: float
    hours: str
    requires_booking: bool
    indoor: bool


# Type aliases for cleaner code
ConstraintList = List[Constraint]
BookingList = List[Booking]