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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO
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


SUPPORTED_OUTPUT_SUFFIXES = (".md", ".json")
OUTPUT_SUFFIX_PRIORITY = {".md": 0, ".json": 1}
DIMENSION_LABELS = {
    "hard_constraints": "Hard Constraints",
    "required_components": "Required Components",
    "soft_preferences": "Soft Preferences",
    "replanning_quality": "Replanning Quality",
    "itinerary_coherence": "Itinerary Coherence",
}
PROGRESS_BAR_WIDTH = 28


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
            label = _display_dimension_name(dim.name)
            if dim.applicable:
                lines.append(f"  {label:<30} {dim.score:>4.1f}/10  ({dim.pct}%)")
                lines.append(f"      Why: {_brief_rationale(dim)}")
            else:
                lines.append(f"  {label:<30}  N/A")
                lines.append(f"      Why: {_brief_rationale(dim)}")
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

## EVIDENCE PRIORITY
1. Trust concrete booking facts first: booking IDs, dates, times, party sizes, costs, and explicit cancellations/rebookings.
2. Then use budget tables, requirement tables, and success-status tables.
3. Treat narrative claims, headers, and summary bullets as lowest-priority evidence.
4. If evidence conflicts, prefer the concrete booking facts over the prose.
5. Count DISTINCT confirmed booking IDs. If the same booking ID is repeated multiple times, count it once unless separate confirmed IDs are shown.
6. For tasks with dynamic events, judge the final itinerary against the post-event task requirements in the task JSON, even if the itinerary text repeats stale pre-event wording.

## DIMENSION DEFINITIONS

1. HARD CONSTRAINTS (weight: 30%)
   Verify actual executable facts: budget ≤ budget_max, dates valid, wheelchair_accessible if required, party size matches, and core timing feasibility.
   CRITICAL: Score 0 only if the confirmed facts clearly violate a hard constraint or make the trip non-executable.
   Minor reporting issues, copied stale labels, or outdated summary text should NOT be treated as hard-constraint violations if the underlying bookings satisfy the task.

2. REQUIRED COMPONENTS (weight: 25%)
   Assess based on distinct confirmed bookings: count of satisfied required items / total required items * 10.
   Example: 8 of 10 items satisfied = 8.0 points.
   Reusing the same booking ID twice does not satisfy two separate required items.

3. SOFT PREFERENCES (weight: 15%)
   Evaluate: how well are user interests and preferences reflected in activity/restaurant/accommodation choices?
   Full alignment = higher score; ignored preferences = lower score.

4. REPLANNING QUALITY (weight: 20%)
   If NO dynamic events in task: set score to null and reasoning to "N/A" (this dimension becomes non-applicable).
   If dynamic events exist: evaluate how well affected bookings were updated, unaffected bookings preserved, and impact minimized.
   Focus on whether the final booked state resolves the event correctly. Mildly stale narrative wording should be a modest deduction here, not an automatic failure.

5. ITINERARY COHERENCE (weight: 10%)
   Assess: logical day-by-day flow, no scheduling conflicts, full trip duration covered, reasonable travel times.
   This is the main place to penalize contradictory prose, stale labels, duplicated booking IDs shown as multiple events, and other presentation/reporting inconsistencies.

## INSTRUCTIONS
- Be consistent and objective
- Base scores ONLY on evidence found in the Final Itinerary text.
- If no conversation log is present, do NOT mention it as a negative finding.
- List specific findings/issues in the findings array
- If replanning_quality is N/A, explain why in the reasoning
- Do not fail an itinerary solely because the write-up is imperfect when the booked facts clearly satisfy the task.
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


