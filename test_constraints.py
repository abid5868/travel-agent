from src.core.constraints import ConstraintTracker
from src.utils.types import Booking
t = ConstraintTracker()
t.add_constraint('budget_max', 1000)
b = Booking(booking_id='f1', type='flight', details={}, cost=300.0)
t.add_booking(b)
print('budget used:', t.budget_used)
print('remaining:', t.get_remaining_budget())
print('within budget:', t.is_within_budget(500))