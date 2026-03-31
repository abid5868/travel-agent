from typing import List, Dict, Any, Optional
from src.utils.types import Constraint, Booking


class ConstraintTracker:
    """
    Tracks constraints, bookings, budget, and dependencies.

    This class is responsible for:
    - Storing hard and soft constraints
    - Managing bookings and their costs
    - Tracking budget usage and limits
    - Maintaining a dependency graph for bookings to support replanning
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
        self.constraints: List[Constraint] = []
        self.bookings: List[Booking] = []
        self.budget_max: Optional[float] = None
        self.budget_used: float = 0.0
        self.dependency_graph: Dict[str, List[str]] = {}  # booking_id -> list of dependent booking_ids
    
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
        constraint = Constraint(name=name, value=value, is_hard=is_hard)
        self.constraints.append(constraint)
        
        # Special handling for budget_max
        if name == "budget_max" and isinstance(value, (int, float)):
            self.budget_max = float(value)
    
    def get_constraint(self, name: str) -> Optional[Constraint]:
        """
        Get a constraint by name
        
        Returns:
            Constraint object or None if not found
        """
        for constraint in self.constraints:
            if constraint.name == name:
                return constraint
        return None
    
    def get_hard_constraints(self) -> List[Constraint]:
        """
        Get all hard constraints
        
        Returns:
            List of constraints where is_hard=True
        """
        return [c for c in self.constraints if c.is_hard]
    
    def get_soft_constraints(self) -> List[Constraint]:
        """
        Get all soft preferences
        
        Returns:
            List of constraints where is_hard=False
        """
        return [c for c in self.constraints if not c.is_hard]
    
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
        self.bookings.append(booking)
        self.budget_used += booking.cost
        
        # Initialize dependency graph entry for this booking
        if booking.booking_id not in self.dependency_graph:
            self.dependency_graph[booking.booking_id] = []
        
        # Register dependencies in graph
        for depends_on in booking.dependencies:
            if depends_on not in self.dependency_graph:
                self.dependency_graph[depends_on] = []
            if booking.booking_id not in self.dependency_graph[depends_on]:
                self.dependency_graph[depends_on].append(booking.booking_id)
    
    def get_booking(self, booking_id: str) -> Optional[Booking]:
        """
        Get a booking by ID
        
        Returns:
            Booking object or None if not found
        """
        for booking in self.bookings:
            if booking.booking_id == booking_id:
                return booking
        return None
    
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
        booking = self.get_booking(booking_id)
        if booking:
            self.bookings.remove(booking)
            self.budget_used -= booking.cost
            
            # Clean up dependency graph
            if booking_id in self.dependency_graph:
                del self.dependency_graph[booking_id]
            
            # Remove this booking from other bookings' dependency lists
            for booking_id_key in self.dependency_graph:
                if booking_id in self.dependency_graph[booking_id_key]:
                    self.dependency_graph[booking_id_key].remove(booking_id)
    
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
        old_booking = self.get_booking(booking_id)
        if old_booking:
            # Update budget
            self.budget_used -= old_booking.cost
            self.budget_used += new_booking.cost
            
            # Replace in list
            idx = self.bookings.index(old_booking)
            self.bookings[idx] = new_booking
    
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
        return [b for b in self.bookings if b.type == booking_type]
    
    # ========== BUDGET TRACKING ==========
    
    def get_remaining_budget(self) -> float:
        """
        Get remaining budget
        
        Returns:
            budget_max - budget_used, or inf if no budget limit
        """
        if self.budget_max is None:
            return float('inf')
        return self.budget_max - self.budget_used
    
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
        if self.budget_max is None:
            return True
        return (self.budget_used + additional_cost) <= self.budget_max
    
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
        if depends_on not in self.dependency_graph:
            self.dependency_graph[depends_on] = []
        if booking_id not in self.dependency_graph[depends_on]:
            self.dependency_graph[depends_on].append(booking_id)
    
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
        return self.dependency_graph.get(booking_id, [])
    
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
        affected = []
        visited = set()
        
        def dfs(current_id: str):
            """Depth-first search to find all transitive dependents"""
            if current_id in visited:
                return
            visited.add(current_id)
            
            # Get direct dependents
            direct_dependents = self.dependency_graph.get(current_id, [])
            for dependent_id in direct_dependents:
                if dependent_id not in visited:
                    affected.append(dependent_id)
                    dfs(dependent_id)
        
        dfs(booking_id)
        return affected
    
    def load_constraints_from_task(self, task_data: Dict[str, Any]):
        """
        Load constraints from task JSON
        
        Args:
            task_data: Task JSON dictionary with initial_constraints
            
        Example:
            task = json.load(open("tasks/easy/easy1.json"))
            tracker.load_constraints_from_task(task)
        """
        if "initial_constraints" not in task_data:
            return
        
        constraints = task_data["initial_constraints"]
        
        # Load hard constraints
        if "hard" in constraints:
            for name, value in constraints["hard"].items():
                self.add_constraint(name, value, is_hard=True)
        
        # Load soft constraints
        if "soft" in constraints:
            for name, value in constraints["soft"].items():
                self.add_constraint(name, value, is_hard=False)
 
 
# ============================================================================
# USAGE EXAMPLE
# ============================================================================
 
"""
# Load task and set up tracker
tracker = ConstraintTracker()
task = json.load(open("benchmarks/tasks/easy/easy1.json"))
tracker.load_constraints_from_task(task)

# Add bookings as agent plans
flight = Booking(
    booking_id="flight_001",
    type="flight",
    details={...},
    cost=250.0,
    dependencies=[]
)
tracker.add_booking(flight)

# Check budget before adding
if tracker.is_within_budget(300):
    tracker.add_booking(hotel)

# Dynamic event occurs
if flight_cancelled:
    affected = tracker.find_all_affected_bookings("flight_001")
    print(f"Need to replan: {affected}")  # ["hotel_001", ...]
    tracker.remove_booking("flight_001")
"""