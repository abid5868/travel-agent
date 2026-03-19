"""
src/agent.py - Travel Planning Agent with ReAct Loop
"""
 
import json
import time
from typing import Dict, Any, List, Tuple
from anthropic import Anthropic
 
from src.tools.flights import FlightSearchTool
from src.tools.hotels import HotelSearchTool
from src.tools.restaurants import RestaurantSearchTool
from src.tools.activities import ActivitySearchTool
from src.core.constraints import ConstraintTracker
from src.core.validator import Validator
from src.utils.prompts import SYSTEM_PROMPT, create_planning_prompt, create_replanning_prompt



class TravelAgent:
    
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-5-20250514"
        
        self._initialize_tools()
        self.tracker = ConstraintTracker() if ConstraintTracker else None
        self.validator = Validator(self.tracker) if Validator and self.tracker else None
        
        self.conversation_history = []
        self.turn_count = 0
        self.metadata = {
            "total_tokens": 0,
            "api_calls": 0,
            "tool_calls": 0,
            "start_time": None,
            "end_time": None
        }

    
    def _initialize_tools(self):
        """Initialize all available travel planning tools."""

        self.flight_tool = FlightSearchTool("benchmarks/mock_data/flights.json")
        self.hotel_tool = HotelSearchTool("benchmarks/mock_data/hotels.json")
        self.restaurant_tool = RestaurantSearchTool("benchmarks/mock_data/restaurants.json")
        self.activity_tool = ActivitySearchTool("benchmarks/mock_data/activities.json")


    def plan_trip(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Plan a trip based on user task.
        """

        self.metadata["start_time"] = time.time()
        
        self._load_constraints(task)
        initial_prompt = self._create_planning_prompt(task)
        itinerary = self._react_planning_loop(initial_prompt, task)
        
        if task.get("dynamic_events"):
            for event in task["dynamic_events"]:
                if self.turn_count >= event.get("trigger_turn", 999):
                    itinerary = self._handle_dynamic_event(event, itinerary, task)
        
        validation_result = self._validate_itinerary(task)
        
        self.metadata["end_time"] = time.time()
        self.metadata["time_elapsed"] = round(
            self.metadata["end_time"] - self.metadata["start_time"], 2
        )
        
        return {
            "itinerary": itinerary,
            "conversation": self.conversation_history,
            "validation": validation_result,
            "metadata": self.metadata,
            "success": validation_result[0] if validation_result else False
        }
    
    def _load_constraints(self, task: Dict[str, Any]):
        """Load constraints from task."""

        self.constraints = {
            "hard": task.get("initial_constraints", {}).get("hard", {}),
            "soft": task.get("initial_constraints", {}).get("soft", {})
        }
        
        if self.tracker:
            for key, value in self.constraints["hard"].items():
                self.tracker.add_constraint(key, value, is_hard=True)
            for key, value in self.constraints["soft"].items():
                self.tracker.add_constraint(key, value, is_hard=False)



    def _create_planning_prompt(self, task: Dict[str, Any]) -> str:
        """Create planning prompt."""
        return create_planning_prompt(task)
    
    def _react_planning_loop(self, prompt: str, task: Dict[str, Any]) -> str:
        """React planning loop."""
        return self._react_planning_loop(prompt, task)
    
    def _handle_dynamic_event(self, event: Dict[str, Any], itinerary: str, task: Dict[str, Any]) -> str:
        """Handle dynamic event."""
        return self._handle_dynamic_event(event, itinerary, task)
    


    def _get_agent_response(self) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.7,
                messages=self.conversation_history,
                system=SYSTEM_PROMPT if SYSTEM_PROMPT else "You are a travel planning agent."
            )
            
            self.metadata["api_calls"] += 1
            self.metadata["total_tokens"] += response.usage.input_tokens + response.usage.output_tokens
            
            response_text = response.content[0].text
            
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })
            
            return response_text
            
        except Exception as e:
            return f"Error: {e}"


    def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        self.metadata["tool_calls"] += 1
        
        tool_map = {
            "search_flights": self.flight_tool,
            "search_hotels": self.hotel_tool,
            "search_restaurants": self.restaurant_tool,
            "search_activities": self.activity_tool
        }
        
        tool = tool_map.get(tool_name)
        
        if tool is None:
            return {"error": f"Tool {tool_name} not available"}
        
        try:
            processed_params = self._process_tool_params(params)
            result = tool.search(**processed_params)
            return result
        except Exception as e:
            return {"error": str(e)}
    
    def _process_tool_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        processed = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                if value.isdigit():
                    processed[key] = int(value)
                elif value.replace('.', '').isdigit():
                    processed[key] = float(value)
                elif value.lower() in ['true', 'false']:
                    processed[key] = value.lower() == 'true'
                else:
                    processed[key] = value
            else:
                processed[key] = value
        
        return processed



    def _validate_itinerary(self, task: Dict[str, Any]) -> Tuple[bool, List[str]]:
        if not self.conversation_history:
            return False, ["No itinerary generated"]
        
        if self.validator:
            return self.validator.validate_all()
        
        return True, []
    
    def _format_constraints(self, constraints: Dict[str, Any]) -> str:
        if not constraints:
            return "- None"
        
        formatted = []
        for key, value in constraints.items():
            if value:
                formatted.append(f"- {key}: {value}")
        
        return '\n'.join(formatted) if formatted else "- None"





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
            "trip_duration_days": 2
        },
        "user_profile": {"party_size": 1},
        "initial_constraints": {
            "hard": {"budget_max": 500},
            "soft": {"interests": ["hiking"]}
        },
        "dynamic_events": []
    }
    
    agent = TravelAgent(api_key=api_key)
    result = agent.plan_trip(test_task)
    
    print("="*70)
    print("RESULT")
    print("="*70)
    print(f"Success: {result['success']}")
    print(f"API calls: {result['metadata']['api_calls']}")
    print(f"Tokens: {result['metadata']['total_tokens']}")