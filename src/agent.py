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
        self.model = "claude-sonnet-4-6"
        
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
        if create_planning_prompt:
            return create_planning_prompt(task)
        
        scenario = task.get("scenario", {})
        constraints = task.get("initial_constraints", {})
        
        prompt = f"""Plan a trip:
 
            Origin: {scenario.get('origin_city')}
            Destination: {', '.join(scenario.get('destination_cities', []))}
            Duration: {scenario.get('trip_duration_days')} days
            Party size: {task.get('user_profile', {}).get('party_size', 1)}
            
            HARD CONSTRAINTS:
            {self._format_constraints(constraints.get('hard', {}))}
            
            PREFERENCES:
            {self._format_constraints(constraints.get('soft', {}))}
            
            Use ReAct format:
            THOUGHT: [reasoning]
            ACTION: search_flights(origin="City", destination="City", max_price=300)
            
            Start planning.
        """
        
        return prompt
        
    def _react_planning_loop(self, prompt: str, task: Dict[str, Any]) -> str:
        """React planning loop."""


        self.conversation_history.append({
            "role": "user",
            "content": initial_prompt
        })
        
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            self.turn_count += 1
            
            response = self._get_agent_response()
            action_needed, tool_name, tool_params = self._parse_action(response)
            
            if action_needed:
                tool_result = self._execute_tool(tool_name, tool_params)
                observation = f"TOOL RESULT from {tool_name}:\n{json.dumps(tool_result, indent=2)}"
                
                self.conversation_history.append({
                    "role": "user",
                    "content": observation
                })
            else:
                if "FINAL ITINERARY" in response or iteration >= max_iterations - 2:
                    return response
        
        return self.conversation_history[-1]["content"] if self.conversation_history else ""


    def _handle_dynamic_event(self, event: Dict[str, Any], itinerary: str, task: Dict[str, Any]) -> str:
        """Handle dynamic event."""
        if create_replanning_prompt:
            replanning_prompt = create_replanning_prompt(
                event,
                current_itinerary,
                event.get('affected_components', [])
            )
        else:
            replanning_prompt = f"""DYNAMIC EVENT: {event['description']}
 
                CURRENT ITINERARY:
                {current_itinerary}
                
                AFFECTED: {', '.join(event.get('affected_components', []))}
                
                Replan incrementally - preserve unaffected bookings.
            """
        
        self.conversation_history.append({
            "role": "user",
            "content": replanning_prompt
        })
        
        updated_itinerary = self._react_planning_loop(
            replanning_prompt,
            task,
            max_iterations=10
        )
        
        return updated_itinerary    


    def _parse_action(self, response: str) -> Tuple[bool, str, Dict]:
        if "ACTION:" not in response:
            return False, None, None
        
        try:
            action_line = [line for line in response.split('\n') if 'ACTION:' in line][0]
            action_part = action_line.split('ACTION:')[1].strip()
            
            tool_name = action_part.split('(')[0].strip()
            params_str = action_part.split('(')[1].rsplit(')', 1)[0]
            
            params = {}
            for param in params_str.split(','):
                if '=' in param:
                    key, value = param.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    params[key] = value
            
            return True, tool_name, params
            
        except:
            return False, None, None


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