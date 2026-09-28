"""Minimal, isolated CLI for Strategy 3 rule experiments.

This module deliberately composes only the market repository and artifact
services needed by Strategy 3.  In particular it never constructs
ApplicationServices (which would also initialise unrelated strategy writers).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any
from uuid import NAMESPACE_URL, uuid5

# Direct execution sets sys.path[0] to ``tools`` rather than the repository.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.application.catalog import ArtifactCatalog
from src.application.early_momentum import (
    EarlyMomentumJobs,
    adjust_bars,
    digest,
    evaluate_event,
    rank_day,
)
from src.application.early_momentum_rules import DEFAULT_RULES, parse_rules
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.platform_kernel import DomainValidationError, QualityStatus, SqliteArtifactStore

DEVELOPMENT_CUTOFF = "2024-12-31"
DEVELOPMENT_START = "2022-01-03"
DEVELOPMENT_YEARS = (2022, 2023, 2024)
MIN_COMPLETE20 = 150
MIN_COMPLETE20_PER_YEAR = 30
LIMITATIONS = (
    "0 corporate-action facts existed at experiment time; nominal bars are therefore unadjusted by recorded facts",
    "The instrument set is the current survivor universe; results are subject to survivorship bias",
    "The validation period had previously been viewed, so this was not a blind validation",
    "Returns exclude transaction costs and slippage, per user instruction",
)


def _digest(value: object) -> str:
    """Use the application's canonical hash encoding for interoperable IDs."""
    return digest(value)


def _expected_feature_hash() -> str:
    indicator = REPOSITORY_ROOT / "src" / "indicators" / "custom" / "early_momentum.py"
    return digest(indicator.read_text(encoding="utf-8"))


def _context(label: str = "strategy3"):
    class Context:
        def __init__(self) -> None:
            self.last_phase: object = None
            self.last_emit = 0.0
            self.calls = 0

        def checkpoint(self, **values: object) -> None:
            progress = values.get("progress")
            if not isinstance(progress, dict):
                return
            self.calls += 1
            phase = progress.get("stage")
            now = time.monotonic()
            if phase != self.last_phase or self.calls % 50 == 0 or now - self.last_emit >= 10:
                details = " ".join(f"{key}={value}" for key, value in progress.items())
                print(f"[{label}] {details}", file=sys.stderr, flush=True)
                self.last_phase, self.last_emit = phase, now
    return Context()


def build_runtime(database: str | Path) -> tuple[EarlyMomentumJobs, ArtifactPublisher]:
    """Compose the minimal production runtime; no ApplicationServices.create."""
    database = Path(database)
    market = MarketRepository(database)
    publisher = ArtifactPublisher(SqliteArtifactStore(database), ArtifactCatalog(database))
    return EarlyMomentumJobs(market, publisher, runtime=None), publisher


