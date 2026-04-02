"""
evaluations/llm_judge.py - LLM-as-a-Judge for travel agent output evaluation.
Uses claude-opus-4-6 to score itineraries across 5 dimensions.
"""

import json
import sys
import argparse
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from anthropic import Anthropic, APIError

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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
You are an expert travel planning evaluator. Assess AI-generated travel itineraries.

## OUTPUT REQUIREMENTS
Return ONLY a valid JSON object with NO markdown fences, NO extra prose outside JSON.

## JSON SCHEMA
{
  "hard_constraints": {
    "score": 0.0 to 10.0 (number),
    "reasoning": "one concise paragraph",
    "findings": ["finding 1", "finding 2", ...]
  },
  "required_components": {
    "score": 0.0 to 10.0 (number),
    "reasoning": "one concise paragraph",
    "findings": ["finding 1", "finding 2", ...]
  },
  "soft_preferences": {
    "score": 0.0 to 10.0 (number),
    "reasoning": "one concise paragraph",
    "findings": ["finding 1", "finding 2", ...]
  },
  "replanning_quality": {
    "score": 0.0 to 10.0 (number) OR null if no dynamic events occur,
    "reasoning": "one paragraph OR 'N/A' if no dynamic events",
    "findings": ["finding 1", "finding 2", ...]
  },
  "itinerary_coherence": {
    "score": 0.0 to 10.0 (number),
    "reasoning": "one concise paragraph",
    "findings": ["finding 1", "finding 2", ...]
  }
}

## SCORING SCALE
9-10 = Excellent (exceptional quality, no issues)
7-8 = Good (solid performance, minor issues)
5-6 = Partial (meets some but not all criteria)
3-4 = Poor (significant shortcomings)
0-2 = Failing (major violations or missing elements)

## DIMENSION DEFINITIONS

1. HARD CONSTRAINTS (weight: 30%)
   Verify: budget ≤ budget_max, dates valid, wheelchair_accessible if required, party size matches.
   CRITICAL: Score 0 if ANY hard constraint is violated; otherwise score based on full compliance.

2. REQUIRED COMPONENTS (weight: 25%)
   Assess: count of satisfied required items / total required items * 10.
   Example: 8 of 10 items satisfied = 8.0 points.

3. SOFT PREFERENCES (weight: 15%)
   Evaluate: how well are user interests and preferences reflected in activity/restaurant/accommodation choices?
   Full alignment = higher score; ignored preferences = lower score.

4. REPLANNING QUALITY (weight: 20%)
   If NO dynamic events in task: set score to null and reasoning to "N/A" (this dimension becomes non-applicable).
   If dynamic events exist: evaluate how well affected bookings were updated, unaffected bookings preserved, and impact minimized.

5. ITINERARY COHERENCE (weight: 10%)
   Assess: logical day-by-day flow, no scheduling conflicts, full trip duration covered, reasonable travel times.

