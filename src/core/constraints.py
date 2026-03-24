from typing import List, Dict, Any, Optional
from src.utils.types import Constraint, Booking


class ConstraintTracker:
    """
    Tracks constraints, bookings, budget, and dependencies
    """
    
    def __init__(self):
        """
        Initialize empty tracker
        
        Internal state to maintain:
        - self.constraints: List[Constraint]
        - self.bookings: List[Booking]
        - self.budget_max: Optional[float]
        - self.budget_used: float
        - self.dependency_graph: Dict[str, List[str]]
        """
        pass
    
    # ========== CONSTRAINT MANAGEMENT ==========
    
    def add_constraint(self, name: str, value: Any, is_hard: bool = True):
        """
        Add a constraint
        
        Args:
            name: Constraint name (e.g., "budget_max", "wheelchair_accessible")
            value: Constraint value
            is_hard: True = must satisfy, False = preference
            
        Example:
            tracker.add_constraint("budget_max", 1000, is_hard=True)
            tracker.add_constraint("interests", ["hiking"], is_hard=False)
        """
        pass
    
    def get_constraint(self, name: str) -> Optional[Constraint]:
        """
        Get a constraint by name
        
        Returns:
            Constraint object or None if not found
        """
        pass
    
    def get_hard_constraints(self) -> List[Constraint]:
        """
        Get all hard constraints
        
        Returns:
            List of constraints where is_hard=True
        """
        pass
    
    def get_soft_constraints(self) -> List[Constraint]:
        """
        Get all soft preferences
        
        Returns:
            List of constraints where is_hard=False
        """
        pass
    
    # ========== BOOKING MANAGEMENT ==========
    
    def add_booking(self, booking: Booking):
        """
        Add a booking and update budget
        
        Args:
            booking: Booking object with cost
            
        Side effects:
            - Adds booking to self.bookings
            - Updates self.budget_used
            - Registers dependencies in graph
            
        Example:
            flight = Booking(
                booking_id="flight_001",
                type="flight",
                details={"origin": "Chicago", "destination": "Denver"},
                cost=300.0,
                dependencies=[]
            )
            tracker.add_booking(flight)
        """
        pass
    
    def get_booking(self, booking_id: str) -> Optional[Booking]:
        """
        Get a booking by ID
        
        Returns:
            Booking object or None if not found
        """
        pass
    
    def remove_booking(self, booking_id: str):
        """
        Remove a booking and update budget
        
        Args:
            booking_id: ID of booking to remove
            
        Side effects:
            - Removes booking from self.bookings
            - Updates self.budget_used
            - Cleans up dependency graph
        """
        pass
    
    def update_booking(self, booking_id: str, new_booking: Booking):
        """
        Update an existing booking (for replanning)
        
        Args:
            booking_id: ID of booking to update
            new_booking: New booking details
            
        Side effects:
            - Updates budget (subtract old, add new)
            - Replaces booking in list
        """
        pass
    
    def get_bookings_by_type(self, booking_type: str) -> List[Booking]:
        """
        Get all bookings of a specific type
        
        Args:
            booking_type: "flight", "hotel", "restaurant", "activity"
            
        Returns:
            List of matching bookings
            
        Example:
            flights = tracker.get_bookings_by_type("flight")
        """
        pass
    
    # ========== BUDGET TRACKING ==========
    
    def get_remaining_budget(self) -> float:
        """
        Get remaining budget
        
        Returns:
            budget_max - budget_used, or inf if no budget limit
        """
        pass
    
    def is_within_budget(self, additional_cost: float = 0.0) -> bool:
        """
        Check if within budget
        
        Args:
            additional_cost: Optional cost to check before adding
            
        Returns:
            True if (budget_used + additional_cost) <= budget_max
            
        Example:
            if tracker.is_within_budget(250):
                # Can afford this $250 booking
        """
        pass
    
    # ========== DEPENDENCY TRACKING ==========
    
    def add_dependency(self, booking_id: str, depends_on: str):
        """
        Add a dependency relationship
        
        Args:
            booking_id: The booking that depends on something
            depends_on: The booking it depends on
            
        Example:
            tracker.add_dependency("hotel_001", "flight_001")
            # Hotel check-in depends on flight arrival
        """
        pass
    
    def find_dependent_bookings(self, booking_id: str) -> List[str]:
        """
        Find direct dependencies (one level)
        
        Args:
            booking_id: ID of the booking
            
        Returns:
            List of booking IDs that depend on this one
            
        Example:
            deps = tracker.find_dependent_bookings("flight_001")
            # Returns ["hotel_001", "restaurant_001"]
        """
        pass
    
    def find_all_affected_bookings(self, booking_id: str) -> List[str]:
        """
        Find ALL affected bookings recursively (transitive dependencies)
        
        This is CRITICAL for replanning!
        
        Args:
            booking_id: ID of the changed booking
            
        Returns:
            List of ALL affected booking IDs (including chains)
            
        Example:
            # If flight_001 changes:
            # flight_001 -> hotel_001 -> restaurant_001 -> activity_001
            affected = tracker.find_all_affected_bookings("flight_001")
            # Returns ["hotel_001", "restaurant_001", "activity_001"]
        """
        pass
 
 
# ============================================================================
# USAGE EXAMPLE
# ============================================================================
 
"""
# Find dependencies (for replanning)
if flight_cancels:
    affected = tracker.find_all_affected_bookings("flight_001")
    print(f"Need to replan: {affected}")  # ["hotel_001", ...]
"""