"""Alternative indicator-path calculations used to compare strategy revisions."""

from __future__ import annotations

import math
from importlib import import_module

import pandas as pd

from src.domains.strategies.positional_trend import _segment_features, valid_bar


def pandas_ta_features(
    bars: list[dict], sessions: list[str], symbol: str, rules: dict | None = None
) -> list[dict]:
    """Change only Supertrend and its dependent entry, anchor and exit decisions."""
    rules = rules or {}
    by_date = {str(bar["as_of_date"]): bar for bar in bars}
    segments, segment = [], []
    for day in sessions:
        bar = by_date.get(day)
        if bar is None:
            continue
        if not valid_bar(bar):
            if segment:
                segments.append(segment)
                segment = []
        else:
            segment.append(bar)
    if segment:
        segments.append(segment)
    result = []
    supertrend = import_module("pandas_ta.overlap.supertrend").supertrend
    for segment in segments:
        rows = _segment_features(segment, symbol, rules)
        if not rows:
            continue
        frame = pd.DataFrame(segment).set_index("as_of_date")
        values = supertrend(
            frame["high"].astype(float),
            frame["low"].astype(float),
            frame["close"].astype(float),
            length=int(rules.get("atr_period", 10)),
            atr_length=int(rules.get("atr_period", 10)),
            multiplier=float(rules.get("supertrend_multiplier", 3)),
            atr_mamode="rma",
        )
        if values is None:
            raise ValueError(f"pandas-ta Supertrend produced no values for {symbol}")
        line_column = next(column for column in values if column.startswith("SUPERT_"))
        direction_column = next(column for column in values if column.startswith("SUPERTd_"))
        lines = values[line_column].to_dict()
        directions = values[direction_column].to_dict()
        for row in rows:
            line = float(lines[row["signal_date"]])
            if not math.isfinite(line):
                raise ValueError(
                    f"pandas-ta Supertrend is not warmed for {symbol} at {row['signal_date']}"
                )
            bullish = bool(directions[row["signal_date"]] > 0)
            row.update(
                {
                    "supertrend": line,
                    "supertrend_bullish": bullish,
                    "initial_stop_anchor": max(line, row["lower20"]),
                    "filtered": bool(
                        row["first_cross"]
                        and row["adx14"] is not None
                        and row["adx14"] > float(rules.get("adx_minimum", 25))
                        and bullish
                        and row["close"] > line
                    ),
                    "exit_signal": bool(row["close"] < line or row["close"] < row["lower20"]),
                }
            )
        result.extend(rows)
    return result
