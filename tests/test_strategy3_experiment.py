from copy import deepcopy

import pytest

# Historical Strategy 3 coverage is retained for the retirement audit only.
pytestmark = pytest.mark.skip(reason="Strategy 3 is retired; Task 4.3 remains incomplete until runtime source is removed")

from src.application.early_momentum import digest
from src.application.early_momentum_rules import DEFAULT_RULES
from src.platform_kernel import DomainValidationError
from tools.strategy3_experiment import (
    _candidate_document,
    _compact_stages,
    _digest,
    _expected_feature_hash,
    _load_rules,
    horizon_stats,
    render_final_markdown,
    render_markdown,
    score_candidate,
    select_candidate_results,
)


def _events(year, count, value):
    return [{"signal_date": f"{year}-06-01", "execution_status": "executed",
             "h20_status": "complete", "h20_session": f"{year}-07-01",
             "return_20": value, "mae_20": .02, "mfe_20": .04}
            for _ in range(count)]


def _result(candidate_id, yearly):
    events = [event for year, (count, value) in yearly.items() for event in _events(year, count, value)]
    candidate = {"candidate_id": candidate_id, "rules": DEFAULT_RULES.to_dict(),
                 "rules_hash": candidate_id, "is_original": candidate_id == "legacy"}
    return score_candidate(candidate, events)


def test_selection_uses_equal_weight_years_then_worst_year_then_lexical():
    legacy = _result("legacy", {2022: (50, .01), 2023: (50, .01), 2024: (50, .01)})
    # Both have the same objective. B has a better worst year than A despite
    # A having many more observations in its strongest year.
    a = _result("a", {2022: (90, .04), 2023: (30, .01), 2024: (30, .01)})
    b = _result("b", {2022: (50, .025), 2023: (50, .02), 2024: (50, .015)})
    result = select_candidate_results(legacy, [a, b])
    assert result["selected_candidate_id"] == "b"
    assert result["beats_original"] is True

    b_twin = deepcopy(b)
    b_twin["candidate_id"] = "aa"
    assert select_candidate_results(legacy, [b, b_twin])["selected_candidate_id"] == "aa"


def test_missing_year_is_ineligible_not_imputed_as_zero():
    legacy = _result("legacy", {2022: (50, .01), 2023: (50, .01), 2024: (50, .01)})
    missing = _result("missing", {2022: (80, .5), 2023: (80, .5)})
    assert missing["eligible"] is False
    assert missing["yearly"]["2024"]["mean_return_20"] is None
    with pytest.raises(DomainValidationError, match="no revised candidate"):
        select_candidate_results(legacy, [missing])


def test_cutoff_excludes_unmatured_and_post_cutoff_h20_events():
    events = _events(2022, 50, .01) + _events(2023, 50, .01) + _events(2024, 50, .01)
    events.append({**events[-1], "h20_status": "insufficient_future_data"})
    events.append({**events[-2], "h20_session": "2025-01-02", "return_20": 99})
    missing_maturity = {**events[-2]}
    missing_maturity.pop("h20_session")
    events.append(missing_maturity)
    result = score_candidate({"candidate_id": "x", "rules": DEFAULT_RULES.to_dict(),
                              "rules_hash": "x", "is_original": False}, events)
    assert result["complete20_count"] == 150
    assert result["objective_equal_weight_yearly_mean_20"] == pytest.approx(.01)


def test_hashes_use_the_application_canonical_encoding():
    value = {"rules": DEFAULT_RULES.to_dict(), "ids": ["raw", "source"]}
    assert _digest(value) == digest(value)


def test_raw_cache_hash_covers_indicator_features_only():
    from pathlib import Path

    indicator = Path("src/indicators/custom/early_momentum.py")
    assert _expected_feature_hash() == digest(indicator.read_text(encoding="utf-8"))