def _candidate_document(value: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Accept the documented object shape, plus a list for simple research files."""
    if isinstance(value, list):
        entries, legacy = value, None
    elif isinstance(value, dict):
        entries = value.get("candidates")
        legacy = value.get("original") or value.get("legacy")
    else:
        raise DomainValidationError("candidate JSON must be an object or array")
    if not isinstance(entries, list) or not entries:
        raise DomainValidationError("candidate JSON requires a non-empty candidates array")
    candidates = [_normalise_candidate(item) for item in entries]
    if legacy is None:
        originals = [item for item in candidates if item.get("is_original")]
        if len(originals) != 1:
            raise DomainValidationError("candidate JSON requires exactly one original/legacy reference")
        legacy_candidate = originals[0]
        candidates = [item for item in candidates if item is not legacy_candidate]
    else:
        legacy_candidate = _normalise_candidate(legacy, original=True)
    if not candidates:
        raise DomainValidationError("at least one revised candidate is required")
    ids = [legacy_candidate["candidate_id"], *(item["candidate_id"] for item in candidates)]
    if len(ids) != len(set(ids)):
        raise DomainValidationError("candidate_id values must be unique")
    return legacy_candidate, candidates


def _normalise_candidate(value: object, *, original: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("candidate_id"), str) or not value["candidate_id"]:
        raise DomainValidationError("each candidate requires a non-empty candidate_id")
    rules = parse_rules(value.get("rules")).to_dict()
    return {"candidate_id": value["candidate_id"], "rules": rules,
            "rules_hash": _digest(rules), "is_original": bool(value.get("is_original", original))}


def _stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "p90": ordered[math.ceil(len(ordered) * .9) - 1] if ordered else None,
    }


def horizon_stats(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    events = list(events)
    result: dict[str, Any] = {}
    for horizon in (1, 2, 5, 10, 20):
        complete = [event for event in events if event.get(f"h{horizon}_status") == "complete"]
        returns = [float(event[f"return_{horizon}"]) for event in complete]
        result[str(horizon)] = {
            "return": _stats(returns),
            "mae": _stats([float(event[f"mae_{horizon}"]) for event in complete]),
            "mfe": _stats([float(event[f"mfe_{horizon}"]) for event in complete]),
            "failed_breakout_rate": sum(value < 0 for value in returns) / len(returns) if returns else None,
        }
    return result


def score_candidate(candidate: dict[str, Any], events: Iterable[dict[str, Any]],
                    *, years: tuple[int, ...] = DEVELOPMENT_YEARS) -> dict[str, Any]:
    """Score only executed, fully matured h20 events; absent years are not zero."""
    events = list(events)
    complete = [event for event in events
                if event.get("execution_status") == "executed"
                and event.get("h20_status") == "complete"
                and event.get("h20_session", event.get("outcome_20_session")) is not None
                and event.get("h20_session", event.get("outcome_20_session")) <= DEVELOPMENT_CUTOFF]
    by_year = {str(year): [event for event in complete if str(event["signal_date"]).startswith(str(year))]
               for year in years}
    yearly = {year: {"horizons": horizon_stats(sample), "complete20_count": len(sample),
                     "raw_signal_count": sum(str(event["signal_date"]).startswith(year) for event in events),
                     "executed_count": sum(event.get("execution_status") == "executed"
                                           for event in events if str(event["signal_date"]).startswith(year)),
                     "mean_return_20": mean([float(e["return_20"]) for e in sample]) if sample else None}
              for year, sample in by_year.items()}
    counts_ok = len(complete) >= MIN_COMPLETE20 and all(len(by_year[str(year)]) >= MIN_COMPLETE20_PER_YEAR for year in years)
    means = [yearly[str(year)]["mean_return_20"] for year in years]
    eligible = counts_ok and all(value is not None for value in means)
    return {
        **candidate,
        "raw_signal_count": len(events),
        "executed_count": sum(event.get("execution_status") == "executed" for event in events),
        "complete20_count": len(complete),
        "yearly": yearly,
        "eligible": eligible,
        "ineligibility_reasons": ([] if eligible else [
            *( [f"fewer than {MIN_COMPLETE20} complete20 events overall"] if len(complete) < MIN_COMPLETE20 else []),
            *( [f"fewer than {MIN_COMPLETE20_PER_YEAR} complete20 events in {year}"]
               for year in years if len(by_year[str(year)]) < MIN_COMPLETE20_PER_YEAR),
        ]),
        "objective_equal_weight_yearly_mean_20": mean(means) if eligible else None,
        "worst_year_mean_20": min(means) if eligible else None,
        "horizons": horizon_stats(complete),
    }


def select_candidate_results(original: dict[str, Any], revised: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the best eligible revised result without consulting holdout data."""
    eligible = [item for item in revised if item.get("eligible")]
    if not eligible:
        raise DomainValidationError("no revised candidate meets development sample requirements")
    selected = min(eligible, key=lambda item: (
        -float(item["objective_equal_weight_yearly_mean_20"]),
        -float(item["worst_year_mean_20"]), item["candidate_id"]))
    original_objective = original.get("objective_equal_weight_yearly_mean_20")
    beats = bool(original.get("eligible") and original_objective is not None
                 and selected["objective_equal_weight_yearly_mean_20"] > original_objective)
    return {
        "selected_candidate_id": selected["candidate_id"],
        "selected_rules": selected["rules"],
        "selected_rules_hash": selected["rules_hash"],
        "beats_original": beats,
        "claim": ("Selected revised rules beat the legacy reference on the prespecified development objective."
                  if beats else "Selected revised rules did not beat the legacy reference; no optimized-edge claim is made."),
    }


def _maturity_sessions(sessions: list[str]) -> dict[str, str]:
    return {session: sessions[index + 20] for index, session in enumerate(sessions[:-20])}


@dataclass
class ExperimentRunner:
    jobs: EarlyMomentumJobs
    publisher: ArtifactPublisher

    def development(self, start: str, end: str, candidate_file: str | Path) -> dict[str, Any]:
        if (start, end) != (DEVELOPMENT_START, DEVELOPMENT_CUTOFF):
            raise DomainValidationError(
                f"development range must be exactly {DEVELOPMENT_START} through {DEVELOPMENT_CUTOFF}"
            )
        start_date, end_date = self.jobs._dates({"start_date": start, "end_date": end})
        raw_id, raw = self.jobs._load("indicators", start_date, end_date)
        if raw.get("indicator_feature_hash") != _expected_feature_hash():
            raise DomainValidationError("Strategy 3 indicator feature implementation hash is stale")
        legacy, revised = _candidate_document(json.loads(Path(candidate_file).read_text(encoding="utf-8")))
        # Selection must not even read holdout outcomes.  The raw artifact may
        # span farther, but both raw rows and market bars are bounded here.
        evaluation_end = min(end_date, date.fromisoformat(DEVELOPMENT_CUTOFF))
        histories, facts, benchmark_id = self.jobs._source(start_date, evaluation_end)
        if _digest([histories, facts]) != raw.get("source_hash"):
            raise DomainValidationError("Strategy 3 indicators are stale after source changes")
        sessions = [str(bar["as_of_date"]) for bar in histories[benchmark_id][0]]
        maturity = _maturity_sessions(sessions)
        adjusted = {key: {str(bar["as_of_date"]): bar for bar in adjust_bars(bars, facts.get(key, []), evaluation_end)}
                    for key, (bars, _) in histories.items()}
        by_day: dict[str, dict[str, Any]] = defaultdict(dict)
        for instrument_id, series in raw["rows"].items():
            for day, values in series.items():
                by_day[day][instrument_id] = values

        evaluated = []
        for candidate in [legacy, *revised]:
            events: list[dict[str, Any]] = []
            for day, values in sorted(by_day.items()):
                if day > DEVELOPMENT_CUTOFF or maturity.get(day, "9999-12-31") > DEVELOPMENT_CUTOFF:
                    continue
                for instrument_id, item in rank_day(values, candidate["rules"]).items():
                    if item["raw_signal"]:
                        event = evaluate_event(day, item, adjusted.get(instrument_id, {}), sessions)
                        event["instrument_id"] = instrument_id
                        event["h20_session"] = maturity.get(day)
                        events.append(event)
            evaluated.append(score_candidate(candidate, events))
        original_result, revised_results = evaluated[0], evaluated[1:]
        selection = select_candidate_results(original_result, revised_results)
        return {
            "schema_version": 1,
            "stage": "experiment-development",
            "signal_start_date": start,
            "signal_end_date": end,
            "development_outcome_cutoff": DEVELOPMENT_CUTOFF,
            "raw_artifact_id": raw_id,
            "raw_source_hash": raw["source_hash"],
            "development_evaluation_source_hash": _digest([histories, facts]),
            "candidate_file_hash": _digest(json.loads(Path(candidate_file).read_text(encoding="utf-8"))),
            "rules_hashes": {item["candidate_id"]: item["rules_hash"] for item in evaluated},
            "selection_policy": {
                "years": list(DEVELOPMENT_YEARS), "minimum_complete20_overall": MIN_COMPLETE20,
                "minimum_complete20_per_year": MIN_COMPLETE20_PER_YEAR,
                "primary": "equal-weight yearly 20-day mean",
                "tie_breaks": ["higher worst-year 20-day mean", "candidate_id lexical"],
                "holdout_used": False,
            },
            "limitations": list(LIMITATIONS),
            "original": original_result,
            "candidates": revised_results,
            "selection": selection,
        }

    def publish_development(self, result: dict[str, Any], report_path: str | Path | None = None) -> dict[str, Any]:
        artifact_id = str(uuid5(NAMESPACE_URL, _digest(result)))
        category = "research/strategy3-experiment-development"
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(category, artifact_id, result,
                                        upstream_ids=(result["raw_artifact_id"],), quality=QualityStatus.PARTIAL)
        if report_path:
            Path(report_path).write_text(render_markdown(result, artifact_id), encoding="utf-8")
        return {"artifact_id": artifact_id, "category": category, **result["selection"]}

    def freeze(self, development_artifact_id: str, output: str | Path | None = None,
               report_path: str | Path | None = None) -> dict[str, Any]:
        _, development = self.publisher.store.read_json(
            "research/strategy3-experiment-development", development_artifact_id)
        selection = development["selection"]
        frozen = {
            "schema_version": 1, "strategy_id": "strategy3", "status": "frozen",
            "rules": selection["selected_rules"], "rules_hash": selection["selected_rules_hash"],
            "candidate_id": selection["selected_candidate_id"], "beats_original": selection["beats_original"],
            "claim": selection["claim"], "development_artifact_id": development_artifact_id,
            "raw_artifact_id": development["raw_artifact_id"], "raw_source_hash": development["raw_source_hash"],
            "development_outcome_cutoff": development["development_outcome_cutoff"],
            "limitations": development["limitations"],
        }
        artifact_id = str(uuid5(NAMESPACE_URL, _digest(frozen)))
        category = "research/strategy3-frozen-rules"
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(category, artifact_id, frozen,
                                        upstream_ids=(development_artifact_id,), quality=QualityStatus.PARTIAL)
        envelope = {"artifact_id": artifact_id, "category": category, **frozen}
        if output:
            Path(output).write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if report_path:
            Path(report_path).write_text(render_markdown(development, development_artifact_id), encoding="utf-8")
        return envelope


def _percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "n/a"


def _append_horizon_rows(lines: list[str], candidate: str, window: str, year: str,
                         signals: int | str, executed: int | str, horizons: dict[str, Any]) -> None:
    for horizon in ("1", "5", "10", "20"):
        summary = horizons[horizon]
        returns = summary["return"]
        lines.append(f"| {candidate} | {window} | {year} | {signals} | {executed} | {horizon} | "
                     f"{returns['count']} | {_percent(returns['mean'])} | {_percent(returns['median'])} | "
                     f"{_percent(summary['failed_breakout_rate'])} |")


def render_markdown(result: dict[str, Any], artifact_id: str) -> str:
    selected = result["selection"]
    lines = ["# Strategy 3 development experiment", "", f"Artifact: `{artifact_id}`", "",
             f"Selected: `{selected['selected_candidate_id']}`", "",
             f"Beats original: `{str(selected['beats_original']).lower()}`", "", selected["claim"], "",
             "## Candidate results", "", "| Candidate | Eligible | Complete h20 | Objective | Worst year |", "|---|---:|---:|---:|---:|"]
    for item in [result["original"], *result["candidates"]]:
        objective = item.get("objective_equal_weight_yearly_mean_20")
        worst = item.get("worst_year_mean_20")
        lines.append(f"| {item['candidate_id']} | {item['eligible']} | {item['complete20_count']} | {_percent(objective)} | {_percent(worst)} |")
    lines.extend(["", "## Returns by candidate and year", "",
                  "Development returns use executed events with complete 20-session outcomes by the cutoff.", "",
                  "| Candidate | Window | Year | Signals | Executed | Horizon | Complete | Mean | Median | Failure |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"])
    for item in [result["original"], *result["candidates"]]:
        _append_horizon_rows(lines, item["candidate_id"], "development", "all",
                             item.get("raw_signal_count", "n/a"), item.get("executed_count", "n/a"),
                             item["horizons"])
        for year, yearly in sorted(item["yearly"].items()):
            _append_horizon_rows(lines, item["candidate_id"], "development", year,
                                 yearly.get("raw_signal_count", "n/a"),
                                 yearly.get("executed_count", "n/a"), yearly["horizons"])
    lines.extend(["", "## Limitations", ""] + [f"- {item}" for item in result["limitations"]])
    return "\n".join(lines) + "\n"


def render_final_markdown(results: dict[str, Any], start: str, end: str) -> str:
    lines = ["# Strategy 3 final comparison", "", f"Holdout signal window: `{start}` through `{end}`", "",
             "| Rules | Window | Event-study artifact | Complete h20 | Mean h20 |", "|---|---|---|---:|---:|"]
    for candidate_id, windows in results.items():
        for window in ("development", "validation"):
            item = windows[window]
            lines.append(f"| {candidate_id} | {window} | {item['event_study_artifact_id']} | {item['complete20_count']} | {_percent(item['mean_return_20'])} |")
    lines.extend(["", "## Returns by window and year", "",
                  "| Rules | Window | Year | Signals | Executed | Horizon | Complete | Mean | Median | Failure |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for candidate_id, windows in results.items():
        for window in ("development", "validation"):
            item = windows[window]
            _append_horizon_rows(lines, candidate_id, window, "all", item["raw_signal_count"],
                                 item["executed_count"], item["horizons"])
            for year, yearly in sorted(item["yearly"].items()):
                _append_horizon_rows(lines, candidate_id, window, year, yearly["raw_signal_count"],
                                     yearly["executed_count"], yearly["horizons"])
    lines.extend(["", "## Limitations", ""] + [f"- {item}" for item in LIMITATIONS])
    return "\n".join(lines) + "\n"


def _load_rules(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict) and "rules" in value:
        rules = parse_rules(value["rules"]).to_dict()
        if "rules_hash" in value and value["rules_hash"] != _digest(rules):
            raise DomainValidationError(f"frozen rules hash does not match rules in {path}")
        return rules
    return parse_rules(value).to_dict()


def _compact_stages(stages: dict[str, Any]) -> dict[str, Any]:
    study = stages["event_study"]
    summary = study["summary"]
    h20 = summary["horizons"]["20"]["return"]
    return {
        "rankings_artifact_id": stages["rankings"]["artifact_id"],
        "event_study_artifact_id": study["artifact_id"],
        "rules_hash": study["rules_hash"],
        "raw_signal_count": summary["raw_signal_count"],
        "executed_count": summary["execution_status_counts"].get("executed", 0),
        "complete20_count": h20["count"],
        "mean_return_20": h20["mean"],
        "horizons": summary["horizons"],
        "yearly": {year: {
            "raw_signal_count": item["strategy"]["raw_signal_count"],
            "executed_count": item["strategy"]["execution_status_counts"].get("executed", 0),
            "complete20_count": item["strategy"]["horizons"]["20"]["return"]["count"],
            "mean_return_20": item["strategy"]["horizons"]["20"]["return"]["mean"],
            "horizons": item["strategy"]["horizons"],
        } for year, item in study["yearly"].items()},
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database", type=Path, default=Path("instance/system.db"))
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("indicators", "experiment-development", "final"):
        command = commands.add_parser(name)
        command.add_argument("--start", required=True)
        command.add_argument("--end", required=True)
    development = commands.choices["experiment-development"]
    development.add_argument("--candidates", type=Path, required=True)
    development.add_argument("--report", type=Path)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--development-artifact-id", required=True)
    freeze.add_argument("--output", type=Path)
    freeze.add_argument("--report", type=Path)
    final = commands.choices["final"]
    final.add_argument("--rules", type=Path, required=True)
    final.add_argument("--candidate-id", default="selected")
    final.add_argument("--legacy-rules", type=Path)
    final.add_argument("--legacy-id", default="legacy")
    final.add_argument("--evaluation-end")
    final.add_argument("--report", type=Path)
    final.add_argument("--output", type=Path, help="write the full development/validation result JSON")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    jobs, publisher = build_runtime(args.database)
    runner = ExperimentRunner(jobs, publisher)
    if args.command == "indicators":
        output = jobs.rebuild_indicators({"start_date": args.start, "end_date": args.end}, _context("indicators"))
    elif args.command == "experiment-development":
        output = runner.publish_development(runner.development(args.start, args.end, args.candidates), args.report)
    elif args.command == "freeze":
        output = runner.freeze(args.development_artifact_id, args.output, args.report)
    else:
        supplied = [(args.legacy_id, args.legacy_rules)]
        supplied.append((args.candidate_id, args.rules))  # selected runs last and remains current
        comparisons: dict[str, dict[str, Any]] = {candidate_id: {} for candidate_id, _ in supplied}
        windows = (
            ("development", DEVELOPMENT_START, DEVELOPMENT_CUTOFF, DEVELOPMENT_CUTOFF),
            ("validation", args.start, args.end, args.evaluation_end),
        )
        for window, start, end, evaluation_end in windows:
            for candidate_id, rules_path in supplied:
                rules = _load_rules(rules_path) if rules_path else DEFAULT_RULES.to_dict()
                payload = {"start_date": start, "end_date": end, "rules": rules}
                label = f"{window}:{candidate_id}"
                rankings = jobs.rebuild_rankings(payload, _context(label + ":rankings"))
                study_payload = {"start_date": start, "end_date": end}
                if evaluation_end:
                    study_payload["evaluation_end_date"] = evaluation_end
                event_study = jobs.event_study(study_payload, _context(label + ":event-study"))
                comparisons[candidate_id][window] = {"rankings": rankings, "event_study": event_study}
        compact = {candidate_id: {window: _compact_stages(stages) for window, stages in windows.items()}
                   for candidate_id, windows in comparisons.items()}
        if args.report:
            args.report.write_text(render_final_markdown(compact, args.start, args.end), encoding="utf-8")
        if args.output:
            args.output.write_text(json.dumps(comparisons, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output = compact
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DomainValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
