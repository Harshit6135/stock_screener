# V3 to V4 Feature Parity & Porting Status

Last updated: 2026-09-13

All 12 feature gaps previously identified between `dead-code-cleanup` (V3) and `feature/codex_enhancement` (V4) have been ported, integrated, and verified with automated test coverage. V4 retains its domain-driven invariants (append-only ledger, immutable artifacts, typed boundaries) while exposing full compatibility for the legacy dashboard UI and API contracts.

---

### Porting Ledger & Verification Summary

| # | Feature / Gap | V3 Baseline | V4 Port Implementation | Status |
|---|---|---|---|---|
| 1 | **Automatic Day-0 Universe with YFinance & Screening** | `init_service.py` joined NSE/BSE CSVs, queried YFinance, and screened mcap ≥ ₹500 Cr & px ≥ ₹75. | `market_jobs.py` (`enrich_and_sync_universe`) and `yfinance_provider.py` (`fetch_symbol_enrichment`), exposed at `POST /api/v1/init/enrich` and worker job `reference.enrich-day0-universe`. | **PORTED & VERIFIED** |
| 2 | **YFinance Fallback for NIFTY 500 Benchmark** | `benchmark_adaptor.py` fell back to YFinance `^CNX500` if Kite had no data. | `research_jobs.py:276-279` catches missing benchmark and invokes `download_daily_bars("^CNX500", ...)` from `yfinance_provider.py`. | **PORTED & VERIFIED** |
| 3 | **Persisted, Patchable Indicator Catalogue** | `indicators_config.py` & `indicators_service.py` with `/indicators/patch`. | `POST /api/v1/indicators/patch` and `GET /api/v1/indicators/<symbol>` in `compatibility_web.py` submit research recalculations and query latest bar indicators. | **PORTED & VERIFIED** |
| 4 | **Direct Bulk Market-Data & Indicator Maintenance API** | Bulk OHLCV/indicator insert and deletion endpoints in `marketdata_routes.py` & `indicators_routes.py`. | `POST /api/v1/marketdata`, `GET /api/v1/marketdata/latest-date`, `GET/DELETE /api/v1/marketdata/<symbol>`, and `POST/DELETE /api/v1/indicators` in `compatibility_web.py`. | **PORTED & VERIFIED** |
| 5 | **Selective, In-Order Pipeline Execution** | `POST /api/v1/app/run-pipeline` with individual switches (`init`, `marketdata`, `indicators`, `percentile`, `score`, `ranking`). | Implemented in `compatibility_web.py:run_pipeline`, running enabled stages in dependency order, broadcasting real-time logs, and returning step results. | **PORTED & VERIFIED** |
| 6 | **Date-Cutoff Cleanup and Dependent Rebuild** | `DELETE /api/v1/app/cleanup` and `POST /api/v1/app/recalculate`. | `compatibility_web.py:cleanup` deletes bars after cutoff via `MarketRepository.delete_bars_after`, and `recalculate` queues strategy 1 & 2 day jobs. | **PORTED & VERIFIED** |
| 7 | **Continuously Updated Kite Holdings-Price Ticker** | Holdings ticker start/stop/prices in `investment_routes.py` & `kite_adaptor.py`. | `POST /api/v1/investment/prices/start`, `GET /api/v1/investment/prices`, and `POST /api/v1/investment/prices/stop` in `compatibility_web.py` tracking open lots and latest close changes. | **PORTED & VERIFIED** |
| 8 | **Integrated Legacy Dashboard Workflow** | Multi-tab dashboard (`templates/dashboard.html` + `dashboard.js`). | Mounted at `GET /dashboard` in `run.py`. Full backing endpoints (`/investment/...`, `/actions/...`, `/backtest/...`, `/config/...`) wired in `compatibility_web.py`. | **PORTED & VERIFIED** |
| 9 | **Live Orchestration Log Stream** | Continuous SSE stream at `/api/v1/app/logs/stream`. | Implemented with thread-safe `_LOG_QUEUES` broadcast and keepalive PINGs in `compatibility_web.py:logs_stream`. | **PORTED & VERIFIED** |
| 10 | **OpenAPI Specification & Interactive Swagger UI** | `flask-smorest` OpenAPI / Swagger UI. | `GET /api/v1/openapi.json` returns OpenAPI 3.0.3 specification, and `GET /api/v1/swagger-ui` serves an interactive Swagger UI. | **PORTED & VERIFIED** |
| 11 | **Delete Saved Backtest Run** | `DELETE /api/v1/backtest/history/<run_id>`. | `services.backtests.delete_run(run_id)` in `backtest_jobs.py` and `DELETE /api/v1/backtest/history/<run_id>` in `compatibility_web.py`. | **PORTED & VERIFIED** |
| 12 | **Convenience Ranking Lookup with Friday Normalization & Price** | Date normalized to prior Friday + price in `ranking_routes.py`. | `GET /api/v1/ranking/symbol/<symbol>?date=YYYY-MM-DD` normalizes any date to the preceding Friday and enriches with latest close price. | **PORTED & VERIFIED** |

---

### Verification
All compatibility endpoints and workflows are covered by automated unit and integration tests in [`tests/test_v1_compatibility.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/tests/test_v1_compatibility.py).
