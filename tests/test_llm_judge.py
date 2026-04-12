import json
from io import StringIO

from evaluations.llm_judge import (
    DimensionScore,
    JudgeResult,
    build_evaluation_pairs,
    discover_agent_output_files,
    format_batch_results_report,
    format_batch_results_table,
    print_progress_bar,
    render_progress_bar,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _task_payload(task_id, difficulty, title):
    return {
        "task_id": task_id,
        "difficulty": difficulty,
        "title": title,
        "dynamic_events": [],
    }


def _score(name, score, applicable=True):
    if not applicable:
        return DimensionScore(name=name, score=-1.0, max_score=0.0, reasoning="N/A", findings=[])
    return DimensionScore(
        name=name,
        score=score,
        max_score=10.0,
        reasoning=f"{name} rationale explains the score in a concise way.",
        findings=[],
    )


def test_discover_agent_output_files_prefers_markdown(tmp_path):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "easy1.md").write_text("# itinerary", encoding="utf-8")
    _write_json(output_dir / "easy1.json", {"task_id": "task_001"})
    (output_dir / "easy2.md").write_text("# another itinerary", encoding="utf-8")

    discovered = discover_agent_output_files(output_dir)

    assert discovered["easy1"].suffix == ".md"
    assert discovered["easy2"].suffix == ".md"


def test_build_evaluation_pairs_matches_stems_and_skips_outputs_without_itinerary(tmp_path):
    task_dir = tmp_path / "tasks"
    output_dir = tmp_path / "outputs"

    _write_json(task_dir / "easy" / "easy1.json", _task_payload("task_001", "easy", "Easy trip"))
    _write_json(task_dir / "medium" / "medium1.json", _task_payload("task_101", "medium", "Medium trip"))

    (output_dir / "easy1.md").parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "easy1.md").write_text("# FINAL ITINERARY\nChicago plan", encoding="utf-8")
    _write_json(output_dir / "medium1.json", {"task_id": "task_101", "success": True})
    (output_dir / "orphan.md").write_text("# FINAL ITINERARY\nNo task", encoding="utf-8")

    pairs = build_evaluation_pairs(task_dir, output_dir)

    assert len(pairs) == 1
    assert pairs[0]["match_name"] == "easy1"
    assert pairs[0]["task"]["title"] == "Easy trip"
    assert pairs[0]["agent_output"]["itinerary"].startswith("# FINAL ITINERARY")


def test_format_batch_results_table_includes_average_row(tmp_path):
    results = [
        JudgeResult(
            task_id="task_001",
            task_title="Easy trip",
            difficulty="easy",
            hard_constraints=_score("hard_constraints", 9.0),
            required_components=_score("required_components", 8.0),
            soft_preferences=_score("soft_preferences", 7.0),
            replanning_quality=_score("replanning_quality", 6.0),
            itinerary_coherence=_score("itinerary_coherence", 9.0),
            overall_score=80.0,
            passed=True,
            pass_threshold=70.0,
        ),
        JudgeResult(
            task_id="task_002",
            task_title="Easy trip 2",
            difficulty="easy",
            hard_constraints=_score("hard_constraints", 5.0),
            required_components=_score("required_components", 6.0),
            soft_preferences=_score("soft_preferences", 7.0),
            replanning_quality=_score("replanning_quality", 0.0, applicable=False),
            itinerary_coherence=_score("itinerary_coherence", 6.0),
            overall_score=60.0,
            passed=False,
            pass_threshold=70.0,
        ),
    ]

    table = format_batch_results_table(
        results,
        pairs=[{"match_name": "easy1"}, {"match_name": "easy2"}],
    )

    assert "Task" in table
    assert "easy1" in table
    assert "easy2" in table
    assert "N/A" in table
    assert "AVERAGE" in table
    assert "70.0/100" in table
    assert "1/2 pass" in table


def test_batch_results_report_includes_brief_rationales():
    result = JudgeResult(
        task_id="task_001",
        task_title="Easy trip",
        difficulty="easy",
        hard_constraints=_score("hard_constraints", 9.0),
        required_components=_score("required_components", 8.0),
        soft_preferences=_score("soft_preferences", 7.0),
        replanning_quality=_score("replanning_quality", 0.0, applicable=False),
        itinerary_coherence=_score("itinerary_coherence", 9.0),
        overall_score=82.0,
        passed=True,
        pass_threshold=70.0,
    )

    report = format_batch_results_report([result], pairs=[{"match_name": "easy1"}])

    assert "Brief Score Rationale" in report
    assert "easy1 [task_001] Easy trip - 82.0/100 (PASS)" in report
    assert "Hard Constraints (9.0/10): hard_constraints rationale explains the score in a concise way." in report
    assert "Replanning Quality (N/A): Not applicable for this task." in report


def test_single_result_summary_includes_why_lines():
    result = JudgeResult(
        task_id="task_001",
        task_title="Easy trip",
        difficulty="easy",
        hard_constraints=_score("hard_constraints", 9.0),
        required_components=_score("required_components", 8.0),
        soft_preferences=_score("soft_preferences", 7.0),
        replanning_quality=_score("replanning_quality", 6.0),
        itinerary_coherence=_score("itinerary_coherence", 9.0),
        overall_score=80.0,
        passed=True,
        pass_threshold=70.0,
    )

    summary = result.summary()

    assert "Hard Constraints" in summary
    assert "Why: hard_constraints rationale explains the score in a concise way." in summary


def test_progress_bar_renders_and_finishes_with_newline():
    assert "2/4" in render_progress_bar(2, 4, "Running easy2")

    stream = StringIO()
    print_progress_bar(1, 1, "Completed easy1", stream=stream)

    assert "Completed easy1" in stream.getvalue()
    assert stream.getvalue().endswith("\n")
