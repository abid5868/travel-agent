import json
from pathlib import Path

from src.utils.prompts import create_planning_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = PROJECT_ROOT / "benchmarks" / "tasks" / "easy" / "easy1.json"


def test_create_planning_prompt_includes_key_trip_details():
    with open(TASK_PATH, encoding="utf-8") as f:
        task = json.load(f)

    prompt = create_planning_prompt(task)

    assert "Origin: Detroit" in prompt
    assert "Destination(s): Chicago" in prompt
    assert "live music" in prompt
    assert "SUCCESS CRITERIA" in prompt
    assert "timing_feasible" in prompt
