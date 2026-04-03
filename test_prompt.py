import json
from src.utils.prompts import create_planning_prompt
with open('benchmarks/tasks/easy/easy1.json') as f:
	task = json.load(f)
print(create_planning_prompt(task))