def test_prespecified_candidate_file_has_legacy_and_six_single_changes():
    import json
    from pathlib import Path

    document = json.loads(Path("tools/strategy3_candidates_20260926.json").read_text(encoding="utf-8"))
    legacy, candidates = _candidate_document(document)
    assert legacy["candidate_id"] == "legacy"
    assert len(candidates) == 6
    defaults = DEFAULT_RULES.to_dict()
    for candidate in candidates:
        assert sum(candidate["rules"][key] != value for key, value in defaults.items()) == 1


def test_frozen_envelope_hash_is_checked(tmp_path):
    import json

    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"rules": DEFAULT_RULES.to_dict(), "rules_hash": "wrong"}), encoding="utf-8")
    with pytest.raises(DomainValidationError, match="hash does not match"):
        _load_rules(path)


def test_explicit_legacy_rules_file_matches_defaults():
    assert _load_rules("tools/strategy3_legacy_rules.json") == DEFAULT_RULES.to_dict()


def test_development_markdown_formats_returns_and_yearly_counts():
    legacy = _result("legacy", {2022: (50, .01), 2023: (50, .02), 2024: (50, -.01)})
    revised = _result("C5", {2022: (50, .02), 2023: (50, .03), 2024: (50, .01)})
    report = render_markdown({"selection": select_candidate_results(legacy, [revised]),
                              "original": legacy, "candidates": [revised],
                              "limitations": []}, "development-id")
    assert "| C5 | True | 150 | 2.00% | 1.00% |" in report
    assert "| C5 | development | 2023 | 50 | 50 | 20 | 50 | 3.00% | 3.00% | 0.00% |" in report
    assert "| legacy | development | 2024 | 50 | 50 | 20 | 50 | -1.00% | -1.00% | 100.00% |" in report


def test_development_markdown_reads_existing_artifact_without_execution_counts():
    legacy = _result("legacy", {2022: (50, .01), 2023: (50, .02), 2024: (50, .03)})
    legacy.pop("raw_signal_count")
    legacy.pop("executed_count")
    for yearly in legacy["yearly"].values():
        yearly.pop("raw_signal_count")
        yearly.pop("executed_count")
    report = render_markdown({"selection": {"selected_candidate_id": "legacy",
                                             "beats_original": False, "claim": "Existing artifact"},
                              "original": legacy, "candidates": [], "limitations": []}, "existing-id")
    assert "| legacy | development | 2024 | n/a | n/a | 20 | 50 | 3.00% | 3.00% | 0.00% |" in report


def test_final_markdown_uses_event_summaries_for_both_windows_and_years():
    sample = [{"h1_status": "complete", "h5_status": "complete", "h10_status": "complete",
               "h20_status": "complete", **{f"return_{h}": -.01 for h in (1, 5, 10, 20)},
               **{f"mae_{h}": .02 for h in (1, 5, 10, 20)},
               **{f"mfe_{h}": .03 for h in (1, 5, 10, 20)}}]
    summary = {"raw_signal_count": 2, "execution_status_counts": {"executed": 1},
               "horizons": horizon_stats(sample)}
    study = {"artifact_id": "event-id", "rules_hash": "rules-hash", "summary": summary,
             "yearly": {"2024": {"strategy": summary}}}
    compact = _compact_stages({"rankings": {"artifact_id": "rank-id"}, "event_study": study})
    report = render_final_markdown({"legacy": {"development": compact, "validation": compact}},
                                   "2025-01-01", "2025-12-31")
    for window in ("development", "validation"):
        assert f"| legacy | {window} | 2024 | 2 | 1 | 20 | 1 | -1.00% | -1.00% | 100.00% |" in report
        assert f"| legacy | {window} | all | 2 | 1 | 5 | 1 | -1.00% | -1.00% | 100.00% |" in report


def test_best_revised_is_selected_honestly_when_weaker_than_original():
    legacy = _result("legacy", {2022: (50, .03), 2023: (50, .03), 2024: (50, .03)})
    revised = _result("revised", {2022: (50, .02), 2023: (50, .02), 2024: (50, .02)})
    selection = select_candidate_results(legacy, [revised])
    assert selection["selected_candidate_id"] == "revised"
    assert selection["beats_original"] is False
    assert "no optimized-edge claim" in selection["claim"]
