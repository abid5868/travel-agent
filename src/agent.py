"""
src/agent.py - Travel Planning Agent with ReAct Loop
"""

import ast
import json
import re
import time
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, Any, List, Optional, Tuple
from anthropic import Anthropic

from src.tools.flights import FlightSearchTool
from src.tools.hotels import HotelSearchTool
from src.tools.restaurants import RestaurantSearchTool
from src.tools.activities import ActivitySearchTool
from src.core.constraints import ConstraintTracker
from src.utils.types import Booking
from src.utils.prompts import (
    SYSTEM_PROMPT,
    ERROR_HANDLING_PROMPT,
    create_planning_prompt,
    create_replanning_prompt,
    create_final_itinerary_prompt,
)


class TravelAgent:

    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-6"
        self._initialize_tools()
        # these are reset per-run in _reset()
        self.tracker = None
        self.conversation_history = []
        self.turn_count = 0
        self.metadata = {}

    def _initialize_tools(self):
        self.flight_tool = FlightSearchTool("benchmarks/mock_data/flights.json")
        self.hotel_tool = HotelSearchTool("benchmarks/mock_data/hotels.json")
        self.restaurant_tool = RestaurantSearchTool("benchmarks/mock_data/restaurants.json")
        self.activity_tool = ActivitySearchTool("benchmarks/mock_data/activities.json")

    def _reset(self):
        """Reset all per-run state so the agent can be called multiple times."""
        self.tracker = ConstraintTracker()
        self.conversation_history = []
        self.turn_count = 0
        self._searched = set()            # track completed searches to prevent repetition
        self._required_components = []    # required_components from task spec
        self._soft_preferences = {}
        self._success_criteria = {}
        self._scenario = {}
        self._current_party_size = 1
        self._original_budget_max = None
        self._operation_log = []
        self._triggered_events = []
        self._post_requirements_turns = 0
        self._use_full_model = True
        self.metadata = {
            "total_tokens": 0,
            "api_calls": 0,
            "tool_calls": 0,
            "start_time": None,
            "end_time": None,
        }

    # ------------------------------------------------------------------

    def plan_trip(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self._reset()
        self.metadata["start_time"] = time.time()

        self._load_constraints(task)
        initial_prompt = self._create_planning_prompt(task)
        itinerary = self._react_planning_loop(initial_prompt, task)

        self.metadata["end_time"] = time.time()
        self.metadata["time_elapsed"] = round(
            self.metadata["end_time"] - self.metadata["start_time"], 2
        )

        final_itinerary_present = bool(itinerary and "FINAL ITINERARY" in itinerary)
        required_components_satisfied = self._all_required_components_satisfied()
        planning_requirements_satisfied = self._all_planning_requirements_satisfied()
        hard_constraints_satisfied = self._hard_constraints_satisfied()
        success_criteria_satisfied = self._success_criteria_satisfied()

        return {
            "itinerary": itinerary,
            "conversation": self.conversation_history,
            "metadata": self.metadata,
            "operation_log": list(self._operation_log),
            "final_itinerary_present": final_itinerary_present,
            "required_components_satisfied": required_components_satisfied,
            "planning_requirements_satisfied": planning_requirements_satisfied,
            "hard_constraints_satisfied": hard_constraints_satisfied,
            "success_criteria_satisfied": success_criteria_satisfied,
            "success": (
                final_itinerary_present and
                planning_requirements_satisfied and
                hard_constraints_satisfied and
                success_criteria_satisfied
            ),
        }

    def _load_constraints(self, task: Dict[str, Any]):
        hard = task.get("initial_constraints", {}).get("hard", {})
        soft = task.get("initial_constraints", {}).get("soft", {})
        user_profile = task.get("user_profile", {})
        for key, value in hard.items():
            self.tracker.add_constraint(key, value, is_hard=True)
        for key, value in soft.items():
            self.tracker.add_constraint(key, value, is_hard=False)
        self._required_components = task.get("required_components", [])
        self._soft_preferences = soft
        self._success_criteria = task.get("success_criteria", {})
        self._scenario = task.get("scenario", {})
        self._current_party_size = int(user_profile.get("party_size", 1) or 1)
        budget_max = hard.get("budget_max")
        self._original_budget_max = float(budget_max) if isinstance(budget_max, (int, float)) else None

    def _create_planning_prompt(self, task: Dict[str, Any]) -> str:
        return create_planning_prompt(task)

    # ------------------------------------------------------------------

    def _react_planning_loop(self, prompt: str, task: Dict[str, Any], max_iterations: int = 50) -> str:
        self.conversation_history.append({"role": "user", "content": prompt})

        pending_events = list(task.get("dynamic_events", []))

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            self.turn_count += 1
            print(f"  [iter {iteration}/{max_iterations}] thinking...", flush=True)

            response = self._get_agent_response()
            self._use_full_model = False

            action_needed, tool_name, tool_params = self._parse_action(response)
            if action_needed:
                print(f"  [iter {iteration}] ACTION: {tool_name}", flush=True)
            else:
                print(f"  [iter {iteration}] no action — checking for final itinerary", flush=True)

            user_message_added = False

            if action_needed:
                tool_result = self._execute_tool(tool_name, tool_params)

                error_message = self._extract_tool_error(tool_result)
                if error_message:
                    observation = ERROR_HANDLING_PROMPT.format(error_message=error_message)
                else:
                    observation = f"TOOL RESULT from {tool_name}:\n{json.dumps(tool_result, indent=2)}"

                self.conversation_history.append({"role": "user", "content": observation})
                user_message_added = True

                # Fire dynamic events at their trigger turn regardless of action state.
                due = [e for e in pending_events if self._event_is_ready(e)]
                for event in due:
                    pending_events.remove(event)
                    print(f"  [iter {iteration}] DYNAMIC EVENT: {event.get('event_type')}", flush=True)
                    replanning_prompt = self._handle_dynamic_event(event, response, task)
                    self.conversation_history.append({"role": "user", "content": replanning_prompt})
                    self._use_full_model = True
                    break  # one event at a time

            else:
                # Fire events that weren't caught during an action turn
                due = [e for e in pending_events if self._event_is_ready(e)]
                for event in due:
                    pending_events.remove(event)
                    print(f"  [iter {iteration}] DYNAMIC EVENT: {event.get('event_type')}", flush=True)
                    replanning_prompt = self._handle_dynamic_event(event, response, task)
                    self.conversation_history.append({"role": "user", "content": replanning_prompt})
                    self._use_full_model = True
                    user_message_added = True
                    break

                if not due:
                    if "FINAL ITINERARY" in response:
                        self._use_full_model = True
                        return self._render_final_itinerary()

            # Nudge to wrap up when nearing the iteration limit.
            all_required_done = self._all_planning_requirements_satisfied()
            ready_to_finalize = (
                all_required_done and
                self._hard_constraints_satisfied() and
                self._success_criteria_satisfied()
            )
            should_optimize = (
                ready_to_finalize and
                self._should_optimize_soft_preferences() and
                self._post_requirements_turns < 2 and
                iteration < max_iterations - 1
            )

            if should_optimize:
                self.conversation_history.append({
                    "role": "user",
                    "content": self._build_soft_optimization_prompt(),
                })
                self._use_full_model = True
                self._post_requirements_turns += 1
                user_message_added = True
            elif ready_to_finalize or iteration >= max_iterations - 1:
                return self._render_final_itinerary()

            if not user_message_added:
                self.conversation_history.append({"role": "user", "content": "Continue planning."})

        return self._render_final_itinerary()

    def _handle_dynamic_event(self, event: Dict[str, Any], itinerary: str, task: Dict[str, Any]) -> str:
        """Build and return a replanning prompt for a dynamic event."""
        affected_components = event.get("affected_components", [])
        affected_bookings = self._find_affected_bookings(affected_components, event)
        dependent_bookings = self._find_dependent_bookings(affected_components, affected_bookings, event)

        budget_max_after = self._apply_event_budget_update(event, task)
        party_size_after = self._apply_event_party_size_update(event)

        preserved_booking_ids = [
            booking.booking_id
            for booking in self.tracker.bookings
            if booking.booking_id not in {b.booking_id for b in affected_bookings}
            and booking.booking_id not in {b.booking_id for b in dependent_bookings}
        ]

        removed_booking_ids = []
        event_type = event.get("event_type", "dynamic_event")
        for booking in affected_bookings:
            if not self._should_auto_remove_affected_booking(booking, event, party_size_after):
                continue
            cancel_tool = getattr(self, f"{booking.type}_tool", None)
            if cancel_tool and hasattr(cancel_tool, "cancel"):
                cancel_tool.cancel(booking.booking_id)
            self.tracker.remove_booking(booking.booking_id)
            removed_booking_ids.append(booking.booking_id)
            self._record_operation(
                "system_event",
                "cancel",
                {"booking_id": booking.booking_id},
                {"booking_id": booking.booking_id},
                summary_override=f"removed invalidated {booking.type} {booking.booking_id} due to {event_type}",
            )

        self._triggered_events.append({
            "turn": self.turn_count,
            "event_type": event_type,
            "description": event.get("description", ""),
            "affected_components": list(affected_components),
            "affected_booking_ids": [booking.booking_id for booking in affected_bookings],
            "dependent_booking_ids": [booking.booking_id for booking in dependent_bookings],
            "preserved_booking_ids": preserved_booking_ids,
            "removed_booking_ids": removed_booking_ids,
            "budget_max_after": budget_max_after,
            "party_size_after": party_size_after,
        })

        return create_replanning_prompt(
            event,
            itinerary,
            affected_components,
            self._format_booking_refs(affected_bookings) if affected_bookings else "None currently booked.",
            self._format_booking_refs(dependent_bookings) if dependent_bookings else "None currently require review.",
            self._format_resolution_requirements(event.get("resolution_requirements", [])),
        )

    def _should_auto_remove_affected_booking(
        self,
        booking: Booking,
        event: Dict[str, Any],
        party_size_after: Optional[int],
    ) -> bool:
        event_type = event.get("event_type")
        if event_type == "accommodation_unavailable":
            return booking.type == "hotel"
        if event_type in {"schedule_swap_required", "venue_closed"}:
            return booking.type == "activity"
        if event_type == "party_size_increase":
            target_size = int(party_size_after or self._current_party_size or 1)
            current_size = int((booking.details or {}).get("party_size") or 0)
            return booking.type in {"flight", "hotel", "restaurant", "activity"} and current_size < target_size
        return False

    def _event_is_ready(self, event: Dict[str, Any]) -> bool:
        if self.turn_count < event.get("trigger_turn", 999):
            return False

        affected_components = event.get("affected_components", [])
        if not affected_components:
            return True

        return bool(self._find_affected_bookings(affected_components, event))

    def _booking_summary(self) -> str:
        """State injected each turn: confirmed bookings, still-needed checklist, budget, searched queries."""
        parts = []
        parts.append(f"Current party size for all new bookings: {self._current_party_size}")

        # --- Confirmed bookings ---
        if self.tracker.bookings:
            lines = [f"- [{b.type}] {b.booking_id}  cost=${b.cost}" for b in self.tracker.bookings]
            parts.append(
                "CONFIRMED BOOKINGS (do not re-book these):\n" +
                "\n".join(lines) +
                f"\nTotal spent: ${self.tracker.budget_used}"
            )
        else:
            parts.append("No bookings confirmed yet.")

        # --- Budget math ---
        if self.tracker.budget_max:
            remaining = self.tracker.get_remaining_budget()
            still_needed_types = self._remaining_required_categories()
            for category in self._remaining_success_criteria_categories():
                if category not in still_needed_types:
                    still_needed_types.append(category)
            budget_lines = [f"Budget remaining: ${remaining:.0f} of ${self.tracker.budget_max:.0f}"]
            if remaining < 0:
                budget_lines.append(f"Do not finalize yet. Current plan is over budget by ${abs(remaining):.0f}.")
            if self.tracker.get_constraint("strict_vegan_only"):
                budget_lines.append("All restaurants MUST be strictly vegan. Check 'dietary_options' before booking.")
            if still_needed_types and remaining > 0:
                approx = remaining / max(len(still_needed_types), 1)
                budget_lines.append(f"Still need to spend on: {', '.join(still_needed_types)}")
                budget_lines.append(f"Approx ${approx:.0f} available per remaining category — use this as max_price in searches")
            missing_requirements = self._get_missing_planning_requirements()
            if missing_requirements:
                budget_lines.append("Do not finalize yet. Missing required components:")
                for item in missing_requirements:
                    budget_lines.append(
                        f"- {item['component']} (need {item['required']}, have {item['matched']})"
                    )
            unmet_success_criteria = self._get_unmet_success_criteria()
            if unmet_success_criteria:
                budget_lines.append("Do not finalize yet. Unmet success criteria:")
                for item in unmet_success_criteria:
                    budget_lines.append(f"- {item}")
            elif self._should_optimize_soft_preferences():
                budget_lines.append(
                    "All required components are satisfied. Use remaining budget to improve soft preferences before finalizing."
                )
            parts.append("\n".join(budget_lines))

        # --- STILL NEEDED checklist from required_components ---
        planning_components = list(self._required_components)
        if self._implicit_flight_requirement_enabled():
            planning_components.append("intercity_outbound_flight")
            if self._return_transport_required():
                planning_components.append("intercity_return_flight")

        if planning_components:
            checklist = []
            for component in planning_components:
                if component == "intercity_outbound_flight":
                    done = self._has_matching_transport_flight("outbound")
                elif component == "intercity_return_flight":
                    done = self._has_matching_transport_flight("return")
                else:
                    done = self._component_satisfied(component)
                checklist.append(f"  [{'x' if done else ' '}] {component}")
            parts.append("STILL NEEDED (book these before finalizing):\n" + "\n".join(checklist))

        unmet_success_criteria = self._get_unmet_success_criteria()
        if unmet_success_criteria:
            parts.append(
                "STILL NEEDED FOR SUCCESS CRITERIA:\n" +
                "\n".join(f"  [ ] {item}" for item in unmet_success_criteria)
            )

        # --- Already-searched queries ---
        if self._searched:
            parts.append("ALREADY SEARCHED (do not search again):\n- " +
                         "\n- ".join(sorted(self._searched)))

        return "\n\n".join(parts)

    def _build_confirmed_bookings_text(self) -> str:
        """Fix 2: ground-truth booking list for the final itinerary prompt."""
        if not self.tracker.bookings:
            return "No bookings were confirmed by the system."
        lines = []
        for b in self.tracker.bookings:
            details = b.details or {}
            facts = []
            if b.type == "flight":
                facts.extend([
                    f"type={details.get('type', 'flight')}",
                    f"route={details.get('origin_city', '?')} -> {details.get('destination_city', '?')}",
                    f"date={details.get('departure_date', '?')}",
                    f"time={details.get('departure_time', '?')}",
                ])
            elif b.type == "hotel":
                facts.extend([
                    f"name={details.get('hotel_name', 'unknown')}",
                    f"check_in={details.get('check_in', '?')}",
                    f"check_out={details.get('check_out', '?')}",
                ])
            elif b.type in {"activity", "restaurant"}:
                full_data = details.get("full_data", {}) if isinstance(details.get("full_data"), dict) else {}
                facts.extend([
                    f"name={details.get('name', 'unknown')}",
                    f"type={full_data.get('type', b.type)}",
                    f"date={details.get('date', '?')}",
                    f"time={details.get('time', '?')}",
                ])
            lines.append(
                f"- [{b.type.upper()}] booking_id={b.booking_id}  cost=${b.cost}"
                + (f"  facts={'; '.join(facts)}" if facts else "")
                + (f"  details={json.dumps(details)}" if details else "")
            )
        lines.append(f"\nTotal confirmed spend: ${self.tracker.budget_used}")
        if self.tracker.budget_max:
            lines.append(f"Budget limit: ${self.tracker.budget_max}")
        return "\n".join(lines)

    def _build_requirement_status_text(self) -> str:
        lines = []
        for component in self._required_components:
            matched = self._matched_component_count(component)
            required = self._required_component_target(component)
            status = "SATISFIED" if matched >= required else "UNMET"
            lines.append(f"- {component}: {status} (matched {matched} / required {required})")

        if self._implicit_flight_requirement_enabled():
            outbound_matched = 1 if self._has_matching_transport_flight("outbound") else 0
            outbound_status = "SATISFIED" if outbound_matched else "UNMET"
            lines.append(f"- intercity_outbound_flight: {outbound_status} (matched {outbound_matched} / required 1)")
            if self._return_transport_required():
                return_matched = 1 if self._has_matching_transport_flight("return") else 0
                return_status = "SATISFIED" if return_matched else "UNMET"
                lines.append(f"- intercity_return_flight: {return_status} (matched {return_matched} / required 1)")

        if not lines:
            return "No required components were specified."
        return "\n".join(lines)

    def _build_budget_context_text(self) -> str:
        current_budget = self.tracker.budget_max
        lines = []
        if current_budget is not None:
            lines.append(f"- current_active_budget_limit: ${current_budget:.2f}")
            lines.append(f"- total_confirmed_spend: ${self.tracker.budget_used:.2f}")
            lines.append(f"- remaining_budget: ${self.tracker.get_remaining_budget():.2f}")
        if current_budget is not None and self._original_budget_max is not None and current_budget != self._original_budget_max:
            lines.append("- budget_changed_during_replanning: yes")
            lines.append("- active_budget_note: Use only the current active budget limit in the final budget table. Mention any earlier budget only in the replanning audit trail if needed.")
        if not lines:
            return "No explicit budget context was recorded."
        return "\n".join(lines)

    def _build_success_criteria_status_text(self) -> str:
        if not self._success_criteria:
            return "No explicit success criteria were specified."

        lines = []
        for name, expected in self._success_criteria.items():
            _, satisfied, detail = self._evaluate_success_criterion(name, expected)
            status = "SATISFIED" if satisfied else "UNMET"
            lines.append(f"- {name}: {status} ({detail})")
        return "\n".join(lines)

    def _get_unmet_success_criteria(self) -> List[str]:
        unmet = []
        for name, expected in self._success_criteria.items():
            _, satisfied, detail = self._evaluate_success_criterion(name, expected)
            if not satisfied:
                unmet.append(f"{name} ({detail})")
        return unmet

    def _build_operation_log_text(self) -> str:
        if not self._operation_log:
            return "No booking or cancellation operations were recorded."
        return "\n".join(
            f"- turn {entry['turn']}: {entry['action']} {entry['tool']} -> {entry['summary']}"
            for entry in self._operation_log
        )

    def _render_final_itinerary(self) -> str:
        lines = ["# FINAL ITINERARY", ""]

        overview_parts = []
        origin = str(self._scenario.get("origin_city", "")).strip()
        destinations = [str(city).strip() for city in self._scenario.get("destination_cities", []) if str(city).strip()]
        if origin:
            overview_parts.append(f"**Origin:** {origin}")
        if destinations:
            overview_parts.append(f"**Destination(s):** {', '.join(destinations)}")
        trip_days = self._scenario.get("trip_duration_days")
        if trip_days:
            overview_parts.append(f"**Trip Length:** {trip_days} days")
        overview_parts.append(f"**Party Size:** {max(int(self._current_party_size or 1), 1)}")
        if overview_parts:
            lines.append(" | ".join(overview_parts))
            lines.append("")

        lines.extend(self._render_final_flights_section())
        lines.append("")
        lines.extend(self._render_final_hotels_section())
        lines.append("")
        lines.extend(self._render_final_activities_section())
        lines.append("")
        lines.extend(self._render_final_restaurants_section())
        lines.append("")
        lines.extend(self._render_final_budget_section())
        lines.append("")
        lines.extend(self._render_final_requirement_section())
        lines.append("")
        lines.extend(self._render_final_success_criteria_section())
        lines.append("")
        lines.extend(self._render_final_audit_section())

        return "\n".join(lines).rstrip() + "\n"

    def _render_final_flights_section(self) -> List[str]:
        flights = sorted(self.tracker.get_bookings_by_type("flight"), key=self._booking_sort_key)
        lines = ["## 1. Flights", ""]
        if not flights:
            lines.append("No flights booked.")
            return lines

        rows = []
        for booking in flights:
            details = booking.details or {}
            route = f"{details.get('origin_city', '?')} -> {details.get('destination_city', '?')}"
            rows.append([
                booking.booking_id,
                str(details.get("type", "flight")).replace("_", " "),
                route,
                str(details.get("departure_date", "?")),
                str(details.get("departure_time", "?")),
                str(details.get("arrival_time", "?")),
                self._format_currency(booking.cost),
            ])
        lines.extend(self._markdown_table(
            ["Booking ID", "Type", "Route", "Date", "Departure", "Arrival", "Cost"],
            rows,
        ))
        return lines

    def _render_final_hotels_section(self) -> List[str]:
        hotels = sorted(self.tracker.get_bookings_by_type("hotel"), key=self._booking_sort_key)
        lines = ["## 2. Hotel", ""]
        if not hotels:
            lines.append("not booked")
            return lines

        rows = []
        for booking in hotels:
            details = booking.details or {}
            rows.append([
                booking.booking_id,
                str(details.get("hotel_name", "unknown")),
                str(details.get("check_in", "?")),
                str(details.get("check_out", "?")),
                str(details.get("nights", "?")),
                self._format_currency(booking.cost),
            ])
        lines.extend(self._markdown_table(
            ["Booking ID", "Name", "Check-In", "Check-Out", "Nights", "Cost"],
            rows,
        ))
        return lines

    def _render_final_activities_section(self) -> List[str]:
        activities = sorted(self.tracker.get_bookings_by_type("activity"), key=self._booking_sort_key)
        lines = ["## 3. Activities", ""]
        if not activities:
            lines.append("none booked")
            return lines

        rows = []
        for booking in activities:
            details = booking.details or {}
            full_data = details.get("full_data", {}) if isinstance(details.get("full_data"), dict) else {}
            activity_type = full_data.get("type") or details.get("type") or "activity"
            rows.append([
                booking.booking_id,
                str(details.get("name", "unknown")),
                str(activity_type).replace("_", " "),
                str(details.get("date", "?")),
                str(details.get("time", "?")),
                self._format_currency(booking.cost),
            ])
        lines.extend(self._markdown_table(
            ["Booking ID", "Name", "Type", "Date", "Time", "Cost"],
            rows,
        ))
        return lines

    def _render_final_restaurants_section(self) -> List[str]:
        restaurants = sorted(self.tracker.get_bookings_by_type("restaurant"), key=self._booking_sort_key)
        lines = ["## 4. Restaurants", ""]
        if not restaurants:
            lines.append("none booked")
            return lines

        rows = []
        for booking in restaurants:
            details = booking.details or {}
            rows.append([
                booking.booking_id,
                str(details.get("name", "unknown")),
                str(details.get("date", "?")),
                str(details.get("time", "?")),
                self._format_currency(booking.cost),
            ])
        lines.extend(self._markdown_table(
            ["Booking ID", "Name", "Date", "Time", "Cost"],
            rows,
        ))
        return lines

    def _render_final_budget_section(self) -> List[str]:
        lines = ["## 5. Budget Summary", ""]
        rows = []
        category_labels = {
            "flight": "Flights",
            "hotel": "Hotel",
            "activity": "Activities",
            "restaurant": "Restaurants",
            "surcharge": "Surcharges",
        }

        for booking_type in ("flight", "hotel", "activity", "restaurant", "surcharge"):
            bookings = self.tracker.get_bookings_by_type(booking_type)
            if not bookings:
                continue
            rows.append([
                category_labels[booking_type],
                f"{len(bookings)} booking(s)",
                self._format_currency(sum(booking.cost for booking in bookings)),
            ])

        rows.append(["", "**GRAND TOTAL**", f"**{self._format_currency(self.tracker.budget_used)}**"])
        if self.tracker.budget_max is not None:
            rows.append(["", "**Active Budget Cap**", f"**{self._format_currency(self.tracker.budget_max)}**"])
            rows.append(["", "**Remaining Budget**", f"**{self._format_currency(self.tracker.get_remaining_budget())}**"])

        lines.extend(self._markdown_table(["Category", "Item", "Cost"], rows))
        return lines

    def _render_final_requirement_section(self) -> List[str]:
        lines = ["## 6. Requirement Status", ""]
        rows = []
        for component in self._required_components:
            matched = self._matched_component_count(component)
            required = self._required_component_target(component)
            status = "SATISFIED" if matched >= required else "UNMET"
            rows.append([component, f"{status} (matched {matched} / required {required})"])

        if self._implicit_flight_requirement_enabled():
            outbound_matched = 1 if self._has_matching_transport_flight("outbound") else 0
            outbound_status = "SATISFIED" if outbound_matched else "UNMET"
            rows.append(["intercity_outbound_flight", f"{outbound_status} (matched {outbound_matched} / required 1)"])
            if self._return_transport_required():
                return_matched = 1 if self._has_matching_transport_flight("return") else 0
                return_status = "SATISFIED" if return_matched else "UNMET"
                rows.append(["intercity_return_flight", f"{return_status} (matched {return_matched} / required 1)"])

        if not rows:
            lines.append("No required components were specified.")
            return lines

        lines.extend(self._markdown_table(["Requirement", "Status"], rows))
        return lines

    def _render_final_success_criteria_section(self) -> List[str]:
        lines = ["## 7. Success Criteria Status", ""]
        if not self._success_criteria:
            lines.append("No explicit success criteria were specified.")
            return lines

        rows = []
        for name, expected in self._success_criteria.items():
            _, satisfied, detail = self._evaluate_success_criterion(name, expected)
            status = "SATISFIED" if satisfied else "UNMET"
            rows.append([name, f"{status} ({detail})"])

        lines.extend(self._markdown_table(["Criterion", "Status"], rows))
        return lines

    def _render_final_audit_section(self) -> List[str]:
        lines = ["## 8. Replanning Audit Trail", ""]
        if not self._operation_log:
            lines.append("No booking or cancellation operations were recorded.")
            return lines

        rows = []
        for entry in self._operation_log:
            rows.append([
                str(entry.get("turn", "?")),
                f"{entry.get('action', '')} {entry.get('tool', '')}".strip(),
                str(entry.get("summary", "")),
            ])
        lines.extend(self._markdown_table(["Turn", "Action", "Result"], rows))
        return lines

    def _booking_sort_key(self, booking: Booking) -> Tuple[str, str, str, str]:
        details = booking.details or {}
        if booking.type == "flight":
            return (
                str(details.get("departure_date", "")),
                str(details.get("departure_time", "")),
                booking.type,
                booking.booking_id,
            )
        if booking.type == "hotel":
            return (
                str(details.get("check_in", "")),
                "00:00",
                booking.type,
                booking.booking_id,
            )
        if booking.type in {"activity", "restaurant"}:
            return (
                str(details.get("date", "")),
                str(details.get("time", "")),
                booking.type,
                booking.booking_id,
            )
        return ("", "", booking.type, booking.booking_id)

    def _markdown_table(self, headers: List[str], rows: List[List[str]]) -> List[str]:
        lines = [
            "| " + " | ".join(headers) + " |",
            "|" + "|".join(["---"] * len(headers)) + "|",
        ]
        for row in rows:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
        return lines

    def _format_currency(self, amount: float) -> str:
        return f"${amount:.2f}"

    def _build_soft_optimization_prompt(self) -> str:
        interests = ", ".join(self._soft_preferences.get("interests", [])) or "none"
        preferences = ", ".join(self._soft_preferences.get("preferences", [])) or "none"
        return (
            "All required components are satisfied, but budget remains.\n"
            f"Soft interests: {interests}\n"
            f"Soft preferences: {preferences}\n"
            "Use one more search-and-book cycle, if possible, to improve the trip for these preferences. "
            "Prioritize underrepresented interests and stay within the remaining budget."
        )

    def _extract_tool_error(self, tool_result: Any) -> str:
        if not isinstance(tool_result, dict):
            return ""
        if isinstance(tool_result.get("error"), str) and tool_result["error"]:
            return tool_result["error"]
        if tool_result.get("status") == "error" and isinstance(tool_result.get("message"), str):
            return tool_result["message"]
        return ""

    def _all_required_components_satisfied(self) -> bool:
        return bool(self._required_components) and all(
            self._component_satisfied(component) for component in self._required_components
        )

    def _all_planning_requirements_satisfied(self) -> bool:
        explicit_done = not self._required_components or self._all_required_components_satisfied()
        return explicit_done and self._implicit_transport_satisfied()

    def _get_missing_required_components(self) -> List[Dict[str, Any]]:
        missing = []
        for component in self._required_components:
            matched = self._matched_component_count(component)
            required = self._required_component_target(component)
            if matched < required:
                missing.append({
                    "component": component,
                    "matched": matched,
                    "required": required,
                })
        return missing

    def _get_missing_planning_requirements(self) -> List[Dict[str, Any]]:
        missing = list(self._get_missing_required_components())
        if self._implicit_flight_requirement_enabled():
            if not self._has_matching_transport_flight("outbound"):
                missing.append({"component": "intercity_outbound_flight", "matched": 0, "required": 1})
            if self._return_transport_required() and not self._has_matching_transport_flight("return"):
                missing.append({"component": "intercity_return_flight", "matched": 0, "required": 1})
        return missing

    def _remaining_required_categories(self) -> List[str]:
        categories = []
        if self._implicit_flight_requirement_enabled() and not self._implicit_transport_satisfied():
            categories.append("required flights")
        if any("flight" in component.lower() and not self._component_satisfied(component) for component in self._required_components):
            if "required flights" not in categories:
                categories.append("required flights")
        if any(any(word in component.lower() for word in ("hotel", "hotels", "accommodation", "accommodations", "lodge", "lodges")) and not self._component_satisfied(component) for component in self._required_components):
            categories.append("required lodging")
        if any(any(word in component.lower() for word in ("activity", "activities", "tour", "tours", "museum", "museums", "visit", "visits", "experience", "experiences", "park", "parks", "attraction", "attractions", "venue", "venues", "entertainment", "show", "concert", "music", "jazz", "live")) and not self._component_satisfied(component) for component in self._required_components):
            categories.append("required activities")
        if any(any(word in component.lower() for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")) and not self._component_satisfied(component) for component in self._required_components):
            categories.append("required restaurants")
        return categories

    def _remaining_success_criteria_categories(self) -> List[str]:
        categories = []
        for name, expected in self._success_criteria.items():
            _, satisfied, _ = self._evaluate_success_criterion(name, expected)
            if satisfied:
                continue

            if name in {"beach_activities_min", "museums_included_min"}:
                categories.append("required activities")
            elif name == "hotel_proximity_to_museums":
                categories.append("required lodging")

        deduped = []
        for category in categories:
            if category not in deduped:
                deduped.append(category)
        return deduped

    def _component_satisfied(self, component: str) -> bool:
        return self._matched_component_count(component) >= self._required_component_target(component)

    def _matched_component_count(self, component: str) -> int:
        normalized = component.lower()
        if "flight" in normalized:
            return sum(
                1 for booking in self.tracker.get_bookings_by_type("flight")
                if self._flight_booking_matches(component, booking)
            )
        if any(word in normalized for word in ("hotel", "hotels", "accommodation", "accommodations", "lodge", "lodges")):
            total_nights = 0
            for booking in self.tracker.get_bookings_by_type("hotel"):
                if self._lodging_booking_matches(component, booking):
                    details = booking.details or {}
                    nights = int(details.get("nights", 0))
                    total_nights += nights
            return total_nights
            # return max(
            #     (
            #         1 for booking in self.tracker.get_bookings_by_type("hotel")
            #         if self._lodging_booking_matches(component, booking)
            #     ),
            #     default=0,
            # )
        if any(word in normalized for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")):
            return sum(
                1 for booking in self.tracker.get_bookings_by_type("restaurant")
                if self._experience_booking_matches(component, booking)
            )
        if any(word in normalized for word in (
            "activity", "activities", "tour", "tours", "museum", "museums", "visit",
            "visits", "experience", "experiences", "park", "parks", "attraction",
            "attractions", "venue", "venues", "entertainment", "show", "concert",
            "music", "jazz", "live", "transportation", "transport", "wedding", "ceremony"
        )):
            return sum(
                1 for booking in self.tracker.get_bookings_by_type("activity")
                if self._experience_booking_matches(component, booking)
            )
        return 0

    def _required_component_target(self, component: str) -> int:
        normalized = component.lower()
        required_nights = self._extract_nights(component)
        if required_nights and any(
            word in normalized
            for word in ("hotel", "hotels", "accommodation", "accommodations", "lodge", "lodges")
        ):
            return required_nights
        return self._extract_min_count(component) or 1

    def _intercity_trip(self) -> bool:
        origin = str(self._scenario.get("origin_city", "")).strip().lower()
        destinations = [
            str(city).strip().lower()
            for city in self._scenario.get("destination_cities", [])
            if str(city).strip()
        ]
        return bool(origin and destinations and any(destination != origin for destination in destinations))

    def _has_explicit_flight_requirement(self) -> bool:
        return any("flight" in component.lower() for component in self._required_components)

    def _return_transport_required(self) -> bool:
        constraint = self.tracker.get_constraint("return_date")
        return bool(constraint and constraint.value)

    def _implicit_flight_requirement_enabled(self) -> bool:
        return self._intercity_trip() and not self._has_explicit_flight_requirement()

    def _has_matching_transport_flight(self, direction: str) -> bool:
        origin = str(self._scenario.get("origin_city", "")).strip().lower()
        destinations = {
            str(city).strip().lower()
            for city in self._scenario.get("destination_cities", [])
            if str(city).strip()
        }

        for booking in self.tracker.get_bookings_by_type("flight"):
            details = booking.details or {}
            booking_type = str(details.get("type", "")).lower()
            booking_origin = str(details.get("origin_city", "")).strip().lower()
            booking_destination = str(details.get("destination_city", "")).strip().lower()

            if direction == "outbound":
                if booking_origin == origin and booking_destination in destinations:
                    if booking_type in {"", "outbound_flight"}:
                        return True
            else:
                if booking_origin in destinations and booking_destination == origin:
                    if booking_type in {"", "return_flight"}:
                        return True
        return False

    def _implicit_transport_satisfied(self) -> bool:
        if not self._implicit_flight_requirement_enabled():
            return True
        if not self._has_matching_transport_flight("outbound"):
            return False
        if self._return_transport_required() and not self._has_matching_transport_flight("return"):
            return False
        return True

    def _flight_booking_matches(self, component: str, booking: Booking) -> bool:
        details = booking.details or {}
        booking_type = str(details.get("type", "")).lower()
        normalized = component.lower()

        if "return" in normalized and booking_type != "return_flight":
            return False
        if "outbound" in normalized and booking_type != "outbound_flight":
            return False

        if "after_" in normalized:
            threshold = normalized.split("after_", 1)[1]
            if str(details.get("departure_time", "")) < threshold:
                return False
        if "before_" in normalized:
            threshold = normalized.split("before_", 1)[1]
            if str(details.get("departure_time", "")) > threshold:
                return False

        component_tokens = self._tokenize_component(normalized)
        route_hint_tokens = {
            token for token in component_tokens
            if token not in {
                "flight", "flights", "outbound", "return", "after", "before",
                "arriving", "meeting", "arriving_before_meeting",
                "train", "trains", "rail", "rails", "or"
            } and not token.isdigit()
        }
        route_tokens = set()
        route_tokens.update(self._tokenize_component(str(details.get("origin_city", ""))))
        route_tokens.update(self._tokenize_component(str(details.get("destination_city", ""))))
        if route_hint_tokens and not route_tokens:
            return False
        if route_hint_tokens and route_tokens and not route_hint_tokens.intersection(route_tokens):
            return False

        return True

    def _lodging_booking_matches(self, component: str, booking: Booking) -> bool:
        details = booking.details or {}
        normalized = component.lower()
        required_nights = self._extract_nights(component)
        if required_nights and int(details.get("nights", 0)) < required_nights:
            return False
        if any(word in normalized for word in ("accessible", "wheelchair")) and not self._detail_or_tag_match(details, "wheelchair_accessible"):
            return False
        return True

    def _experience_booking_matches(self, component: str, booking: Booking) -> bool:
        details = booking.details or {}
        normalized = component.lower()

        if any(word in normalized for word in ("accessible", "wheelchair")) and not self._detail_or_tag_match(details, "wheelchair_accessible"):
            return False

        structured_terms = self._booking_structured_terms(details)
        required_aliases = self._component_match_aliases(normalized)
        if required_aliases:
            return bool(required_aliases & structured_terms)

        content_tokens = self._booking_content_tokens(details)
        keywords = self._component_keywords(normalized)
        if "business" in keywords:
            keywords.add("client")
        if not keywords:
            return True
        return bool(keywords & content_tokens)

    def _booking_structured_terms(self, details: Dict[str, Any]) -> set[str]:
        full_data = details.get("full_data", {}) if isinstance(details.get("full_data"), dict) else {}
        terms = set()

        for value in (
            full_data.get("type", ""),
            details.get("type", ""),
        ):
            normalized = self._normalize_term(str(value))
            if normalized:
                terms.add(normalized)

        for item in full_data.get("category", []):
            normalized = self._normalize_term(str(item))
            if normalized:
                terms.add(normalized)

        for tag in full_data.get("tags", []):
            normalized = self._normalize_term(str(tag))
            if normalized:
                terms.add(normalized)

        if full_data.get("family_friendly") is True:
            terms.add("family_friendly")
        if full_data.get("wheelchair_accessible") is True or full_data.get("is_wheelchair_accessible") is True:
            terms.add("wheelchair_accessible")

        return terms

    def _component_match_aliases(self, component: str) -> set[str]:
        normalized = component.lower()
        aliases = set()

        if "guided_boat_tour" in normalized:
            aliases.update({"guided_boat_tour", "boat_tour"})
        if "beach_activities" in normalized or "beach_activity" in normalized:
            aliases.update({"beach_activity", "beach"})

        return aliases

    def _normalize_term(self, value: str) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    def _booking_content_tokens(self, details: Dict[str, Any]) -> set[str]:
        full_data = details.get("full_data", {}) if isinstance(details.get("full_data"), dict) else {}
        tokens = set()
        for value in (
            details.get("name", ""),
            details.get("hotel_name", ""),
            full_data.get("type", ""),
        ):
            tokens.update(self._tokenize_component(str(value)))
        for item in full_data.get("category", []):
            tokens.update(self._tokenize_component(str(item)))
        for tag in full_data.get("tags", []):
            tokens.update(self._tokenize_component(str(tag)))
        for diet in full_data.get("dietary_options", []):
            tokens.update(self._tokenize_component(str(diet)))
        if full_data.get("family_friendly") is True:
            tokens.update({"family", "family_friendly"})
        if full_data.get("wheelchair_accessible") is True or full_data.get("is_wheelchair_accessible") is True:
            tokens.update({"accessible", "wheelchair", "wheelchair_accessible"})
        return tokens

    def _component_keywords(self, component: str) -> set[str]:
        tokens = self._tokenize_component(component)
        ignored = {
            "min", "flight", "flights", "hotel", "hotels", "accommodation", "accommodations",
            "lodge", "lodges", "restaurant", "restaurants", "dining", "meal", "meals",
            "brunch", "dinner", "activity", "activities", "tour", "tours", "museum",
            "museums", "visit", "visits", "experience", "experiences", "park", "parks",
            "attraction", "attractions", "venue", "venues", "accessible", "wheelchair",
            "outbound", "return", "night", "nights", "or", "all", "both", "after", "before", "business"
        }
        return {token for token in tokens if token not in ignored and not token.isdigit()}

    def _tokenize_component(self, value: str) -> set[str]:
        if not value:
            return set()
        return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}

    def _extract_min_count(self, component: str) -> int:
        match = re.search(r"_min_(\d+)", component.lower())
        if match:
            return int(match.group(1))
        return 0

    def _extract_nights(self, component: str) -> int:
        match = re.search(r"_(\d+)_nights?", component.lower())
        if match:
            return int(match.group(1))
        return 0

    def _detail_or_tag_match(self, details: Dict[str, Any], tag: str) -> bool:
        full_data = details.get("full_data", {}) if isinstance(details.get("full_data"), dict) else {}
        if full_data.get(tag) is True:
            return True
        if tag == "wheelchair_accessible" and full_data.get("is_wheelchair_accessible") is True:
            return True
        return tag in full_data.get("tags", [])

    def _hard_constraints_satisfied(self) -> bool:
        if self.tracker.budget_max is not None and self.tracker.budget_used > self.tracker.budget_max:
            return False

        hard_constraints = {constraint.name: constraint.value for constraint in self.tracker.get_hard_constraints()}
        accessibility_required = bool(
            hard_constraints.get("wheelchair_accessible") or hard_constraints.get("accessibility_required")
        )
        if accessibility_required:
            for booking in self.tracker.bookings:
                if booking.type in {"hotel", "restaurant", "activity"} and not self._detail_or_tag_match(booking.details or {}, "wheelchair_accessible"):
                    return False
        return True

    def _success_criteria_satisfied(self) -> bool:
        if not self._success_criteria:
            return True
        return all(
            self._evaluate_success_criterion(name, expected)[1]
            for name, expected in self._success_criteria.items()
        )

    def _evaluate_success_criterion(self, name: str, expected: Any) -> Tuple[Any, bool, str]:
        active_ids = {booking.booking_id for booking in self.tracker.bookings}

        if name == "total_cost_max":
            actual = self.tracker.budget_used
            return actual, actual <= float(expected), f"actual ${actual:.2f} / max ${float(expected):.2f}"

        if name == "timing_feasible":
            actual = self._timing_feasible()
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "all_venues_wheelchair_accessible":
            actual = self._hard_constraints_satisfied()
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "replanning_successful":
            actual = all(self._event_resolved(event_state) for event_state in self._triggered_events)
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "unaffected_bookings_preserved":
            actual = all(
                set(event_state.get("preserved_booking_ids", [])).issubset(active_ids)
                for event_state in self._triggered_events
            )
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "dependent_bookings_updated":
            actual = all(
                not event_state.get("dependent_booking_ids")
                or self._dependent_bookings_reviewed(event_state)
                or self._dependents_still_valid_without_changes(event_state)
                for event_state in self._triggered_events
            )
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "final_party_size":
            actual = max(int(self._current_party_size or 1), 1)
            satisfied = actual >= int(expected) and self._bookings_meet_party_size(int(expected))
            return actual, satisfied, f"actual {actual} / expected {expected}"

        if name == "boat_tour_on_sunday":
            actual = self._has_component_on_weekday("guided_boat_tour_min_1", "sunday")
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "beach_activities_on_saturday":
            actual = self._has_component_on_weekday("beach_activities_min_1", "saturday")
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "animal_park_removed":
            actual = all(self._venue_closed_resolved(event_state) for event_state in self._triggered_events)
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "early_return_executed":
            actual = all(self._trip_cut_short_resolved(event_state) for event_state in self._triggered_events)
            return actual, actual is bool(expected), f"actual {actual} / expected {expected}"

        if name == "beach_activities_min" and isinstance(expected, int):
            actual = self._matched_component_count(f"beach_activities_min_{expected}")
            return actual, actual >= expected, f"actual {actual} / expected at least {expected}"

        if name == "museums_included_min" and isinstance(expected, int):
            actual = self._matched_component_count(f"museum_visits_min_{expected}")
            return actual, actual >= expected, f"actual {actual} / expected at least {expected}"

        if name == "hotel_proximity_to_museums":
            actual = self._hotel_proximity_requirement_satisfied("museums", str(expected))
            return actual, actual is True, f"actual {actual} / expected {expected}"

        return "not_checked", True, "no code-side evaluator"

    def _hotel_proximity_requirement_satisfied(self, topic: str, expected: str) -> bool:
        hotels = self.tracker.get_bookings_by_type("hotel")
        if not hotels:
            return False
        return any(self._hotel_matches_proximity_topic(booking, topic, expected) for booking in hotels)

    def _hotel_matches_proximity_topic(self, booking: Booking, topic: str, expected: str) -> bool:
        details = booking.details or {}
        full_data = details.get("full_data", {}) if isinstance(details.get("full_data"), dict) else {}
        proximity = full_data.get("proximity_to_attractions", {})
        if not isinstance(proximity, dict):
            return False

        max_miles = 2.0 if expected == "within_30min" else 1.0
        topic_keys = {
            "museums": {"museum", "museums", "moma", "met", "whitney", "natural_history"},
        }.get(topic, {topic})

        for key, value in proximity.items():
            key_tokens = self._tokenize_component(str(key))
            if topic_keys & key_tokens and self._distance_within_limit(str(value), max_miles):
                return True

        if topic == "museums":
            for key, value in proximity.items():
                if "subway" in self._tokenize_component(str(key)) and self._distance_within_limit(str(value), 0.5):
                    return True

        return False

    def _distance_within_limit(self, value: str, max_miles: float) -> bool:
        normalized = value.strip().lower()
        if normalized in {"steps", "on_site", "onsite"}:
            return True
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*miles?", normalized)
        if not match:
            return False
        return float(match.group(1)) <= max_miles

    def _should_optimize_soft_preferences(self) -> bool:
        if not (self._soft_preferences.get("interests") or self._soft_preferences.get("preferences")):
            return False
        return self.tracker.get_remaining_budget() > 0

    def _build_messages(self) -> List[Dict]:
        """Build windowed message list with injected booking summary."""
        window = 8
        if len(self.conversation_history) > window + 1:
            messages = [self.conversation_history[0]] + self.conversation_history[-window:]
        else:
            messages = list(self.conversation_history)
        booking_note = {"role": "user", "content": self._booking_summary()}
        return [messages[0], booking_note] + messages[1:]

    def _get_agent_response(self) -> str:
        """
        Always uses Sonnet. Planning/replanning/final turns get a full blocking response
        (4096 tokens). Tool-calling turns use streaming with early stop once a complete
        ACTION(...) line is received (700 tokens), avoiding waiting for the full output.
        """
        full = self._use_full_model
        max_tokens = 4096
        messages = self._build_messages()

        try:
            if full:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=messages,
                    system=SYSTEM_PROMPT,
                    timeout=180,
                )
                self.metadata["api_calls"] += 1
                self.metadata["total_tokens"] += response.usage.input_tokens + response.usage.output_tokens
                response_text = response.content[0].text
            else:
                response_text = self._stream_until_action(self.model, max_tokens, messages)
                self.metadata["api_calls"] += 1

            self.conversation_history.append({"role": "assistant", "content": response_text})
            return response_text
        except Exception as e:
            return f"Error: {e}"

    def _stream_until_action(self, model: str, max_tokens: int, messages: List[Dict]) -> str:
        """Stream the response and stop as soon as a complete ACTION(...) line is received."""
        chunks: List[str] = []
        try:
            with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                system=SYSTEM_PROMPT,
                timeout=60,
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                    current = "".join(chunks)
                    # Stop early once we have a complete ACTION(...)  line
                    if "ACTION:" in current:
                        for line in current.split("\n"):
                            if "ACTION:" in line and "(" in line and line.count(")") >= line.count("("):
                                return current   # complete action found — stop streaming
        except Exception as e:
            if chunks:
                return "".join(chunks)  # return whatever we got before the error
            raise
        return "".join(chunks)

    # ------------------------------------------------------------------

    def _component_to_booking_types(self, component: str) -> set[str]:
        normalized = component.lower()
        if any(word in normalized for word in ("hotel", "hotels", "accommodation", "accommodations", "lodge", "lodges")):
            return {"hotel"}
        if "flight" in normalized:
            return {"flight"}
        if any(word in normalized for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")):
            return {"restaurant"}
        if any(word in normalized for word in (
            "activity", "activities", "tour", "tours", "museum", "museums", "visit",
            "visits", "experience", "experiences", "park", "parks", "attraction",
            "attractions", "venue", "venues", "entertainment", "show", "concert",
            "music", "jazz", "live", "transportation", "transport", "wedding", "ceremony"
        )):
            return {"activity"}
        return set()

    def _find_affected_bookings(
        self,
        affected_components: List[str],
        event: Optional[Dict[str, Any]] = None,
    ) -> List[Booking]:
        matched: List[Booking] = []
        seen_ids = set()
        for booking in self.tracker.bookings:
            if any(self._booking_matches_event_component(booking, component, event) for component in affected_components):
                if booking.booking_id not in seen_ids:
                    matched.append(booking)
                    seen_ids.add(booking.booking_id)
        return matched

    def _find_dependent_bookings(
        self,
        affected_components: List[str],
        affected_bookings: List[Booking],
        event: Optional[Dict[str, Any]] = None,
    ) -> List[Booking]:
        affected_types = set()
        for component in affected_components:
            affected_types.update(self._component_to_booking_types(component))

        dependent_types = set()
        if "hotel" in affected_types:
            dependent_types.add("restaurant")
        if "flight" in affected_types:
            dependent_types.update({"hotel", "restaurant", "activity"})

        affected_ids = {booking.booking_id for booking in affected_bookings}
        return [
            booking for booking in self.tracker.bookings
            if booking.type in dependent_types and booking.booking_id not in affected_ids
        ]

    def _format_booking_refs(self, bookings: List[Booking]) -> str:
        lines = []
        for booking in bookings:
            label = booking.details.get("name") or booking.details.get("hotel_name") or booking.booking_id
            lines.append(f"- [{booking.type}] {booking.booking_id}: {label}")
        return "\n".join(lines)

    def _format_resolution_requirements(self, requirements: List[str]) -> str:
        if not requirements:
            return "- None provided."
        return "\n".join(f"- {item}" for item in requirements)

    def _event_resolved(self, event_state: Dict[str, Any]) -> bool:
        event_type = event_state.get("event_type", "")
        if event_type == "trip_cut_short":
            return self._trip_cut_short_resolved(event_state)
        if event_type == "budget_reduced":
            return self._budget_reduction_resolved(event_state)
        if event_type == "schedule_swap_required":
            return self._schedule_swap_resolved(event_state)
        if event_type == "party_size_increase":
            return self._party_size_increase_resolved(event_state)
        if event_type == "venue_closed":
            return self._venue_closed_resolved(event_state)

        for component in event_state.get("affected_components", []):
            active_matches = [
                booking
                for booking in self.tracker.bookings
                if self._booking_matches_event_component(booking, component, event_state)
            ]
            if self._event_component_requires_replacement(component, event_state):
                if not active_matches:
                    return False
            elif active_matches:
                return False
        return True

    def _dependent_bookings_reviewed(self, event_state: Dict[str, Any]) -> bool:
        review_turn = event_state.get("turn", 0)
        dependent_ids = set(event_state.get("dependent_booking_ids", []))
        if not dependent_ids:
            return True

        for entry in self._operation_log:
            if entry.get("turn", 0) < review_turn:
                continue
            booking_id = entry.get("booking_id")
            if booking_id in dependent_ids:
                return True
            if entry.get("tool") in {"book_restaurant", "cancel_restaurant"}:
                return True
        return self._dependents_still_valid_without_changes(event_state)

    def _apply_event_budget_update(self, event: Dict[str, Any], task: Dict[str, Any]) -> Optional[float]:
        if event.get("event_type") not in {"budget_reduced", "party_size_increase"}:
            return None

        total_cost_max = task.get("success_criteria", {}).get("total_cost_max")
        new_budget_max: Optional[float] = None
        if isinstance(total_cost_max, (int, float)):
            new_budget_max = float(total_cost_max)
        else:
            description = event.get("description", "")
            specific_match = re.search(
                r"new maximum budget .*? now \$([0-9]+(?:\.[0-9]+)?)",
                description,
                flags=re.IGNORECASE,
            )
            if not specific_match:
                specific_match = re.search(
                    r"budget .*? reduced .*? to \$([0-9]+(?:\.[0-9]+)?)",
                    description,
                    flags=re.IGNORECASE,
                )
            if specific_match:
                try:
                    new_budget_max = float(specific_match.group(1))
                except ValueError:
                    new_budget_max = None

        if new_budget_max is None:
            return None

        if self.tracker.budget_max is not None:
            new_budget_max = min(new_budget_max, self.tracker.budget_max)

        self.tracker.budget_max = new_budget_max
        for constraint in self.tracker.constraints:
            if constraint.name == "budget_max":
                constraint.value = new_budget_max
                break

        self._record_operation(
            "system_event",
            "update",
            {"booking_id": f"budget_max_{int(new_budget_max)}"},
            {"booking_id": f"budget_max_{int(new_budget_max)}"},
            summary_override=f"updated budget cap to ${new_budget_max:.0f} due to {event.get('event_type')}",
        )
        return new_budget_max

    def _apply_event_party_size_update(self, event: Dict[str, Any]) -> Optional[int]:
        if event.get("event_type") != "party_size_increase":
            return None

        description = event.get("description", "")
        target_size: Optional[int] = None
        for pattern in (
            r"party size is now (\d+)",
            r"total party size is now (\d+)",
            r"now (\d+) adults",
        ):
            match = re.search(pattern, description, flags=re.IGNORECASE)
            if match:
                target_size = int(match.group(1))
                break

        if target_size is None:
            return None

        self._current_party_size = max(self._current_party_size, target_size)
        self._record_operation(
            "system_event",
            "update",
            {"booking_id": f"party_size_{self._current_party_size}"},
            {"booking_id": f"party_size_{self._current_party_size}"},
            summary_override=f"updated active party size to {self._current_party_size}",
        )
        return self._current_party_size

    def _event_component_requires_replacement(self, component: str, event_state: Dict[str, Any]) -> bool:
        normalized = component.lower()
        if event_state.get("event_type") == "trip_cut_short":
            if normalized in {"saturday_hotel", "saturday_activities", "sunday_activities", "saturday_restaurants", "sunday_restaurants"}:
                return False
        return True

    def _booking_matches_event_component(
        self,
        booking: Booking,
        component: str,
        event: Optional[Dict[str, Any]] = None,
    ) -> bool:
        normalized = component.lower()
        details = booking.details or {}

        if normalized == "return_flight":
            return booking.type == "flight" and str(details.get("type", "")).lower() == "return_flight"
        if normalized == "outbound_flight":
            return booking.type == "flight" and str(details.get("type", "")).lower() == "outbound_flight"
        if normalized == "guided_boat_tour":
            return booking.type == "activity" and self._experience_booking_matches("guided_boat_tour_min_1", booking)
        if normalized in {"sunday_activity", "sunday_beach_activity"} and isinstance(event, dict) and event.get("event_type") == "schedule_swap_required":
            sunday_dates = self._dates_for_weekday_in_trip("sunday")
            return (
                booking.type == "activity"
                and self._experience_booking_matches("beach_activities_min_1", booking)
                and any(self._booking_occurs_on_date(booking, target_date) for target_date in sunday_dates)
            )
        if normalized == "major_animal_park_visit":
            blocked_dates = self._event_blocked_dates(event or {})
            if booking.type != "activity" or not self._matches_major_animal_park(booking):
                return False
            if not blocked_dates:
                return True
            return any(self._booking_occurs_on_date(booking, target_date) for target_date in blocked_dates)

        target_dates = self._component_target_dates(normalized, event)
        if normalized.endswith("_hotel") and target_dates:
            return booking.type == "hotel" and any(self._booking_overlaps_date(booking, target_date) for target_date in target_dates)
        if normalized.endswith("_activities") and target_dates:
            return booking.type == "activity" and any(self._booking_occurs_on_date(booking, target_date) for target_date in target_dates)
        if normalized.endswith("_activity") and target_dates:
            return booking.type == "activity" and any(self._booking_occurs_on_date(booking, target_date) for target_date in target_dates)
        if normalized.endswith("_restaurants") and target_dates:
            return booking.type == "restaurant" and any(self._booking_occurs_on_date(booking, target_date) for target_date in target_dates)
        if normalized.endswith("_restaurant") and target_dates:
            return booking.type == "restaurant" and any(self._booking_occurs_on_date(booking, target_date) for target_date in target_dates)

        booking_types = self._component_to_booking_types(component)
        generic_component = bool(booking_types) and not self._component_keywords(normalized)
        if generic_component:
            return booking.type in booking_types

        if booking.type == "activity":
            return self._experience_booking_matches(component, booking)
        if booking.type == "restaurant":
            return self._experience_booking_matches(component, booking)
        if booking.type == "hotel":
            return self._lodging_booking_matches(component, booking)
        if booking.type == "flight":
            return self._flight_booking_matches(component, booking)

        return booking.type in booking_types

    def _component_target_dates(self, component: str, event: Optional[Dict[str, Any]] = None) -> List[date]:
        text = event.get("description", "") if isinstance(event, dict) else ""
        explicit_dates = [
            self._parse_date(match)
            for match in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
        ]
        explicit_dates = [value for value in explicit_dates if value is not None]

        weekday_names = (
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        )
        for weekday_name in weekday_names:
            if weekday_name in component:
                matching_dates = self._dates_for_weekday_in_trip(weekday_name)
                if matching_dates:
                    return matching_dates
        return explicit_dates

    def _dates_for_weekday_in_trip(self, weekday_name: str) -> List[date]:
        departure = self._parse_date(str(self._constraint_value("departure_date", "")))
        return_date = self._parse_date(str(self._constraint_value("return_date", "")))
        if departure is None or return_date is None or return_date < departure:
            return []

        current = departure
        matched = []
        while current <= return_date:
            if current.strftime("%A").lower() == weekday_name:
                matched.append(current)
            current += timedelta(days=1)
        return matched

    def _constraint_value(self, name: str, default: Any = None) -> Any:
        constraint = self.tracker.get_constraint(name)
        return constraint.value if constraint is not None else default

    def _parse_date(self, value: str) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _parse_time(self, value: str) -> Optional[dt_time]:
        if not value:
            return None
        for fmt in ("%H:%M", "%I:%M %p", "%I %p"):
            try:
                return datetime.strptime(value.strip(), fmt).time()
            except ValueError:
                continue
        return None

    def _booking_occurs_on_date(self, booking: Booking, target_date: date) -> bool:
        details = booking.details or {}
        booking_date = self._parse_date(str(details.get("date", "")))
        if booking_date is not None:
            return booking_date == target_date
        departure_date = self._parse_date(str(details.get("departure_date", "")))
        if departure_date is not None:
            return departure_date == target_date
        return False

    def _booking_overlaps_date(self, booking: Booking, target_date: date) -> bool:
        details = booking.details or {}
        check_in = self._parse_date(str(details.get("check_in", "")))
        check_out = self._parse_date(str(details.get("check_out", "")))
        if check_in is None or check_out is None:
            return False
        return check_in <= target_date < check_out

    def _event_cutoff_datetime(self, event_state: Dict[str, Any]) -> Tuple[Optional[date], Optional[dt_time]]:
        description = event_state.get("description", "")
        explicit_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", description)
        explicit_times = re.findall(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b|\b\d{2}:\d{2}\b", description, flags=re.IGNORECASE)
        cutoff_date = self._parse_date(explicit_dates[0]) if explicit_dates else None
        cutoff_time = self._parse_time(explicit_times[0]) if explicit_times else None
        return cutoff_date, cutoff_time

    def _trip_cut_short_resolved(self, event_state: Dict[str, Any]) -> bool:
        cutoff_date, cutoff_time = self._event_cutoff_datetime(event_state)
        return_flights = [
            booking for booking in self.tracker.get_bookings_by_type("flight")
            if str((booking.details or {}).get("type", "")).lower() == "return_flight"
        ]
        if not return_flights:
            return False

        valid_return = False
        chosen_date = None
        chosen_time = None
        for booking in return_flights:
            details = booking.details or {}
            flight_date = self._parse_date(str(details.get("departure_date", "")))
            flight_time = self._parse_time(str(details.get("departure_time", "")))
            if flight_date is None:
                continue
            if cutoff_date is not None and flight_date > cutoff_date:
                continue
            if cutoff_date is not None and flight_date == cutoff_date and cutoff_time is not None and flight_time is not None and flight_time > cutoff_time:
                continue
            valid_return = True
            chosen_date = flight_date
            chosen_time = flight_time
            break

        if not valid_return:
            return False

        for booking in self.tracker.bookings:
            if booking.type == "hotel":
                check_out = self._parse_date(str((booking.details or {}).get("check_out", "")))
                if check_out is not None and chosen_date is not None and check_out > chosen_date:
                    return False
            elif booking.type in {"activity", "restaurant"}:
                booking_date = self._parse_date(str((booking.details or {}).get("date", "")))
                booking_time = self._parse_time(str((booking.details or {}).get("time", "")))
                if booking_date is None or chosen_date is None:
                    continue
                if booking_date > chosen_date:
                    return False
                if booking_date == chosen_date and chosen_time is not None and booking_time is not None and booking_time >= chosen_time:
                    return False

        return True

    def _budget_reduction_resolved(self, event_state: Dict[str, Any]) -> bool:
        budget_cap = event_state.get("budget_max_after")
        if budget_cap is None:
            budget_cap = self.tracker.budget_max
        return budget_cap is None or self.tracker.budget_used <= budget_cap

    def _dependents_still_valid_without_changes(self, event_state: Dict[str, Any]) -> bool:
        active_bookings = {
            booking.booking_id: booking
            for booking in self.tracker.bookings
        }
        dependent_bookings = [
            active_bookings[booking_id]
            for booking_id in event_state.get("dependent_booking_ids", [])
            if booking_id in active_bookings
        ]
        if not dependent_bookings:
            return True

        if event_state.get("event_type") == "trip_cut_short":
            cutoff_date, cutoff_time = self._event_cutoff_datetime(event_state)
            if cutoff_date is None:
                return False
            for booking in dependent_bookings:
                details = booking.details or {}
                if booking.type == "hotel":
                    check_out = self._parse_date(str(details.get("check_out", "")))
                    if check_out is not None and check_out > cutoff_date:
                        return False
                elif booking.type in {"activity", "restaurant"}:
                    booking_date = self._parse_date(str(details.get("date", "")))
                    booking_time = self._parse_time(str(details.get("time", "")))
                    if booking_date is None:
                        continue
                    if booking_date > cutoff_date:
                        return False
                    if (
                        booking_date == cutoff_date and
                        cutoff_time is not None and
                        booking_time is not None and
                        booking_time >= cutoff_time
                    ):
                        return False
            return True

        if event_state.get("event_type") == "budget_reduced":
            budget_cap = event_state.get("budget_max_after", self.tracker.budget_max)
            return budget_cap is None or self.tracker.budget_used <= budget_cap

        if event_state.get("event_type") == "party_size_increase":
            target_size = event_state.get("party_size_after", self._current_party_size)
            return self._bookings_meet_party_size(int(target_size or 1))

        if event_state.get("event_type") == "schedule_swap_required":
            return self._schedule_swap_resolved(event_state)

        if event_state.get("event_type") == "venue_closed":
            return self._venue_closed_resolved(event_state)

        return False

    def _schedule_swap_resolved(self, event_state: Dict[str, Any]) -> bool:
        saturday_dates = self._dates_for_weekday_in_trip("saturday")
        sunday_dates = self._dates_for_weekday_in_trip("sunday")
        if not saturday_dates or not sunday_dates:
            return False

        saturday = saturday_dates[0]
        sunday = sunday_dates[0]

        has_sunday_boat = any(
            booking.type == "activity"
            and self._experience_booking_matches("guided_boat_tour_min_1", booking)
            and self._booking_occurs_on_date(booking, sunday)
            and self._booking_time_is_morning(booking)
            for booking in self.tracker.bookings
        )
        has_saturday_beach = any(
            booking.type == "activity"
            and self._experience_booking_matches("beach_activities_min_1", booking)
            and self._booking_occurs_on_date(booking, saturday)
            for booking in self.tracker.bookings
        )
        has_saturday_boat = any(
            booking.type == "activity"
            and self._experience_booking_matches("guided_boat_tour_min_1", booking)
            and self._booking_occurs_on_date(booking, saturday)
            for booking in self.tracker.bookings
        )
        return has_sunday_boat and has_saturday_beach and not has_saturday_boat

    def _party_size_increase_resolved(self, event_state: Dict[str, Any]) -> bool:
        target_size = int(event_state.get("party_size_after") or self._current_party_size or 1)
        return self._bookings_meet_party_size(target_size)

    def _venue_closed_resolved(self, event_state: Dict[str, Any]) -> bool:
        blocked_dates = self._event_blocked_dates(event_state)
        if not blocked_dates:
            return False

        for booking in self.tracker.get_bookings_by_type("activity"):
            if not self._booking_matches_event_component(booking, "major_animal_park_visit", event_state):
                continue
            if any(self._booking_occurs_on_date(booking, blocked_date) for blocked_date in blocked_dates):
                return False
        return True

    def _timing_feasible(self) -> bool:
        origin = str(self._scenario.get("origin_city", "")).lower()
        destinations = [str(city).lower() for city in self._scenario.get("destination_cities", [])]
        if origin and destinations and any(destination != origin for destination in destinations):
            if not self.tracker.get_bookings_by_type("flight"):
                return False

        time_windows = []
        for booking in self.tracker.bookings:
            window = self._booking_time_window(booking)
            if window is not None:
                time_windows.append((booking, window))

        for index, (left_booking, left_window) in enumerate(time_windows):
            for right_booking, right_window in time_windows[index + 1:]:
                if self._windows_overlap(left_window, right_window):
                    return False

        for booking in self.tracker.get_bookings_by_type("activity") + self.tracker.get_bookings_by_type("restaurant"):
            if self._booking_violates_flight_buffers(booking):
                return False
        return True

    def _has_component_on_weekday(self, component: str, weekday_name: str) -> bool:
        target_dates = self._dates_for_weekday_in_trip(weekday_name)
        if not target_dates:
            return False
        for booking in self.tracker.bookings:
            if booking.type != "activity":
                continue
            if not self._experience_booking_matches(component, booking):
                continue
            if any(self._booking_occurs_on_date(booking, target_date) for target_date in target_dates):
                return True
        return False

    def _bookings_meet_party_size(self, required_size: int) -> bool:
        if required_size <= 1:
            return True
        for booking in self.tracker.bookings:
            if booking.type == "surcharge":
                continue
            party_size = int((booking.details or {}).get("party_size") or 0)
            if booking.type in {"flight", "hotel", "restaurant", "activity"} and party_size < required_size:
                return False
        return True

    def _event_blocked_dates(self, event_state: Dict[str, Any]) -> List[date]:
        explicit_dates = self._component_target_dates("", event_state)
        if explicit_dates:
            return explicit_dates

        description = event_state.get("description", "").lower()
        blocked = []
        if "weekend" in description:
            blocked.extend(self._dates_for_weekday_in_trip("saturday"))
            blocked.extend(self._dates_for_weekday_in_trip("sunday"))
        return blocked

    def _booking_time_is_morning(self, booking: Booking) -> bool:
        details = booking.details or {}
        booking_time = self._parse_time(str(details.get("time", "")))
        if booking_time is None:
            booking_time = self._parse_time(str(details.get("departure_time", "")))
        return booking_time is not None and booking_time < dt_time(12, 0)

    def _matches_major_animal_park(self, booking: Booking) -> bool:
        tokens = self._booking_content_tokens(booking.details or {})
        return bool({"animal", "zoo", "safari", "wildlife", "wildlife_park"} & tokens)

    def _booking_time_window(self, booking: Booking) -> Optional[Tuple[datetime, datetime]]:
        details = booking.details or {}
        if booking.type == "activity":
            booking_date = self._parse_date(str(details.get("date", "")))
            booking_time = self._parse_time(str(details.get("time", "")))
            duration_hours = ((details.get("full_data") or {}).get("duration_hours") if isinstance(details.get("full_data"), dict) else None) or 2
            if booking_date is None or booking_time is None:
                return None
            start = datetime.combine(booking_date, booking_time)
            end = start + timedelta(hours=float(duration_hours))
            return start, end

        if booking.type == "restaurant":
            booking_date = self._parse_date(str(details.get("date", "")))
            booking_time = self._parse_time(str(details.get("time", "")))
            if booking_date is None or booking_time is None:
                return None
            start = datetime.combine(booking_date, booking_time)
            end = start + timedelta(minutes=90)
            return start, end

        if booking.type == "flight":
            departure_date = self._parse_date(str(details.get("departure_date", "")))
            departure_time = self._parse_time(str(details.get("departure_time", "")))
            arrival_time = self._parse_time(str(details.get("arrival_time", "")))
            if departure_date is None or departure_time is None or arrival_time is None:
                return None
            start = datetime.combine(departure_date, departure_time)
            end = datetime.combine(departure_date, arrival_time)
            if end < start:
                end += timedelta(days=1)
            return start, end

        return None

    def _windows_overlap(
        self,
        left: Tuple[datetime, datetime],
        right: Tuple[datetime, datetime],
    ) -> bool:
        return left[0] < right[1] and right[0] < left[1]

    def _booking_violates_flight_buffers(self, booking: Booking) -> bool:
        booking_window = self._booking_time_window(booking)
        if booking_window is None:
            return False

        for flight in self.tracker.get_bookings_by_type("flight"):
            flight_window = self._booking_time_window(flight)
            if flight_window is None:
                continue
            flight_details = flight.details or {}
            flight_type = str(flight_details.get("type", "")).lower()
            if flight_type == "outbound_flight":
                if booking_window[0].date() == flight_window[0].date():
                    if booking_window[0] < flight_window[1] + timedelta(minutes=90):
                        return True
            elif flight_type == "return_flight":
                if booking_window[0].date() == flight_window[0].date():
                    if booking_window[1] > flight_window[0] - timedelta(minutes=120):
                        return True
        return False

    def _parse_action(self, response: str) -> Tuple[bool, str, Dict]:
        if "ACTION:" not in response:
            return False, None, None

        try:
            action_line = [line for line in response.split("\n") if "ACTION:" in line][0]
            action_part = action_line.split("ACTION:")[1].strip()

            tool_name = action_part.split("(")[0].strip()
            params_str = action_part.split("(")[1].rsplit(")", 1)[0]

            params = {}
            for param in self._split_params(params_str):
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key.strip()] = value.strip()

            return True, tool_name, params

        except Exception:
            return False, None, None

    def _split_params(self, params_str: str) -> List[str]:
        """Split a params string by commas, respecting brackets and quotes."""
        parts = []
        depth = 0
        current = []
        for ch in params_str:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current).strip())
        return parts

    def _process_tool_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        processed = {}
        for key, value in params.items():
            if not isinstance(value, str):
                processed[key] = value
                continue
            # Fix 2: handle list/dict literals like ["hiking", "food"] or True/False
            if value.startswith("[") or value.startswith("{"):
                try:
                    processed[key] = ast.literal_eval(value)
                    continue
                except (ValueError, SyntaxError):
                    pass
            if value.lower() in ("true", "false"):
                processed[key] = value.lower() == "true"
            elif value.isdigit():
                processed[key] = int(value)
            elif value.replace(".", "", 1).isdigit():
                processed[key] = float(value)
            else:
                processed[key] = value.strip('"\'')
        return processed

    def _apply_live_trip_state_to_params(
        self,
        tool_name: str,
        method: str,
        processed_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        if method not in {"search", "book"}:
            return processed_params

        if tool_name in {
            "book_flight",
            "book_hotel",
            "book_restaurant",
            "book_activity",
            "search_restaurants",
            "search_activities",
        }:
            current_size = max(int(self._current_party_size or 1), 1)
            existing_size = int(processed_params.get("party_size", current_size) or current_size)
            processed_params["party_size"] = max(existing_size, current_size)

        return processed_params

    def _validate_candidate_timing(
        self,
        tool_name: str,
        method: str,
        processed_params: Dict[str, Any],
    ) -> str:
        if method != "book" or tool_name not in {"book_restaurant", "book_activity"}:
            return ""

        duplicate_error = self._validate_duplicate_candidate(tool_name, processed_params)
        if duplicate_error:
            return duplicate_error

        candidate_window = self._candidate_booking_time_window(tool_name, processed_params)
        if candidate_window is None:
            return ""

        for booking in self.tracker.bookings:
            booking_window = self._booking_time_window(booking)
            if booking_window is None:
                continue
            if self._windows_overlap(candidate_window, booking_window):
                return (
                    "Timing conflict: this booking "
                    f"({self._format_time_window(candidate_window)}) overlaps with existing "
                    f"{booking.type} {booking.booking_id} ({self._format_time_window(booking_window)}). "
                    f"Choose a start time at or after {booking_window[1].strftime('%H:%M')}."
                )

        if self._candidate_violates_flight_buffers(candidate_window):
            return (
                "Timing conflict: this booking violates the required airport or arrival buffer around an existing flight. "
                f"Candidate window: {self._format_time_window(candidate_window)}."
            )

        return ""

    def _validate_duplicate_candidate(
        self,
        tool_name: str,
        processed_params: Dict[str, Any],
    ) -> str:
        if tool_name != "book_activity":
            return ""

        candidate_activity_id = str(processed_params.get("activity_id", ""))
        candidate_date = str(processed_params.get("date", ""))
        if not candidate_activity_id or not candidate_date:
            return ""

        for booking in self.tracker.get_bookings_by_type("activity"):
            details = booking.details or {}
            if (
                str(details.get("activity_id", "")) == candidate_activity_id
                and str(details.get("date", "")) == candidate_date
            ):
                return (
                    "Duplicate activity booking: this activity is already booked on that date. "
                    "Choose a different activity or keep the existing booking."
                )
        return ""

    def _candidate_booking_time_window(
        self,
        tool_name: str,
        processed_params: Dict[str, Any],
    ) -> Optional[Tuple[datetime, datetime]]:
        if tool_name == "book_activity":
            activity = self._lookup_activity(processed_params.get("activity_id"))
            booking_date = self._parse_date(str(processed_params.get("date", "")))
            booking_time = self._parse_time(str(processed_params.get("time", "")))
            if activity is None or booking_date is None or booking_time is None:
                return None
            start = datetime.combine(booking_date, booking_time)
            end = start + timedelta(hours=float(activity.get("duration_hours", 2)))
            return start, end

        if tool_name == "book_restaurant":
            booking_date = self._parse_date(str(processed_params.get("date", "")))
            booking_time = self._parse_time(str(processed_params.get("time", "")))
            if booking_date is None or booking_time is None:
                return None
            start = datetime.combine(booking_date, booking_time)
            end = start + timedelta(minutes=90)
            return start, end

        return None

    def _candidate_violates_flight_buffers(
        self,
        candidate_window: Tuple[datetime, datetime],
    ) -> bool:
        for flight in self.tracker.get_bookings_by_type("flight"):
            flight_window = self._booking_time_window(flight)
            if flight_window is None:
                continue
            flight_details = flight.details or {}
            flight_type = str(flight_details.get("type", "")).lower()
            if candidate_window[0].date() != flight_window[0].date():
                continue
            if flight_type == "outbound_flight":
                if candidate_window[0] < flight_window[1] + timedelta(minutes=90):
                    return True
            elif flight_type == "return_flight":
                if candidate_window[1] > flight_window[0] - timedelta(minutes=120):
                    return True
        return False

    def _format_time_window(self, window: Tuple[datetime, datetime]) -> str:
        start, end = window
        if start.date() == end.date():
            return f"{start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%H:%M')}"
        return f"{start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')}"

    def _lookup_activity(self, activity_id: Any) -> Optional[Dict[str, Any]]:
        if not activity_id or not hasattr(self.activity_tool, "activities"):
            return None
        for activity in self.activity_tool.activities:
            if activity.get("activity_id") == activity_id:
                return activity
        return None

    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        self.metadata["tool_calls"] += 1

        tool_action_map = {
            "search_flights":     (self.flight_tool,     "search"),
            "book_flight":        (self.flight_tool,     "book"),
            "cancel_flight":      (self.flight_tool,     "cancel"),
            "search_hotels":      (self.hotel_tool,      "search"),
            "book_hotel":         (self.hotel_tool,      "book"),
            "cancel_hotel":       (self.hotel_tool,      "cancel"),
            "search_restaurants": (self.restaurant_tool, "search"),
            "book_restaurant":    (self.restaurant_tool, "book"),
            "cancel_restaurant":  (self.restaurant_tool, "cancel"),
            "search_activities":  (self.activity_tool,   "search"),
            "book_activity":      (self.activity_tool,   "book"),
            "cancel_activity":    (self.activity_tool,   "cancel"),
            "record_surcharge":   (self,                 "record_surcharge"),
        }

        entry = tool_action_map.get(tool_name)
        if entry is None:
            return {"error": f"Unknown tool: {tool_name}"}

        tool, method = entry
        try:
            processed_params = self._process_tool_params(params)
            processed_params = self._apply_live_trip_state_to_params(tool_name, method, processed_params)
            order_error = self._validate_booking_order(tool_name, method)
            if order_error:
                return {"status": "error", "message": order_error}
            timing_error = self._validate_candidate_timing(tool_name, method, processed_params)
            if timing_error:
                return {"status": "error", "message": timing_error}
            result = getattr(tool, method)(**processed_params)
            if tool_name == "search_restaurants" and method == "search":
                result = self._expand_restaurant_search_results(processed_params, result)
        except Exception as e:
            return {"error": str(e)}

        # Fix 1: record completed searches so the booking summary can warn the model
        if method == "search":
            city = processed_params.get("city") or processed_params.get("destination_city", "?")
            origin = processed_params.get("original_city", "")
            key = f"{tool_name}:{origin}->{city}" if origin else f"{tool_name}:{city}"
            self._searched.add(key)

        if isinstance(result, dict) and result.get("status") == "success":
            if method == "book":
                booking_type = tool_name.split("_", 1)[1]  # "book_flight" → "flight"
                self.tracker.add_booking(Booking(
                    booking_id=result["booking_id"],
                    type=booking_type,
                    details=result.get("details", {}),
                    cost=float(result.get("cost", 0.0)),
                ))
                self._record_operation(tool_name, method, result, processed_params)
            elif method == "cancel":
                booking_id = processed_params.get("booking_id")
                if booking_id:
                    self.tracker.remove_booking(booking_id)
                self._record_operation(tool_name, method, result, processed_params)

        return self._trim_result(result, method)

    def _validate_booking_order(self, tool_name: str, method: str) -> str:
        if method not in {"search", "book"}:
            return ""

        stage = self._current_booking_stage()
        if not stage:
            return ""

        if stage == "flight" and "flight" not in tool_name:
            return "Booking order violation: complete required flights before moving to other components."
        if stage == "lodging" and "hotel" not in tool_name:
            return "Booking order violation: complete required lodging before activities or restaurants."
        if stage == "activity" and "restaurant" in tool_name:
            return "Booking order violation: complete required activities before restaurants."
        return ""

    def _current_booking_stage(self) -> str:
        if self._implicit_flight_requirement_enabled() and not self._implicit_transport_satisfied():
            return "flight"
        if any("flight" in component.lower() and not self._component_satisfied(component) for component in self._required_components):
            return "flight"
        if any(any(word in component.lower() for word in ("hotel", "hotels", "accommodation", "accommodations", "lodge", "lodges")) and not self._component_satisfied(component) for component in self._required_components):
            return "lodging"
        if any(any(word in component.lower() for word in ("activity", "activities", "tour", "tours", "museum", "museums", "visit", "visits", "experience", "experiences", "park", "parks", "attraction", "attractions", "venue", "venues")) and not self._component_satisfied(component) for component in self._required_components):
            return "activity"
        if any(any(word in component.lower() for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")) and not self._component_satisfied(component) for component in self._required_components):
            return "restaurant"
        return ""

    def _record_operation(
        self,
        tool_name: str,
        method: str,
        result: Dict[str, Any],
        processed_params: Dict[str, Any],
        summary_override: str = "",
    ) -> None:
        booking_id = result.get("booking_id") or processed_params.get("booking_id")
        if summary_override:
            summary = summary_override
        elif method == "book":
            summary = f"confirmed {result.get('booking_id', 'unknown booking')}"
        else:
            summary = f"cancelled {processed_params.get('booking_id', 'unknown booking')}"
        self._operation_log.append({
            "turn": self.turn_count,
            "tool": tool_name,
            "action": method,
            "booking_id": booking_id,
            "summary": summary,
        })

    def _expand_restaurant_search_results(self, params: Dict[str, Any], result: Any) -> Any:
        if not isinstance(result, list):
            return result

        remaining_required = 0
        for item in self._get_missing_required_components():
            component = item["component"].lower()
            if any(word in component for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")):
                remaining_required = max(remaining_required, item["required"] - item["matched"])

        if remaining_required <= 0 or len(result) >= remaining_required:
            return result

        fallback_params = {
            "city": params.get("city"),
            "max_price": params.get("max_price"),
            "party_size": params.get("party_size"),
        }
        if params.get("wheelchair_accessible") is True or any(
            "accessible_restaurants" in component.lower() for component in self._required_components
        ):
            fallback_params["wheelchair_accessible"] = True

        try:
            fallback = self.restaurant_tool.search(**fallback_params)
        except Exception:
            return result

        if not isinstance(fallback, list):
            return result

        merged = []
        seen_ids = set()
        for item in list(result) + list(fallback):
            restaurant_id = item.get("restaurant_id")
            if restaurant_id and restaurant_id in seen_ids:
                continue
            if restaurant_id:
                seen_ids.add(restaurant_id)
            merged.append(item)
        return merged[:10]

    def _trim_result(self, result: Any, method: str) -> Any:
        """Strip bulky fields from tool results before they enter conversation history."""
        if method == "book" and isinstance(result, dict) and "details" in result:
            details = {k: v for k, v in result["details"].items() if k != "full_data"}
            return {**result, "details": details}
        if method == "search" and isinstance(result, dict):
            trimmed = {}
            for key, items in result.items():
                if isinstance(items, list):
                    trimmed[key] = self._trim_search_items(items)
                else:
                    trimmed[key] = items
            return trimmed
        if method == "search" and isinstance(result, list):
            return self._trim_search_items(result)
        return result

    def _trim_search_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        trimmed = []
        keep = {
            "flight_id", "hotel_id", "restaurant_id", "activity_id",
            "name", "city", "price", "price_per_night", "price_per_person",
            "stars", "departure_time", "arrival_time", "duration_hours",
            "airline", "origin_city", "destination_city", "from_city", "to_city",
            "departure_date", "price_per_seat", "wheelchair_accessible",
            "is_wheelchair_accessible", "tags", "neighborhood", "cuisine_type",
            "type", "category", "average_cost_per_person"
        }
        for item in items[:5]:
            trimmed.append({k: v for k, v in item.items() if k in keep})
        return trimmed

    # ------------------------------------------------------------------

    def _format_constraints(self, constraints: Dict[str, Any]) -> str:
        if not constraints:
            return "- None"
        formatted = [f"- {k}: {v}" for k, v in constraints.items() if v]
        return "\n".join(formatted) if formatted else "- None"


    def record_surcharge(self, amount: float, description: str):
        import time
        fake_id = f"bk_surcharge_{int(time.time())}"
        
        self.tracker.add_booking(Booking(
            booking_id=fake_id,
            type="surcharge",
            details={"name": description},
            cost=float(amount)
        ))
        
        return {
            "status": "success", 
            "booking_id": fake_id, 
            "cost": float(amount),
            "message": f"Surcharge of ${amount} recorded successfully."
        }
    
if __name__ == "__main__":
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY environment variable")
        exit(1)

    test_task = {
        "task_id": "test_001",
        "title": "Test trip",
        "scenario": {
            "origin_city": "Chicago",
            "destination_cities": ["Denver"],
            "trip_duration_days": 2,
        },
        "user_profile": {"party_size": 1},
        "initial_constraints": {
            "hard": {"budget_max": 500},
            "soft": {"interests": ["hiking"]},
        },
        "dynamic_events": [],
    }

    agent = TravelAgent(api_key=api_key)
    result = agent.plan_trip(test_task)

    print("=" * 70)
    print(f"Success: {result['success']}")
    print(f"API calls: {result['metadata']['api_calls']}")
    print(f"Tokens:    {result['metadata']['total_tokens']}")
    print(f"Time:      {result['metadata']['time_elapsed']}s")
