# Strategy Guide

## Overview

The Stock Screener uses a **multi-factor momentum scorecard** to rank stocks. This methodology is based on the research paper included in this repository.

---

## Factor Weights

| Factor | Weight | Description |
|--------|--------|-------------|
| **Trend** | 35% | EMA slope, price vs EMA |
| **Momentum** | 30% | RSI, PPO, PPO Histogram |
| **Volume** | 20% | Relative volume, price-volume correlation |
| **Structure** | 15% | Bollinger Band width, %B position |

---

## Trend Score (35%)

### Components
- **EMA 50 Slope** (70%): Trend velocity
- **Distance from EMA 200** (30%): Trend extension (Goldilocks curve)

### Goldilocks Curve
Optimal distance from 200 EMA is 10-20%. Too close = weak trend, too far = overextended.

---

## Momentum Score (30%)

### Components
- **Smoothed RSI** (60%): 14-period RSI with 5-period smoothing
- **PPO** (25%): Percentage Price Oscillator
- **PPO Histogram** (15%): PPO momentum

### RSI Regime Scoring
| RSI Range | Score | Interpretation |
|-----------|-------|----------------|
| 50-70 | 100 | Optimal momentum |
| 40-50 | 70 | Acceptable |
| 70-80 | 50 | Overbought caution |
| < 40 | 20 | Weak momentum |
| > 80 | 20 | Extreme overbought |

---

## Volume Score (20%)

### Components
- **Relative Volume** (50%): Volume / 20-day SMA
- **Price-Volume Correlation** (50%): 10-day correlation

High RVOL + positive correlation = accumulation (bullish)

---

## Structure Score (15%)

### Components
- **BB Width Z-Score** (50%): Volatility regime
- **%B Position** (50%): Position within Bollinger Bands

Low BB width = squeeze potential
%B near 0.5-0.7 = healthy uptrend

---

## Penalty Box

Stocks are assigned **0 score** if they trigger any of these conditions:

| Condition | Rule | Reason |
|-----------|------|--------|
| Broken Trend | Price < 200 EMA | Not in uptrend |
| ATR Spike | ATR > 2× 20-day avg | Excessive volatility |
| Liquidity Trap | Volume < 50% avg | Illiquid |

---

## Champion vs Challenger

When deciding to swap positions:

```
Swap if: challenger_score > incumbent_score × 1.25
```

The 25% buffer prevents excessive trading from minor score fluctuations.

---

## Exit Rules

1. **Score Degradation**: Exit if score < 40
2. **Stop-Loss**: ATR trailing or hard trailing triggered
3. **Manual Override**: User marks action as SKIPPED

---

## Position Sizing

ATR-based volatility sizing ensures equal risk per position:

```
shares = risk_per_trade / (ATR × stop_multiplier)
```

Example:
- Risk per trade: ₹1,000
- ATR: ₹25
- Stop multiplier: 2
- Shares = 1000 / (25 × 2) = 20 shares
