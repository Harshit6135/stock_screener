# Strategy 3 candidate research — 2026-09-26

This experiment compares the unchanged legacy rule set with six prespecified challengers. Each challenger changes exactly one rule. There are no combinations, parameter sweeps, or post-result threshold choices.

| ID | Sole change | Hypothesis |
|---|---|---|
| `C1_prior10_squeeze` | `squeeze_mode = prior10_minimum` | A recent volatility contraction may be a more useful setup condition than requiring contraction on the breakout session itself. |
| `C2_prior20_high_cross` | `trigger = prior20_high_cross` | A fresh short-horizon price breakout may identify momentum onset more directly than the legacy Bollinger-band cross. |
| `C3_strong_close` | `close_location_minimum = 0.75` | A breakout closing in the upper quarter of its daily range may show stronger demand. A zero-range session is rejected; the implementation's neutral close-location convention is 0.5, not a passing value. |
| `C4_bounded_daily_move` | `max_daily_move_atr = 2.0` | Excluding unusually extended one-day moves may reduce late entries. |
| `C5_raw63_skip5` | `ranking_factor = momentum_63_skip5` | Medium-term momentum with the most recent five sessions skipped may be a useful alternative cross-sectional rank. The log-return representation is monotonic with the equivalent simple return, so ranking and positivity are preserved. |
| `C6_benchmark_uptrend` | `benchmark_regime_required = true` | Requiring an upward benchmark regime may avoid hostile broad-market conditions. |

All unspecified fields retain the explicit application defaults. The unchanged `legacy` candidate is evaluated through the identical development pipeline and cutoff for a fair reference.

## Prespecified method

- Development signals begin `2022-01-03`; every selected event must have its twentieth exchange-session outcome no later than `2024-12-31`.
- Eligibility requires at least 150 complete 20-session events overall and at least 30 in each of 2022, 2023, and 2024.
- The primary objective is the equal-weight mean of the three yearly 20-session mean returns. Ties prefer the higher worst-year mean, then lexical candidate ID.
- Missing outcomes and missing years are not treated as zero.
- The best eligible revised candidate is selected even if it is weaker than legacy, but `beats_original` must then be false and no optimized-edge claim is permitted.

## Sources and interpretation

- [Bollinger Band rules](https://www.bollingerbands.com/bollinger-band-rules)
- [Brock, Lakonishok, and LeBaron technical trading rules study](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04681.x)
- [Bollinger Bands screening guidance](https://bollingerbands.us/help-screening.php)
- [Momentum Crashes / momentum research reference](https://www.kentdaniel.net/papers/published/mom12.pdf)
- [Erasmus University momentum research](https://repub.eur.nl/pub/22252)
- [Faber timing model](https://mebfaber.com/timing-model/)

These references support the hypotheses being tested. They do not establish any exact threshold in this candidate set as optimal.

## Known limitations

- Zero corporate-action facts existed at experiment time.
- The data uses the current survivor universe and is subject to survivorship bias.
- The validation period had previously been viewed, so it is not blind validation.
- Returns exclude costs and slippage per user instruction.
