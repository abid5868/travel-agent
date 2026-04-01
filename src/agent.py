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
    FINAL_ITINERARY_PROMPT,
    create_planning_prompt,
    create_replanning_prompt,
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

            response = self._get_agent_response()
            action_needed, tool_name, tool_params = self._parse_action(response)

            if action_needed:
                tool_result = self._execute_tool(tool_name, tool_params)

                # Fix 5: inject error prompt when tool fails
                if isinstance(tool_result, dict) and "error" in tool_result:
                    observation = ERROR_HANDLING_PROMPT.format(error_message=tool_result["error"])
                else:
                    observation = f"TOOL RESULT from {tool_name}:\n{json.dumps(tool_result, indent=2)}"

                self.conversation_history.append({"role": "user", "content": observation})

            else:
                # Fire any dynamic events due at this turn
                due = [e for e in pending_events if self.turn_count >= e.get("trigger_turn", 999)]
                for event in due:
                    pending_events.remove(event)
                    replanning_prompt = self._handle_dynamic_event(event, response, task)
                    self.conversation_history.append({"role": "user", "content": replanning_prompt})
                    break  # one event at a time

                if not due:
                    if "FINAL ITINERARY" in response:
                        return response
                    # Fix 6: nudge agent to wrap up when nearing the iteration limit
                    if iteration >= max_iterations - 3:
                        self.conversation_history.append({"role": "user", "content": FINAL_ITINERARY_PROMPT})

        return self.conversation_history[-1]["content"] if self.conversation_history else ""

    def _handle_dynamic_event(self, event: Dict[str, Any], itinerary: str, task: Dict[str, Any]) -> str:
        """Build and return a replanning prompt for a dynamic event."""
        return create_replanning_prompt(
            event,
            itinerary,
            event.get("affected_components", [])
        )

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
