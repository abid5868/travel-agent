"""
evaluations/llm_judge.py - LLM-as-a-Judge for travel agent output evaluation.
Uses claude-opus-4-6 to score itineraries across 5 dimensions.
"""

import json
import os
import sys
import argparse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    reasoning: str
    findings: List[str] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return self.max_score > 0

    @property
    def pct(self) -> Optional[float]:
        if not self.applicable:
            return None
        return round(self.score / self.max_score * 100, 1)


@dataclass
class JudgeResult:
    task_id: str
    task_title: str
    difficulty: str
    hard_constraints: DimensionScore
    required_components: DimensionScore
    soft_preferences: DimensionScore
    replanning_quality: DimensionScore
    itinerary_coherence: DimensionScore
    overall_score: float
    passed: bool
    pass_threshold: float
    judge_model: str = "claude-opus-4-6"
    raw_judge_response: str = ""

    def dimensions(self) -> List[DimensionScore]:
        return [
            self.hard_constraints,
            self.required_components,
            self.soft_preferences,
            self.replanning_quality,
            self.itinerary_coherence,
        ]

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"LLM Judge Report",
            f"Task: [{self.task_id}] {self.task_title} ({self.difficulty})",
            f"{'='*60}",
        ]
        for dim in self.dimensions():
            if dim.applicable:
                lines.append(f"  {dim.name:<30} {dim.score:>4.1f}/10  ({dim.pct}%)")
                for finding in dim.findings:
                    lines.append(f"      - {finding}")
            else:
                lines.append(f"  {dim.name:<30}  N/A")
        lines += [
            f"{'─'*60}",
            f"  Overall Score:                   {self.overall_score:>5.1f}/100",
            f"  Verdict:                         {'PASS' if self.passed else 'FAIL'}",
            f"{'='*60}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "difficulty": self.difficulty,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "pass_threshold": self.pass_threshold,
            "judge_model": self.judge_model,
            "dimensions": {
                dim.name: {
                    "score": dim.score,
                    "max_score": dim.max_score,
                    "pct": dim.pct,
                    "reasoning": dim.reasoning,
                    "findings": dim.findings,
                }
                for dim in self.dimensions()
            },
        }


_SYSTEM_PROMPT = """\
You are an expert travel planning evaluator. Assess AI-generated travel itineraries
across exactly five dimensions.

Return ONLY a valid JSON object — no markdown fences, no prose outside the JSON.

JSON schema:
{
  "hard_constraints": {
    "score": <0.0-10.0>,
    "reasoning": "<one paragraph>",
    "findings": ["<finding>", ...]
  },
  "required_components": {
    "score": <0.0-10.0>,
    "reasoning": "<one paragraph>",
    "findings": ["<finding>", ...]
  },
  "soft_preferences": {
    "score": <0.0-10.0>,
    "reasoning": "<one paragraph>",
    "findings": ["<finding>", ...]
  },
  "replanning_quality": {
    "score": <0.0-10.0 or null if no dynamic events>,
    "reasoning": "<one paragraph or 'N/A'>",
    "findings": ["<finding>", ...]
  },
  "itinerary_coherence": {
    "score": <0.0-10.0>,
    "reasoning": "<one paragraph>",
    "findings": ["<finding>", ...]
  }
}

Scoring: 9-10 Excellent, 7-8 Good, 5-6 Partial, 3-4 Poor, 0-2 Failing

HARD CONSTRAINTS (30%): budget <= budget_max, dates, wheelchair_accessible, party size. Score 0 if any hard constraint is violated.
REQUIRED COMPONENTS (25%): count satisfied items / total items * 10.
SOFT PREFERENCES (15%): interests and preferences reflected in choices.
REPLANNING QUALITY (20%): dynamic event handled, affected bookings updated, unaffected preserved. Set null if no dynamic events.
ITINERARY COHERENCE (10%): logical day-by-day flow, no scheduling conflicts, full trip duration covered.
"""

_USER_TEMPLATE = """\
## Task
```json
{task_json}
```

## Final Itinerary
```
{itinerary}
```

## Conversation Log (last {max_turns} turns)
```
{conversation_log}
```
"""


