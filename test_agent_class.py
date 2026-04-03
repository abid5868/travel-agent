import os, json
from src.agent import TravelAgent
with open('benchmarks/tasks/easy/easy1.json') as f:
    task = json.load(f)
agent = TravelAgent(api_key=os.environ['ANTHROPIC_API_KEY'])
result = agent.plan_trip(task)
print('Success:', result['success'])
print('API calls:', result['metadata']['api_calls'])
print('Cost tracking:', agent.tracker.budget_used)
print(result['itinerary'])
