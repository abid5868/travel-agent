from src.core.constraints import ConstraintTracker
from src.utils.types import Booking


def test_constraint_tracker_tracks_budget_usage():
    tracker = ConstraintTracker()
    tracker.add_constraint("budget_max", 1000)

    booking = Booking(booking_id="f1", type="flight", details={}, cost=300.0)
    tracker.add_booking(booking)

    assert tracker.budget_used == 300.0
    assert tracker.get_remaining_budget() == 700.0
    assert tracker.is_within_budget(500) is True
    assert tracker.is_within_budget(701) is False
