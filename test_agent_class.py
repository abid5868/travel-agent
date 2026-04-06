import os
import json
import time
from pathlib import Path
from src.agent import TravelAgent

TASKS = [
    "benchmarks/tasks/easy/easy1.json",
    "benchmarks/tasks/medium/medium1.json",
    "benchmarks/tasks/hard/hard1.json",
]

OUTPUT_DIR = Path("agent_planning_results")
OUTPUT_DIR.mkdir(exist_ok=True)

def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required to run this integration script.")

    agent = TravelAgent(api_key=api_key)

    for task_path in TASKS:
        task_name = Path(task_path).stem  # e.g. "easy1"
        print(f"\n{'='*60}")
        print(f"Running: {task_name}  ({task_path})")
        print(f"{'='*60}")

        with open(task_path) as f:
            task = json.load(f)

        wall_start = time.time()
        result = agent.plan_trip(task)
        wall_elapsed = round(time.time() - wall_start, 2)

        result["metadata"]["wall_time_seconds"] = wall_elapsed

        metadata_output = {
            "task_id":    task.get("task_id", task_name),
            "task_file":  task_path,
            "title":      task.get("title", ""),
            "difficulty": task.get("difficulty", ""),
            "success":    result["success"],
            "metadata":   result["metadata"],
        }
        json_path = OUTPUT_DIR / f"{task_name}.json"
        with open(json_path, "w") as f:
            json.dump(metadata_output, f, indent=2)

        md_path = OUTPUT_DIR / f"{task_name}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(result["itinerary"])

        print(f"  Success:   {result['success']}")
        print(f"  API calls: {result['metadata']['api_calls']}")
        print(f"  Tokens:    {result['metadata']['total_tokens']}")
        print(f"  Time:      {wall_elapsed}s")
        print(f"  Metadata:  {json_path}")
        print(f"  Itinerary: {md_path}")


if __name__ == "__main__":
    main()