class LLMJudge:
    MODEL = "claude-opus-4-6"

    WEIGHTS = {
        "hard_constraints": 0.30,
        "required_components": 0.25,
        "soft_preferences": 0.15,
        "replanning_quality": 0.20,
        "itinerary_coherence": 0.10,
    }

    def __init__(self, api_key: Optional[str] = None, pass_threshold: float = 70.0, max_conversation_turns: int = 20):
        self.client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.pass_threshold = pass_threshold
        self.max_conversation_turns = max_conversation_turns

    def evaluate(self, task: Dict[str, Any], agent_output: Dict[str, Any]) -> JudgeResult:
        itinerary = agent_output.get("itinerary", "")
        conversation = agent_output.get("conversation", [])
        prompt = self._build_prompt(task, itinerary, conversation)
        raw = self._call_judge(prompt)
        parsed = self._parse_response(raw)
        return self._build_result(task, parsed, raw)

    def evaluate_batch(self, tasks_and_outputs: List[Dict[str, Any]]) -> List[JudgeResult]:
        return [self.evaluate(item["task"], item["agent_output"]) for item in tasks_and_outputs]

    def _build_prompt(self, task: Dict[str, Any], itinerary: str, conversation: List[Dict[str, str]]) -> str:
        trimmed = conversation[-self.max_conversation_turns:]
        convo_lines = []
        for msg in trimmed:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            if len(content) > 1500:
                content = content[:1500] + "\n... [truncated]"
            convo_lines.append(f"[{role}]\n{content}")
        conversation_log = "\n\n".join(convo_lines) if convo_lines else "(none)"
        return _USER_TEMPLATE.format(
            task_json=json.dumps(task, indent=2),
            itinerary=itinerary or "(none)",
            max_turns=self.max_conversation_turns,
            conversation_log=conversation_log,
        )

    def _call_judge(self, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        text = raw
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Judge returned invalid JSON.\n{exc}\nRaw:\n{raw}") from exc

    def _build_result(self, task: Dict[str, Any], parsed: Dict[str, Any], raw: str) -> JudgeResult:
        has_events = bool(task.get("dynamic_events"))

        def _dim(key: str, applicable: bool = True) -> DimensionScore:
            data = parsed.get(key, {})
            raw_score = data.get("score")
            if not applicable or raw_score is None:
                return DimensionScore(key, -1.0, 0.0, data.get("reasoning", "N/A"), data.get("findings", []))
            return DimensionScore(key, max(0.0, min(10.0, float(raw_score))), 10.0, data.get("reasoning", ""), data.get("findings", []))

        hard = _dim("hard_constraints")
        components = _dim("required_components")
        soft = _dim("soft_preferences")
        replan = _dim("replanning_quality", applicable=has_events)
        coherence = _dim("itinerary_coherence")
        overall = self._compute_overall(hard, components, soft, replan, coherence)

        return JudgeResult(
            task_id=task.get("task_id", "unknown"),
            task_title=task.get("title", ""),
            difficulty=task.get("difficulty", "unknown"),
            hard_constraints=hard,
            required_components=components,
            soft_preferences=soft,
            replanning_quality=replan,
            itinerary_coherence=coherence,
            overall_score=overall,
            passed=overall >= self.pass_threshold,
            pass_threshold=self.pass_threshold,
            raw_judge_response=raw,
        )

    def _compute_overall(self, hard, components, soft, replan, coherence) -> float:
        weights = dict(self.WEIGHTS)
        if not replan.applicable:
            extra = weights.pop("replanning_quality")
            total = sum(weights.values())
            for k in list(weights):
                weights[k] += extra * (weights[k] / total)
        score_map = {
            "hard_constraints": hard,
            "required_components": components,
            "soft_preferences": soft,
            "replanning_quality": replan,
            "itinerary_coherence": coherence,
        }
        total = sum(
            (score_map[k].score / 10.0) * w * 100
            for k, w in weights.items()
            if score_map[k].applicable
        )
        return round(total, 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LLM judge on agent output.")
    parser.add_argument("task_file", help="Path to benchmark task JSON")
    parser.add_argument("agent_output_file", help="Path to agent output JSON")
    parser.add_argument("--threshold", type=float, default=70.0)
    parser.add_argument("--output", help="Path to write judge result JSON")
    args = parser.parse_args()

    with open(args.task_file) as f:
        task = json.load(f)
    with open(args.agent_output_file) as f:
        agent_output = json.load(f)

    result = LLMJudge(pass_threshold=args.threshold).evaluate(task, agent_output)
    print(result.summary())

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"Result written to {args.output}")

    sys.exit(0 if result.passed else 1)
