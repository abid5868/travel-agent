"""
src/agent.py - Travel Planning Agent with ReAct Loop
"""

import ast
import json
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

        return {
            "itinerary": itinerary,
            "conversation": self.conversation_history,
            "metadata": self.metadata,
            "success": bool(itinerary and "FINAL ITINERARY" in itinerary),
        }

    def _load_constraints(self, task: Dict[str, Any]):
        hard = task.get("initial_constraints", {}).get("hard", {})
        soft = task.get("initial_constraints", {}).get("soft", {})
        for key, value in hard.items():
            self.tracker.add_constraint(key, value, is_hard=True)
        for key, value in soft.items():
            self.tracker.add_constraint(key, value, is_hard=False)
        self._required_components = task.get("required_components", [])

    def _create_planning_prompt(self, task: Dict[str, Any]) -> str:
        return create_planning_prompt(task)

    # ------------------------------------------------------------------

    def _react_planning_loop(self, prompt: str, task: Dict[str, Any], max_iterations: int = 20) -> str:
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

                if isinstance(tool_result, dict) and "error" in tool_result:
                    observation = ERROR_HANDLING_PROMPT.format(error_message=tool_result["error"])
                else:
                    observation = f"TOOL RESULT from {tool_name}:\n{json.dumps(tool_result, indent=2)}"

                self.conversation_history.append({"role": "user", "content": observation})
                user_message_added = True

                # Fire dynamic events at their trigger turn regardless of action state.
                due = [e for e in pending_events if self.turn_count >= e.get("trigger_turn", 999)]
                for event in due:
                    pending_events.remove(event)
                    print(f"  [iter {iteration}] DYNAMIC EVENT: {event.get('event_type')}", flush=True)
                    replanning_prompt = self._handle_dynamic_event(event, response, task)
                    self.conversation_history.append({"role": "user", "content": replanning_prompt})
                    self._use_full_model = True
                    break  # one event at a time

            else:
                # Fire events that weren't caught during an action turn
                due = [e for e in pending_events if self.turn_count >= e.get("trigger_turn", 999)]
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
            if iteration >= max_iterations - 3:
                final_prompt = create_final_itinerary_prompt(self._build_confirmed_bookings_text())
                self.conversation_history.append({"role": "user", "content": final_prompt})
                self._use_full_model = True
                user_message_added = True

            if not user_message_added:
                self.conversation_history.append({"role": "user", "content": "Continue planning."})

        # Final call — always Sonnet, full tokens
        if self.conversation_history and self.conversation_history[-1]["role"] == "user":
            print(f"  [final] requesting itinerary (sonnet)...", flush=True)
            self._use_full_model = True
            return self._get_agent_response()

        return self.conversation_history[-1]["content"] if self.conversation_history else ""

    def _handle_dynamic_event(self, event: Dict[str, Any], itinerary: str, task: Dict[str, Any]) -> str:
        """Build and return a replanning prompt for a dynamic event."""
        return create_replanning_prompt(
            event,
            itinerary,
            event.get("affected_components", [])
        )

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
            booked_types = {b.type for b in self.tracker.bookings}
            still_needed_types = []
            if "flight" not in booked_types:
                still_needed_types.append("flights (×2 round-trip)")
            if "hotel" not in booked_types:
                still_needed_types.append("hotel")
            if "activity" not in booked_types:
                still_needed_types.append("activities")
            if "restaurant" not in booked_types:
                still_needed_types.append("restaurants")
            budget_lines = [f"Budget remaining: ${remaining:.0f} of ${self.tracker.budget_max:.0f}"]
            if still_needed_types and remaining > 0:
                approx = remaining / max(len(still_needed_types), 1)
                budget_lines.append(f"Still need to spend on: {', '.join(still_needed_types)}")
                budget_lines.append(f"Approx ${approx:.0f} available per remaining category — use this as max_price in searches")
            parts.append("\n".join(budget_lines))

        # --- STILL NEEDED checklist from required_components ---
        if self._required_components:
            booked_ids = {b.booking_id for b in self.tracker.bookings}
            booked_types = [b.type for b in self.tracker.bookings]
            checklist = []
            for component in self._required_components:
                # Map component name to booking type to check if covered
                done = False
                c = component.lower()
                if "flight" in c and booked_types.count("flight") >= (2 if "return" in c or "outbound" in c else 1):
                    done = True
                elif "hotel" in c and "hotel" in booked_types:
                    done = True
                elif "activity" in c and "activity" in booked_types:
                    done = True
                elif "restaurant" in c and "restaurant" in booked_types:
                    done = True
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
        (3000 tokens). Tool-calling turns use streaming with early stop once a complete
        ACTION(...) line is received (700 tokens), avoiding waiting for the full output.
        """
        full = self._use_full_model
        max_tokens = 3000 if full else 700
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
        }

        entry = tool_action_map.get(tool_name)
        if entry is None:
            return {"error": f"Unknown tool: {tool_name}"}

        tool, method = entry
        try:
            processed_params = self._process_tool_params(params)
            result = getattr(tool, method)(**processed_params)
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
            elif method == "cancel":
                booking_id = processed_params.get("booking_id")
                if booking_id:
                    self.tracker.remove_booking(booking_id)

        return self._trim_result(result, method)

    def _trim_result(self, result: Any, method: str) -> Any:
        """Strip bulky fields from tool results before they enter conversation history."""
        if method == "book" and isinstance(result, dict) and "details" in result:
            details = {k: v for k, v in result["details"].items() if k != "full_data"}
            return {**result, "details": details}
        if method == "search" and isinstance(result, list):
            trimmed = []
            keep = {"flight_id", "hotel_id", "restaurant_id", "activity_id",
                    "name", "city", "price", "price_per_night", "price_per_person",
                    "stars", "departure_time", "arrival_time", "duration_hours",
                    "airline", "origin_city", "destination_city", "departure_date",
                    "wheelchair_accessible", "tags", "neighborhood", "cuisine_type",
                    "type", "category"}
            for item in result[:5]:  # cap at 5 results
                trimmed.append({k: v for k, v in item.items() if k in keep})
            return trimmed
        return result

    # ------------------------------------------------------------------

    def _format_constraints(self, constraints: Dict[str, Any]) -> str:
        if not constraints:
            return "- None"
        formatted = [f"- {k}: {v}" for k, v in constraints.items() if v]
        return "\n".join(formatted) if formatted else "- None"


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
