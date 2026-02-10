# Swagger Organization — Granular Tags + Redoc with x-tagGroups

Reporting for duty, M. Time to give our intel dashboard some proper organization.

## Problem

All Swagger endpoints crammed into 5 generic tags — `System`, `Data Pipeline`, `Trading`, `Analysis`, `Backtest`. The `Data Pipeline` tag alone holds ~25+ endpoints from 5 route files.

## Proposed Changes

### Phase 1: Flask Config — Add Redoc + Tag Groups

#### [MODIFY] [flask_config.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/config/flask_config.py)

Add Redoc serving config and `API_SPEC_OPTIONS` with `x-tagGroups`:

```python
OPENAPI_REDOC_PATH = "/redoc"
OPENAPI_REDOC_URL = "https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"

API_SPEC_OPTIONS = {
    "x-tagGroups": [
        {"name": "System & Config", "tags": ["Initialization", "App Orchestration", "Configuration"]},
        {"name": "Data Pipeline", "tags": ["Instruments", "Market Data", "Indicators", "Percentiles", "Scores", "Rankings"]},
        {"name": "Trading", "tags": ["Actions", "Investments"]},
        {"name": "Analysis", "tags": ["Transaction Costs", "Tax Analysis"]},
        {"name": "Backtest", "tags": ["Backtest"]}
    ]
}
```

---

### Phase 2: Rename Tags in ALL Route Files

| Route File | Current Tag | New Tag |
|---|---|---|
| `init_routes.py` | System | Initialization |
| `app_routes.py` | System | App Orchestration |
| `config_routes.py` | System | Configuration |
| `instrument_routes.py` | Data Pipeline | Instruments |
| `marketdata_routes.py` | Data Pipeline | Market Data |
| `indicators_routes.py` | Data Pipeline | Indicators |
| `percentile_routes.py` | Data Pipeline | Percentiles |
| `score_routes.py` | Data Pipeline | Scores |
| `ranking_routes.py` | Data Pipeline | Rankings |
| `actions_routes.py` | Trading | Actions |
| `investment_routes.py` | Trading | Investments |
| `costs_routes.py` | Analysis | Transaction Costs |
| `tax_routes.py` | Analysis | Tax Analysis |
| `backtest_routes.py` | Backtest | Backtest |

**All 14 route files accounted for.** Only `backtest_routes.py` keeps its existing tag.

**Complexity: 2/10** — Mechanical string replacements + config addition.

## Result

- `/swagger-ui` → 14 distinct collapsible tag sections
- `/redoc` → 5 grouped subheadings with nested tags

## Verification Plan

### Manual Verification
1. Start the Flask app
2. Open `/swagger-ui` — verify 14 distinct tag sections
3. Open `/redoc` — verify 5 group headings with nested tags
