"""
src/agent.py - Travel Planning Agent with ReAct Loop
"""

import ast
import json
import re
import time
from typing import Dict, Any, List, Tuple
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
        for key, value in hard.items():
            self.tracker.add_constraint(key, value, is_hard=True)
        for key, value in soft.items():
            self.tracker.add_constraint(key, value, is_hard=False)
        self._required_components = task.get("required_components", [])
        self._soft_preferences = soft
        self._success_criteria = task.get("success_criteria", {})
        self._scenario = task.get("scenario", {})

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
                        return response

            # Nudge to wrap up when nearing the iteration limit.
            all_required_done = self._all_planning_requirements_satisfied()
            should_optimize = (
                all_required_done and
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
            elif all_required_done or iteration >= max_iterations - 1:
                final_prompt = create_final_itinerary_prompt(
                    self._build_confirmed_bookings_text(),
                    self._build_requirement_status_text(),
                    self._build_operation_log_text(),
                )
                self.conversation_history.append({"role": "user", "content": final_prompt})
                self._use_full_model = True
                user_message_added = True

            if not user_message_added:
                self.conversation_history.append({"role": "user", "content": "Continue planning."})

        # Final call — always Sonnet, full tokens
        if self.conversation_history and self.conversation_history[-1]["role"] == "user":
            print("  [final] requesting itinerary...", flush=True)
            self._use_full_model = True
            return self._get_agent_response()

        return self.conversation_history[-1]["content"] if self.conversation_history else ""

    def _handle_dynamic_event(self, event: Dict[str, Any], itinerary: str, task: Dict[str, Any]) -> str:
        """Build and return a replanning prompt for a dynamic event."""
        affected_components = event.get("affected_components", [])
        affected_bookings = self._find_affected_bookings(affected_components)
        dependent_bookings = self._find_dependent_bookings(affected_components, affected_bookings)

        preserved_booking_ids = [
            booking.booking_id
            for booking in self.tracker.bookings
            if booking.booking_id not in {b.booking_id for b in affected_bookings}
            and booking.booking_id not in {b.booking_id for b in dependent_bookings}
        ]

        removed_booking_ids = []
        event_type = event.get("event_type", "dynamic_event")
        for booking in affected_bookings:
            if booking.type != "hotel":
                continue
            self.hotel_tool.cancel(booking.booking_id)
            self.tracker.remove_booking(booking.booking_id)
            removed_booking_ids.append(booking.booking_id)
            self._record_operation(
                "system_event",
                "cancel",
                {"booking_id": booking.booking_id},
                {"booking_id": booking.booking_id},
                summary_override=f"removed unavailable hotel {booking.booking_id} due to {event_type}",
            )

        self._triggered_events.append({
            "turn": self.turn_count,
            "event_type": event_type,
            "affected_components": list(affected_components),
            "affected_booking_ids": [booking.booking_id for booking in affected_bookings],
            "dependent_booking_ids": [booking.booking_id for booking in dependent_bookings],
            "preserved_booking_ids": preserved_booking_ids,
            "removed_booking_ids": removed_booking_ids,
        })

        return create_replanning_prompt(
            event,
            itinerary,
            affected_components,
            self._format_booking_refs(affected_bookings) if affected_bookings else "None currently booked.",
            self._format_booking_refs(dependent_bookings) if dependent_bookings else "None currently require review.",
            self._format_resolution_requirements(event.get("resolution_requirements", [])),
        )

    def _event_is_ready(self, event: Dict[str, Any]) -> bool:
        if self.turn_count < event.get("trigger_turn", 999):
            return False

        affected_components = event.get("affected_components", [])
        if not affected_components:
            return True

        return bool(self._find_affected_bookings(affected_components))

    def _booking_summary(self) -> str:
        """State injected each turn: confirmed bookings, still-needed checklist, budget, searched queries."""
        parts = []

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
            budget_lines = [f"Budget remaining: ${remaining:.0f} of ${self.tracker.budget_max:.0f}"]
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
            lines.append(
                f"- [{b.type.upper()}] booking_id={b.booking_id}  cost=${b.cost}"
                + (f"  details={json.dumps(b.details)}" if b.details else "")
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

    def _build_operation_log_text(self) -> str:
        if not self._operation_log:
            return "No booking or cancellation operations were recorded."
        return "\n".join(
            f"- turn {entry['turn']}: {entry['action']} {entry['tool']} -> {entry['summary']}"
            for entry in self._operation_log
        )

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
        if any(any(word in component.lower() for word in ("activity", "activities", "tour", "tours", "museum", "museums", "visit", "visits", "experience", "experiences", "park", "parks", "attraction", "attractions", "venue", "venues")) and not self._component_satisfied(component) for component in self._required_components):
            categories.append("required activities")
        if any(any(word in component.lower() for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")) and not self._component_satisfied(component) for component in self._required_components):
            categories.append("required restaurants")
        return categories

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
            return max(
                (
                    1 for booking in self.tracker.get_bookings_by_type("hotel")
                    if self._lodging_booking_matches(component, booking)
                ),
                default=0,
            )
        if any(word in normalized for word in ("restaurant", "restaurants", "dining", "meal", "meals", "brunch", "dinner")):
            return sum(
                1 for booking in self.tracker.get_bookings_by_type("restaurant")
                if self._experience_booking_matches(component, booking)
            )
        if any(word in normalized for word in (
            "activity", "activities", "tour", "tours", "museum", "museums", "visit",
            "visits", "experience", "experiences", "park", "parks", "attraction",
            "attractions", "venue", "venues", "entertainment", "show"
        )):
            return sum(
                1 for booking in self.tracker.get_bookings_by_type("activity")
                if self._experience_booking_matches(component, booking)
            )
        return 0

    def _required_component_target(self, component: str) -> int:
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
                "arriving", "meeting", "arriving_before_meeting"
            } and not token.isdigit()
        }
        route_tokens = set()
        route_tokens.update(self._tokenize_component(str(details.get("origin_city", ""))))
        route_tokens.update(self._tokenize_component(str(details.get("destination_city", ""))))
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

        content_tokens = self._booking_content_tokens(details)
        keywords = self._component_keywords(normalized)
        if not keywords:
            return True
        return bool(keywords & content_tokens)

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
            "outbound", "return", "night", "nights", "or", "all", "both", "after", "before"
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

        total_cost_max = self._success_criteria.get("total_cost_max")
        if total_cost_max is not None and self.tracker.budget_used > total_cost_max:
            return False

        if self._success_criteria.get("timing_feasible") is True:
            origin = str(self._scenario.get("origin_city", "")).lower()
            destinations = [str(city).lower() for city in self._scenario.get("destination_cities", [])]
            if origin and destinations and any(destination != origin for destination in destinations):
                if not self.tracker.get_bookings_by_type("flight"):
                    return False

        if self._success_criteria.get("all_venues_wheelchair_accessible") is True and not self._hard_constraints_satisfied():
            return False

        if self._success_criteria.get("replanning_successful") is True:
            for event_state in self._triggered_events:
                if not self._event_resolved(event_state):
                    return False

        if self._success_criteria.get("unaffected_bookings_preserved") is True:
            active_ids = {booking.booking_id for booking in self.tracker.bookings}
            for event_state in self._triggered_events:
                if not set(event_state["preserved_booking_ids"]).issubset(active_ids):
                    return False

        if self._success_criteria.get("dependent_bookings_updated") is True:
            for event_state in self._triggered_events:
                if event_state["dependent_booking_ids"] and not self._dependent_bookings_reviewed(event_state):
                    return False

        return True

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
        max_tokens = 4096 if full else 700
        messages = self._build_messages()

        try:
            if full:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=messages,
                    system=SYSTEM_PROMPT,
                    timeout=90,
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
            "attractions", "venue", "venues"
        )):
            return {"activity"}
        return set()

    def _find_affected_bookings(self, affected_components: List[str]) -> List[Booking]:
        affected_types = set()
        for component in affected_components:
            affected_types.update(self._component_to_booking_types(component))
        return [booking for booking in self.tracker.bookings if booking.type in affected_types]

    def _find_dependent_bookings(self, affected_components: List[str], affected_bookings: List[Booking]) -> List[Booking]:
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
        for component in event_state.get("affected_components", []):
            booking_types = self._component_to_booking_types(component)
            if not booking_types:
                continue
            if not any(booking.type in booking_types for booking in self.tracker.bookings):
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
            order_error = self._validate_booking_order(tool_name, method)
            if order_error:
                return {"status": "error", "message": order_error}
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
