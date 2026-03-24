from typing import Tuple, List
from src.core.constraints import ConstraintTracker
 
# ============================================================================
# TODO: Implement the Validator Class + Integreate with ConstraintTracker so
# that Agent can validate itineraries after planning and replanning steps.
# ============================================================================


class Validator:
    """
    Validates itineraries against constraints
    """
    
    def __init__(self, constraint_tracker: ConstraintTracker):
        """
        Initialize validator with a constraint tracker
        
        Args:
            constraint_tracker: ConstraintTracker instance
        """
        pass
    
    def validate_all(self) -> Tuple[bool, List[str]]:
        """
        Run ALL validation checks
        
        Returns:
            (is_valid: bool, errors: List[str])
            
        Example:
            (True, [])  # All constraints satisfied
            (False, ["Budget exceeded by $50.00", "No hotels booked"])
        """
        pass
    
    def validate_budget(self) -> Tuple[bool, List[str]]:
        """
        Check if total cost <= budget_max
        
        Returns:
            (is_valid: bool, errors: List[str])
        """
        pass
    
    def validate_timing(self) -> Tuple[bool, List[str]]:
        """
        Check timing feasibility:
        - Flight arrival before hotel check-in
        - Hotel checkout before return flight
        
        Returns:
            (is_valid: bool, errors: List[str])
        """
        pass
    
    def validate_accessibility(self) -> Tuple[bool, List[str]]:
        """
        Check if wheelchair_accessible requirement met
        
        Returns:
            (is_valid: bool, errors: List[str])
        """
        pass
    
    def validate_completeness(self) -> Tuple[bool, List[str]]:
        """
        Check required components present:
        - At least 2 flights (outbound + return)
        - At least 1 hotel
        
        Returns:
            (is_valid: bool, errors: List[str])
        """
        pass
 
 
# ============================================================================
# USAGE BY AGENT
# ============================================================================
 
"""
How we will use this in agent.py:
 
from src.core.constraints import ConstraintTracker

tracker = ConstraintTracker()
validator = Validator(tracker)
 
# After planning, validate
is_valid, errors = validator.validate_all()
 
if is_valid:
    print("All constraints satisfied!")
else:
    print("Validation failed:")
    for error in errors:
        print(f"  - {error}")
"""
 
 