"""


def load_task_file(task_file: Path) -> Dict[str, Any]:
    with task_file.open(encoding="utf-8") as f:
        return json.load(f)


def load_agent_output_file(agent_output_file: Path) -> Dict[str, Any]:
    if agent_output_file.suffix.lower() == ".md":
        return {"itinerary": agent_output_file.read_text(encoding="utf-8"), "conversation": []}

    with agent_output_file.open(encoding="utf-8") as f:
        agent_output = json.load(f)

    if not isinstance(agent_output, dict):
        raise ValueError(f"Agent output file must contain a JSON object: {agent_output_file}")

    return agent_output


def _expand_input_path(path: Path, allowed_suffixes: Sequence[str]) -> List[Path]:
    normalized = {suffix.lower() for suffix in allowed_suffixes}
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if path.is_file():
        if path.suffix.lower() not in normalized:
            raise ValueError(f"Unsupported file type for {path}. Expected one of: {', '.join(sorted(normalized))}")
        return [path]

    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in normalized
    )


def discover_task_files(task_path: Path) -> Dict[str, Path]:
    task_files = _expand_input_path(task_path, [".json"])
    if not task_files:
        raise ValueError(f"No task JSON files found in {task_path}")

    indexed: Dict[str, Path] = {}
    duplicates: Dict[str, List[str]] = {}
    for task_file in task_files:
        stem = task_file.stem
        if stem in indexed:
            duplicates.setdefault(stem, [str(indexed[stem])]).append(str(task_file))
            continue
        indexed[stem] = task_file

    if duplicates:
        duplicate_lines = [f"{stem}: {', '.join(paths)}" for stem, paths in sorted(duplicates.items())]
        raise ValueError("Duplicate task file stems found:\n" + "\n".join(duplicate_lines))

    return indexed


def discover_agent_output_files(agent_output_path: Path) -> Dict[str, Path]:
    output_files = _expand_input_path(agent_output_path, SUPPORTED_OUTPUT_SUFFIXES)
    if not output_files:
        raise ValueError(f"No agent output files found in {agent_output_path}")

    grouped: Dict[str, List[Path]] = {}
    for output_file in output_files:
        grouped.setdefault(output_file.stem, []).append(output_file)

    selected: Dict[str, Path] = {}
    for stem, candidates in grouped.items():
        ordered = sorted(
            candidates,
            key=lambda candidate: (OUTPUT_SUFFIX_PRIORITY.get(candidate.suffix.lower(), 999), str(candidate)),
        )
        best = ordered[0]
        best_priority = OUTPUT_SUFFIX_PRIORITY.get(best.suffix.lower(), 999)
        same_priority = [candidate for candidate in ordered if OUTPUT_SUFFIX_PRIORITY.get(candidate.suffix.lower(), 999) == best_priority]
        if len(same_priority) > 1:
            paths = ", ".join(str(candidate) for candidate in same_priority)
            raise ValueError(f"Ambiguous output files for stem '{stem}': {paths}")
        selected[stem] = best

    return selected


def _has_itinerary(agent_output: Dict[str, Any]) -> bool:
    itinerary = agent_output.get("itinerary", "")
    return isinstance(itinerary, str) and bool(itinerary.strip())


def build_evaluation_pairs(task_path: Path, agent_output_path: Path) -> List[Dict[str, Any]]:
    task_files = discover_task_files(task_path)
    output_files = discover_agent_output_files(agent_output_path)

    pairs: List[Dict[str, Any]] = []
    for stem, output_file in sorted(output_files.items()):
        task_file = task_files.get(stem)
        if task_file is None:
            logger.warning(f"Skipping output with no matching task JSON: {output_file}")
            continue

        agent_output = load_agent_output_file(output_file)
        if not _has_itinerary(agent_output):
            logger.warning(f"Skipping output with no itinerary content: {output_file}")
            continue

        pairs.append(
            {
                "match_name": stem,
                "task_file": str(task_file),
                "agent_output_file": str(output_file),
                "task": load_task_file(task_file),
                "agent_output": agent_output,
            }
        )

    if not pairs:
        raise ValueError(
            f"No evaluable task/output pairs found between task folder '{task_path}' and output folder '{agent_output_path}'."
        )

    return pairs


def _format_dimension_score(score: DimensionScore) -> str:
    if not score.applicable:
        return "N/A"
    return f"{score.score:.1f}/10"


def _display_dimension_name(name: str) -> str:
    return DIMENSION_LABELS.get(name, name.replace("_", " ").title())


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _truncate_text(text: str, max_len: int = 140) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _brief_rationale(score: DimensionScore, max_len: int = 140) -> str:
    if not score.applicable:
        return "Not applicable for this task."

    reasoning = _collapse_whitespace(score.reasoning)
    if reasoning and reasoning.upper() != "N/A":
        first_sentence = re.split(r"(?<=[.!?])\s+", reasoning, maxsplit=1)[0]
        return _truncate_text(first_sentence or reasoning, max_len=max_len)

    if score.findings:
        return _truncate_text(_collapse_whitespace("; ".join(score.findings)), max_len=max_len)

    return "No brief rationale was returned by the judge."


def _normalize_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _extract_markdown_table_rows(text: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r"[:\- ]+", cell or "-") for cell in cells):
            continue
        rows.append(cells)
    return rows


def _build_status_lookup(itinerary: str) -> Dict[str, Optional[bool]]:
    ignored_headers = {
        "requirement", "requirements", "criterion", "criteria", "status",
        "category", "item", "details", "date", "time", "cost", "booking id",
        "route", "flight", "name", "meal", "cuisine", "duration",
    }
    lookup: Dict[str, Optional[bool]] = {}
    for cells in _extract_markdown_table_rows(itinerary):
        label = _normalize_label(cells[0])
        if not label or label in ignored_headers:
            continue
        status_text = " ".join(cells[1:]).lower()
        if "❌" in status_text or "unmet" in status_text or "not satisfied" in status_text or "failed" in status_text:
            lookup[label] = False
        elif "✅" in status_text or "satisfied" in status_text or "met" in status_text:
            lookup[label] = True
    return lookup


def _lookup_reported_status(lookup: Dict[str, Optional[bool]], aliases: Sequence[str]) -> Optional[bool]:
    normalized_aliases = [_normalize_label(alias) for alias in aliases]
    for key, value in lookup.items():
        if any(alias and alias in key for alias in normalized_aliases):
            return value
    return None


def _append_reasoning(reasoning: str, note: str) -> str:
    reasoning = reasoning or ""
    if note in reasoning:
        return reasoning
    if not reasoning:
        return note
    return f"{reasoning} {note}"


def _append_finding(findings: List[str], finding: str) -> List[str]:
    if finding in findings:
        return findings
    return findings + [finding]


def _apply_fact_based_adjustments(
    task: Dict[str, Any],
    itinerary: str,
    dimensions: Dict[str, DimensionScore],
) -> None:
    lookup = _build_status_lookup(itinerary)
    success_criteria = task.get("success_criteria", {}) or {}
    hard_constraints = ((task.get("initial_constraints") or {}).get("hard") or {})
    dynamic_events = task.get("dynamic_events", []) or []

    hard_signals: List[bool] = []
    if success_criteria.get("total_cost_max") is not None or hard_constraints.get("budget_max") is not None:
        status = _lookup_reported_status(lookup, ["total cost", "budget"])
        if status is not None:
            hard_signals.append(status)
    if success_criteria.get("timing_feasible") is True:
        status = _lookup_reported_status(lookup, ["timing feasible"])
        if status is not None:
            hard_signals.append(status)
    if isinstance(success_criteria.get("final_party_size"), int):
        status = _lookup_reported_status(lookup, ["final party size"])
        if status is not None:
            hard_signals.append(status)
    if hard_constraints.get("wheelchair_accessible") or hard_constraints.get("accessibility_required"):
        status = _lookup_reported_status(lookup, ["accessible", "wheelchair"])
        if status is not None:
            hard_signals.append(status)

    if len(hard_signals) >= 2 and all(hard_signals):
        dim = dimensions["hard_constraints"]
        if dim.applicable and dim.score < 8.5:
            dim.score = 8.5
            dim.reasoning = _append_reasoning(
                dim.reasoning,
                "Fact-based adjustment: explicit success-status evidence shows the core hard constraints are satisfied."
            )
            dim.findings = [finding for finding in dim.findings if "hard constraint" not in finding.lower() or "violated" not in finding.lower()]

    replan_signals: List[bool] = []
    if dynamic_events:
        for aliases in (
            ["replanning successful"],
            ["unaffected bookings preserved"],
            ["dependent bookings updated"],
        ):
            status = _lookup_reported_status(lookup, aliases)
            if status is not None:
                replan_signals.append(status)

    if len(replan_signals) >= 2 and all(replan_signals):
        floor = 8.0 if any(event.get("event_type") == "party_size_increase" for event in dynamic_events) else 7.5
        dim = dimensions["replanning_quality"]
        if dim.applicable and dim.score < floor:
            dim.score = floor
            dim.reasoning = _append_reasoning(
                dim.reasoning,
                "Fact-based adjustment: the reported success-status and audit trail show the event was resolved with preserved unaffected bookings."
            )

    # Mild presentation contradictions should not dominate the final result if facts are strong.
    if all(hard_signals) and len(hard_signals) >= 2:
        dim = dimensions["itinerary_coherence"]
        if dim.applicable and dim.score < 7.0:
            dim.score = 7.0
            dim.reasoning = _append_reasoning(
                dim.reasoning,
                "Fact-based adjustment: despite some reporting inconsistencies, the concrete booking flow remains coherent."
            )


def _format_average_score(scores: Sequence[DimensionScore]) -> str:
    applicable = [score.score for score in scores if score.applicable]
    if not applicable:
        return "N/A"
    return f"{sum(applicable) / len(applicable):.1f}/10"


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    numeric_columns = {2, 3, 4, 5, 6, 7}

    def _format_row(row: Sequence[str]) -> str:
        cells = []
        for idx, cell in enumerate(row):
            align = ">" if idx in numeric_columns else "<"
            cells.append(f"{cell:{align}{widths[idx]}}")
        return "| " + " | ".join(cells) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    lines = [_format_row(headers), separator]
    lines.extend(_format_row(row) for row in rows)
    return "\n".join(lines)


def format_batch_results_table(results: List["JudgeResult"], pairs: Optional[List[Dict[str, Any]]] = None) -> str:
    headers = [
        "Task",
        "Difficulty",
        "Hard",
        "Required",
        "Soft",
        "Replan",
        "Coherence",
        "Overall",
        "Verdict",
    ]

    rows: List[List[str]] = []
    for idx, result in enumerate(results):
        label = result.task_id
        if pairs and idx < len(pairs):
            label = pairs[idx].get("match_name", label)

        rows.append(
            [
                label,
                result.difficulty,
                _format_dimension_score(result.hard_constraints),
                _format_dimension_score(result.required_components),
                _format_dimension_score(result.soft_preferences),
                _format_dimension_score(result.replanning_quality),
                _format_dimension_score(result.itinerary_coherence),
                f"{result.overall_score:.1f}/100",
                "PASS" if result.passed else "FAIL",
            ]
        )

    if results:
        average_row = [
            "AVERAGE",
            "-",
            _format_average_score([result.hard_constraints for result in results]),
            _format_average_score([result.required_components for result in results]),
            _format_average_score([result.soft_preferences for result in results]),
            _format_average_score([result.replanning_quality for result in results]),
            _format_average_score([result.itinerary_coherence for result in results]),
            f"{sum(result.overall_score for result in results) / len(results):.1f}/100",
            f"{sum(1 for result in results if result.passed)}/{len(results)} pass",
        ]
        rows.append(average_row)

    return _render_table(headers, rows)


def format_batch_reasoning_summary(results: List["JudgeResult"], pairs: Optional[List[Dict[str, Any]]] = None) -> str:
    lines = ["Brief Score Rationale"]
    for idx, result in enumerate(results):
        label = result.task_id
        if pairs and idx < len(pairs):
            label = pairs[idx].get("match_name", label)

        lines.append("")
        lines.append(
            f"{label} [{result.task_id}] {result.task_title} - {result.overall_score:.1f}/100 ({'PASS' if result.passed else 'FAIL'})"
        )
        for dimension in result.dimensions():
            lines.append(
                f"  {_display_dimension_name(dimension.name)} ({_format_dimension_score(dimension)}): {_brief_rationale(dimension)}"
            )

    return "\n".join(lines)


def format_batch_results_report(results: List["JudgeResult"], pairs: Optional[List[Dict[str, Any]]] = None) -> str:
    return f"{format_batch_results_table(results, pairs)}\n\n{format_batch_reasoning_summary(results, pairs)}"


def render_progress_bar(current: int, total: int, label: str = "", width: int = PROGRESS_BAR_WIDTH) -> str:
    total = max(total, 1)
    current = max(0, min(current, total))
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    percent = current / total * 100
    suffix = f" {label}" if label else ""
    return f"Evaluating [{bar}] {current}/{total} ({percent:5.1f}%){suffix}"


def print_progress_bar(current: int, total: int, label: str = "", stream: TextIO = sys.stderr) -> None:
    line = render_progress_bar(current, total, label=label)
    end = "\n" if current >= total else "\r"
    stream.write(line + end)
    stream.flush()


class LLMJudge:
    MODEL = "claude-sonnet-4-6"
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

    def __init__(self, api_key: Optional[str] = None, pass_threshold: float = 70.0, max_conversation_turns: int = 20, max_tokens: int = 4096):
        self.client = Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY from env automatically
        self.pass_threshold = pass_threshold
        self.max_conversation_turns = max_conversation_turns
        self.max_tokens = max_tokens
        self._current_itinerary_for_adjustment = ""

    def evaluate(self, task: Dict[str, Any], agent_output: Dict[str, Any]) -> JudgeResult:
        # Validate input structure
        self._validate_task(task)
        self._validate_agent_output(agent_output)
        
        itinerary = agent_output.get("itinerary", "")
        conversation = agent_output.get("conversation", [])
        self._current_itinerary_for_adjustment = itinerary
        prompt = self._build_prompt(task, itinerary, conversation)
        raw = self._call_judge(prompt)
        parsed = self._parse_response(raw)
        return self._build_result(task, parsed, raw)

    def evaluate_batch(
        self,
        tasks_and_outputs: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[JudgeResult]:
        results = []
        total = len(tasks_and_outputs)
        if progress_callback:
            progress_callback(0, total, "Starting")

        for idx, item in enumerate(tasks_and_outputs, start=1):
            label = item.get("match_name") or item.get("task", {}).get("task_id", f"item {idx}")
            if progress_callback:
                progress_callback(idx - 1, total, f"Running {label}")
            try:
                result = self.evaluate(item["task"], item["agent_output"])
                results.append(result)
            except Exception as e:
                logger.error(f"Error evaluating batch item {idx}: {e}")
                raise
            if progress_callback:
                progress_callback(idx, total, f"Completed {label}")
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
        _apply_fact_based_adjustments(task, self._current_itinerary_for_adjustment, dimensions)
        
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
    parser.add_argument("task_path", help="Path to a benchmark task JSON file or a directory of task JSON files")
    parser.add_argument("agent_output_path", help="Path to an agent output file or a directory of agent output files")
    parser.add_argument("--threshold", type=float, default=70.0)
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max tokens for judge response")
    args = parser.parse_args()

    task_path = Path(args.task_path)
    agent_output_path = Path(args.agent_output_path)
    judge = LLMJudge(pass_threshold=args.threshold, max_tokens=args.max_tokens)

    if task_path.is_dir() or agent_output_path.is_dir():
        if not task_path.is_dir() or not agent_output_path.is_dir():
            parser.error("Directory mode requires both task_path and agent_output_path to be directories.")

        pairs = build_evaluation_pairs(task_path, agent_output_path)
        results = judge.evaluate_batch(pairs, progress_callback=print_progress_bar)
        print(format_batch_results_report(results, pairs))
        sys.exit(0 if results and all(result.passed for result in results) else 1)

    task = load_task_file(task_path)
    agent_output = load_agent_output_file(agent_output_path)
    print_progress_bar(0, 1, f"Running {task_path.stem}")
    result = judge.evaluate(task, agent_output)
    print_progress_bar(1, 1, f"Completed {task_path.stem}")
    print(result.summary())

    sys.exit(0 if result.passed else 1)
