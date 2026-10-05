"""Standalone hybrid Momentum / Positional Trend backtest."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from src.domains.backtesting import BacktestRunManifest, BacktestStep, FillModelRevision, run
from src.domains.portfolio_engine import (
    Candidate,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
)
from src.domains.strategies import feature_series
from src.gates.backtesting_adapter import BacktestPortfolioEngineAdapter
from src.gates.composition import ApplicationServices
from src.gates.workflows.positional_trend_backtest_inputs import load_snapshot_universe
from src.platform_kernel import Money, QualityStatus


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "instance"
DB = DATA_DIR / "stock_screener.db"
START = date(2022, 1, 1)
END = date(2026, 10, 1)
OUTPUT = ROOT / "backtesting_results" / "intersection_momentum_positional_trend_corrected_2022-01-01_2026-10-01.json"


def main() -> None:
    services = ApplicationServices.create(DATA_DIR)
    momentum_revision = services.research.runtime.revision("momentum")
    pt_revision = services.research.runtime.revision("positional_trend_following")
    weeks = services.research.ranking_weeks("momentum")
    histories, sessions, coverage = load_snapshot_universe(DB, end_date=END.isoformat())
    ids_by_symbol = {symbol: instrument_id for instrument_id, (symbol, _) in histories.items()}
    symbols_by_id = {instrument_id: symbol for instrument_id, (symbol, _) in histories.items()}
    last_snapshot_day = max(day for day in coverage["membership_by_day"] if day <= END.isoformat())
    current_member_ids = {
        ids_by_symbol[symbol]
        for symbol in coverage["membership_by_day"][last_snapshot_day]["symbols"]
        if symbol in ids_by_symbol
    }

    session_dates = [date.fromisoformat(day) for day in sessions]
    session_index = {day: index for index, day in enumerate(session_dates)}
    buy_on_close: dict[date, set[str]] = defaultdict(set)
    exits_on_close: dict[date, set[str]] = defaultdict(set)
    rules = services.research.runtime.signal_rules("positional_trend_following")
    for instrument_id, (symbol, bars) in histories.items():
        for row in feature_series(bars, sessions, symbol, rules):
            signal_day = date.fromisoformat(row["signal_date"])
            if not START <= signal_day <= END:
                continue
            if row["filtered"]:
                buy_on_close[signal_day].add(instrument_id)
            if row["exit_signal"]:
                exits_on_close[signal_day].add(instrument_id)

    bars_by_day: dict[date, dict[str, MarketBar]] = defaultdict(dict)
    for instrument_id, (_, bars) in histories.items():
        for row in bars:
            day = date.fromisoformat(str(row["as_of_date"]))
            if START <= day <= END:
                bars_by_day[day][instrument_id] = MarketBar(
                    instrument_id,
                    day,
                    Decimal(str(row["open"])),
                    Decimal(str(row["high"])),
                    Decimal(str(row["low"])),
                    Decimal(str(row["close"])),
                    int(row["volume"]),
                )

    ranking_cache: dict[date, list[dict[str, object]]] = {}
    risk_cache: dict[date, dict[str, dict[str, object]]] = {}
    top15_by_day: dict[date, set[str]] = {}
    rank_week_by_day: dict[date, date] = {}
    steps: list[BacktestStep] = []
    entries_by_execution: dict[date, set[str]] = {}
    exits_by_execution: dict[date, set[str]] = {}
    upstream_rank_artifacts: set[str] = set()

    def ranking_for(day: date) -> tuple[list[dict[str, object]], date]:
        prior = [week for week in weeks if week < day]
        if not prior:
            raise RuntimeError(f"No completed Momentum ranking before {day}")
        week_end = prior[-1]
        if week_end not in ranking_cache:
            rows = services.research.all_rankings(week_end, "momentum")
            ranking_cache[week_end] = [
                row for row in rows if str(row["instrument_id"]) in current_member_ids
            ]
            ranking_cache[week_end].sort(
                key=lambda row: (-float(row["score"]), str(row["symbol"]))
            )
            if not ranking_cache[week_end]:
                raise RuntimeError(f"No Momentum ranks for the NIFTY 500 universe at {week_end}")
            upstream_rank_artifacts.update(str(row["artifact_id"]) for row in rows)
            risk_cache[week_end] = services.market.indicators_for_date(
                services.research._indicator_set("momentum", None), week_end
            )
        return ranking_cache[week_end], week_end

    for day in sorted(bars_by_day):
        index = session_index.get(day)
        if index is None or index == 0:
            continue
        signal_day = session_dates[index - 1]
        if not START <= day <= END:
            continue
        ranking, week_end = ranking_for(day)
        rank_week_by_day[day] = week_end
        top15_by_day[day] = {
            str(row["instrument_id"]) for row in ranking[:15]
        }
        candidates = []
        risk = risk_cache[week_end]
        for row in ranking:
            instrument_id = str(row["instrument_id"])
            if instrument_id not in bars_by_day[day]:
                continue
            values = risk.get(instrument_id, {})
            atr = values.get("atrr_14")
            close = values.get("close")
            candidates.append(
                Candidate(
                    instrument_id,
                    Decimal(str(row["score"])),
                    Decimal(1),
                    Decimal(str(atr)) if atr is not None and float(atr) > 0 else None,
                    Decimal(str(close)) if close is not None and float(close) > 0 else None,
                )
            )
        entries_by_execution[day] = buy_on_close.get(signal_day, set()) & top15_by_day[day]
        exits_by_execution[day] = exits_on_close.get(signal_day, set())
        steps.append(BacktestStep(day, tuple(candidates), bars_by_day[day]))
    if not steps:
        raise RuntimeError("No market replay sessions in requested period")

    # The requested policy has no ATR stop. Normalize only the engine's unused
    # protective-stop inputs to zero while retaining its score-exit/swap logic.
    from dataclasses import replace
    from src.domains.portfolio_engine import DecisionType, Holding

    class HybridAdapter(BacktestPortfolioEngineAdapter):
        def evaluate(
            self,
            state,
            policy,
            candidates,
            bars,
            assumptions,
            *,
            is_rebalance_day,
            score_candidates,
            forced_universe_exits,
        ):
            day = next(day for day, current_bars in bars_by_day.items() if current_bars is bars)
            signal_buys = entries_by_execution.get(day, set())
            filtered_candidates = []
            for candidate in candidates:
                if candidate.instrument_id not in signal_buys:
                    continue
                bar = bars[candidate.instrument_id]
                filtered_candidates.append(
                    replace(candidate, atr=bar.open, signal_close=bar.open)
                )
            no_stop_state = PortfolioState(
                state.cash,
                tuple(replace(holding, current_stop=Money(0)) for holding in state.holdings),
            )
            exits = frozenset(exits_by_execution.get(day, set()))
            decisions, next_state = super().evaluate(
                no_stop_state,
                policy,
                filtered_candidates,
                bars,
                assumptions,
                is_rebalance_day=is_rebalance_day,
                score_candidates=tuple(
                    replace(candidate, atr=None) for candidate in score_candidates
                ),
                forced_universe_exits=forced_universe_exits | exits,
            )
            if exits:
                decisions = tuple(
                    replace(
                        decision,
                        type=DecisionType.SELL,
                        reason="Positional Trend daily exit signal",
                    )
                    if decision.instrument_id in exits
                    and decision.type == DecisionType.UNIVERSE_EXIT
                    else decision
                    for decision in decisions
                )
            return decisions, next_state

    settings = services.research.runtime.portfolio_policy("momentum")
    policy = PortfolioPolicy(
        max_positions=int(settings["max_positions"]),
        exit_score=Decimal(str(settings["exit_threshold"])),
        max_position_fraction=min(
            Decimal(1) / Decimal(str(settings["max_positions"])),
            Decimal(str(settings["max_concentration_pct"])),
        ),
        swap_buffer=Decimal(str(settings["buffer_percent"])),
        max_volume_participation=Decimal(1),
        rebalance_frequency="WEEKLY",
        swap_cost_bps=Decimal(0),
        check_daily_sl=False,
        mid_week_buy=True,
    )
    starting_cash = Decimal(str(settings["initial_capital"]))
    fill_id = uuid5(NAMESPACE_URL, "hybrid-next-open-zero-cost-v1")
    fill_model = FillModelRevision(fill_id, "1.0.0")
    with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as connection:
        source_rows = connection.execute(
            "SELECT instrument_id, as_of_date, snapshot_id FROM market_bars "
            "WHERE instrument_id IN (%s) AND as_of_date BETWEEN ? AND ? "
            "ORDER BY instrument_id, as_of_date"
            % ",".join("?" for _ in histories),
            [*histories.keys(), "2021-01-01", END.isoformat()],
        ).fetchall()
    source_ids = sorted({str(row[2]) for row in source_rows})
    history_hash = hashlib.sha256(
        json.dumps(source_rows, separators=(",", ":")).encode()
    ).hexdigest()
    policy_payload = {
        "entry": "Positional Trend filtered BUY at prior close AND Momentum top 15 in latest completed weekly rank",
        "exit": "Positional Trend daily exit OR Momentum weekly score below threshold OR Momentum swap",
        "top15_is_entry_gate_only": True,
        "momentum_atr_stops": "disabled",
        "max_positions": policy.max_positions,
        "score_exit_threshold": str(policy.exit_score),
        "swap_buffer": str(policy.swap_buffer),
        "rebalance_frequency": policy.rebalance_frequency,
        "mid_week_entries": True,
        "starting_cash": str(starting_cash),
        "slippage_bps": "0",
        "fee_bps": "0",
        "tax_bps": "0",
        "historical_universe": "2026 NIFTY 500 constituents applied retrospectively; only 2026 membership snapshots are stored",
        "universe_snapshot_id": coverage["membership_by_day"][last_snapshot_day]["snapshot_id"],
        "bar_history_sha256": history_hash,
        "bar_count": len(source_rows),
        "momentum_rank_weeks": len(ranking_cache),
    }
    policy_revision = uuid5(
        NAMESPACE_URL,
        "hybrid-policy:" + hashlib.sha256(json.dumps(policy_payload, sort_keys=True).encode()).hexdigest(),
    )
    run_id = uuid4()
    code_paths = [
        ROOT / "src/domains/backtesting/simulation.py",
        ROOT / "src/domains/portfolio_engine/api.py",
        ROOT / "src/domains/strategies/positional_trend.py",
        ROOT / "src/domains/indicators/momentum_quality.py",
        ROOT / "src/domains/strategies/momentum_quality.py",
        Path(__file__),
    ]
    code_hash = hashlib.sha256(b"".join(path.read_bytes() for path in code_paths)).hexdigest()
    manifest = BacktestRunManifest(
        run_id,
        tuple(sorted(set(source_ids) | upstream_rank_artifacts | {
            str(pt_revision["revision_id"]),
        })),
        UUID(str(momentum_revision["revision_id"])),
        policy_revision,
        fill_id,
        "portfolio-engine-hybrid-v1",
        steps[0].as_of_date,
        steps[-1].as_of_date,
        {key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
         for key, value in policy_payload.items()},
        code_hash,
    )
    result = run(
        PortfolioState(Money(starting_cash)),
        policy,
        tuple(steps),
        manifest,
        fill_model,
        portfolio_engine=HybridAdapter(),
    )
    payload = result.to_payload()
    payload.update(
        {
            "strategy_id": "momentum_positional_trend_intersection",
            "strategy_revisions": {
                "momentum": str(momentum_revision["revision_id"]),
                "positional_trend_following": str(pt_revision["revision_id"]),
            },
            "methodology": policy_payload,
            "data": {
                **coverage,
                "historical_membership": "current NIFTY 500 constituents applied retrospectively; only 2026 snapshots are stored",
                "bar_count": len(source_rows),
                "bar_snapshot_count": len(source_ids),
                "bar_history_sha256": history_hash,
            },
            "limitations": [
                "Current NIFTY 500 constituents are applied retrospectively because historical membership snapshots are absent.",
                "Stored provider OHLCV adjustment basis; corporate actions are not adjusted per project research scope.",
                "Zero execution costs assumed: slippage, fees, and taxes are all zero.",
                "This is an exploratory historical replay, not live-trading evidence.",
            ],
            "signal_counts": {
                "positional_trend_buy_signals": sum(map(len, buy_on_close.values())),
                "positional_trend_exit_signal_days": sum(map(len, exits_on_close.values())),
                "joint_buy_signals": sum(map(len, entries_by_execution.values())),
                "weekly_rankings_used": len(ranking_cache),
            },
        }
    )
    payload["summary"] = {
        "starting_equity": str(result.starting_equity),
        "ending_equity": str(payload["ending_equity"]),
        **{key: str(value) for key, value in result.metrics.items()},
        "closed_trades": len(result.completed_trades),
        "buy_fills": result.trade_counts["buy"],
        "sell_fills": result.trade_counts["sell"],
        "score_exits": sum(
            getattr(fill.decision_type, "value", fill.decision_type) == "SCORE_EXIT"
            for fill in result.fills
        ),
        "positional_trend_exits": sum(
            fill.side == "SELL"
            and getattr(fill.decision_type, "value", fill.decision_type) == "SELL"
            for fill in result.fills
        ),
        "swap_sells": sum(
            getattr(fill.decision_type, "value", fill.decision_type) == "SWAP_SELL"
            for fill in result.fills
        ),
        "open_positions": len(result.final_state.holdings),
    }
    OUTPUT.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "period": [steps[0].as_of_date.isoformat(), steps[-1].as_of_date.isoformat()],
        "summary": payload["summary"],
        "signals": payload["signal_counts"],
        "source_bars": len(source_rows),
    }, indent=2))


if __name__ == "__main__":
    main()