## INSTRUCTIONS
- Be consistent and objective
- Base scores on evidence from the itinerary and conversation
- List specific findings/issues in the findings array
- If replanning_quality is N/A, explain why in the reasoning
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
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 1.0  # seconds

    WEIGHTS = {
        "hard_constraints": 0.30,
        "required_components": 0.25,
        "soft_preferences": 0.15,
        "replanning_quality": 0.20,
        "itinerary_coherence": 0.10,
    }

    DIMENSION_KEYS = ["hard_constraints", "required_components", "soft_preferences", "replanning_quality", "itinerary_coherence"]

    def __init__(self, api_key: Optional[str] = None, pass_threshold: float = 70.0, max_conversation_turns: int = 20, max_tokens: int = 2048):
        self.client = Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY from env automatically
        self.pass_threshold = pass_threshold
        self.max_conversation_turns = max_conversation_turns
        self.max_tokens = max_tokens

    def evaluate(self, task: Dict[str, Any], agent_output: Dict[str, Any]) -> JudgeResult:
        # Validate input structure
        self._validate_task(task)
        self._validate_agent_output(agent_output)
        
        itinerary = agent_output.get("itinerary", "")
        conversation = agent_output.get("conversation", [])
        prompt = self._build_prompt(task, itinerary, conversation)
        raw = self._call_judge(prompt)
        parsed = self._parse_response(raw)
        return self._build_result(task, parsed, raw)

    def evaluate_batch(self, tasks_and_outputs: List[Dict[str, Any]]) -> List[JudgeResult]:
        results = []
        for idx, item in enumerate(tasks_and_outputs):
            try:
                result = self.evaluate(item["task"], item["agent_output"])
                results.append(result)
            except Exception as e:
                logger.error(f"Error evaluating batch item {idx}: {e}")
                raise
        return results

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
        """Call the judge model with exponential backoff retry logic."""
        import time
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.client.messages.create(
                    model=self.MODEL,
                    max_tokens=self.max_tokens,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text.strip()
            except APIError as e:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.INITIAL_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"API error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed after {self.MAX_RETRIES} attempts: {e}")
                    raise

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        """Parse JSON response, robustly handling markdown fences and whitespace."""
        text = raw.strip()
        
        # Remove markdown code fences using regex
        text = re.sub(r'^```(?:json)?\s*', '', text)  # Remove opening fence
        text = re.sub(r'\s*```$', '', text)  # Remove closing fence
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse judge response: {exc}")
            raise ValueError(f"Judge returned invalid JSON.\n{exc}\nRaw:\n{raw}") from exc

    def _build_result(self, task: Dict[str, Any], parsed: Dict[str, Any], raw: str) -> JudgeResult:
        has_events = bool(task.get("dynamic_events"))
        expected_keys = set(self.DIMENSION_KEYS)
        missing = expected_keys - set(parsed.keys())
        if missing:
            logger.warning(f"Judge response missing keys: {missing}. These dimensions will be marked N/A.")

        def _dim(key: str, applicable: bool = True) -> DimensionScore:
            data = parsed.get(key, {})
            raw_score = data.get("score")
            if not applicable or raw_score is None:
                return DimensionScore(key, -1.0, 0.0, data.get("reasoning", "N/A"), data.get("findings", []))
            return DimensionScore(key, max(0.0, min(10.0, float(raw_score))), 10.0, data.get("reasoning", ""), data.get("findings", []))

        # Build dimensions using loop
        dimensions = {}
        dimensions["hard_constraints"] = _dim("hard_constraints")
        dimensions["required_components"] = _dim("required_components")
        dimensions["soft_preferences"] = _dim("soft_preferences")
        dimensions["replanning_quality"] = _dim("replanning_quality", applicable=has_events)
        dimensions["itinerary_coherence"] = _dim("itinerary_coherence")
        
        overall = self._compute_overall(dimensions)

        return JudgeResult(
            task_id=task.get("task_id", "unknown"),
            task_title=task.get("title", ""),
            difficulty=task.get("difficulty", "unknown"),
            hard_constraints=dimensions["hard_constraints"],
            required_components=dimensions["required_components"],
            soft_preferences=dimensions["soft_preferences"],
            replanning_quality=dimensions["replanning_quality"],
            itinerary_coherence=dimensions["itinerary_coherence"],
            overall_score=overall,
            passed=overall >= self.pass_threshold,
            pass_threshold=self.pass_threshold,
            raw_judge_response=raw,
        )

    def _normalize_weights(self, applicable_keys: List[str]) -> Dict[str, float]:
        """Redistribute weights when some dimensions are not applicable."""
        weights = dict(self.WEIGHTS)
        inapplicable = set(self.DIMENSION_KEYS) - set(applicable_keys)
        
        for key in inapplicable:
            if key in weights:
                extra = weights.pop(key)
                remaining = sum(weights.values())
                if remaining > 0:
                    for k in weights:
                        weights[k] += extra * (weights[k] / remaining)
        
        return weights

    def _compute_overall(self, dimensions: Dict[str, DimensionScore]) -> float:
        """Compute overall score from dimensions, redistributing weights for inapplicable ones."""
        applicable = [k for k, v in dimensions.items() if v.applicable]
        weights = self._normalize_weights(applicable)
        
        overall = sum(
            (dimensions[k].score / 10.0) * weights[k] * 100
            for k in applicable
            if k in weights
        )
        return round(overall, 2)

    def _validate_task(self, task: Dict[str, Any]) -> None:
        """Validate task structure before evaluation."""
        required_fields = ["task_id", "title", "difficulty"]
        missing = [f for f in required_fields if f not in task]
        if missing:
            logger.warning(f"Task missing fields: {missing}. Using defaults.")

    def _validate_agent_output(self, agent_output: Dict[str, Any]) -> None:
        """Validate agent output structure before evaluation."""
        if "itinerary" not in agent_output:
            logger.warning("Agent output missing 'itinerary'. Using empty string.")
        if "conversation" not in agent_output:
            logger.warning("Agent output missing 'conversation'. Using empty list.")


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

    judge = LLMJudge(pass_threshold=args.threshold)
    result = judge.evaluate(task, agent_output)
    print(result.summary())

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        logger.info(f"Result written to {args.output}")

    sys.exit(0 if result.passed else 1)
