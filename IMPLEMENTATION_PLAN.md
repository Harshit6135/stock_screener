# Configurable App Orchestration Endpoints

Add boolean toggle flags to the existing cleanup and pipeline endpoints, create a new "recalculate from date" endpoint, and add count validation to the percentile service.

## Proposed Changes

### Schema Layer

#### [MODIFY] [app_schema.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/schemas/app_schema.py)

Add boolean flags to `CleanupQuerySchema` and create two new schemas:

```python
class CleanupQuerySchema(Schema):
    """Schema for cleanup query parameters"""
    start_date = fields.Date(required=True, ...)
    marketdata = fields.Boolean(load_default=True, ...)
    indicators = fields.Boolean(load_default=True, ...)
    percentile = fields.Boolean(load_default=True, ...)
    score = fields.Boolean(load_default=True, ...)
    ranking = fields.Boolean(load_default=True, ...)

class PipelineQuerySchema(Schema):
    """Schema for pipeline run toggles"""
    init = fields.Boolean(load_default=True, ...)
    marketdata = fields.Boolean(load_default=True, ...)
    indicators = fields.Boolean(load_default=True, ...)
    percentile = fields.Boolean(load_default=True, ...)
    score = fields.Boolean(load_default=True, ...)
    ranking = fields.Boolean(load_default=True, ...)

class RecalculateQuerySchema(Schema):
    """Schema for recalculate-from-date"""
    start_date = fields.Date(required=True, ...)
    percentile = fields.Boolean(load_default=True, ...)
    score = fields.Boolean(load_default=True, ...)
    ranking = fields.Boolean(load_default=True, ...)
```

> [!NOTE]
> `RecalculateQuerySchema` only covers percentile/score/ranking because marketdata and indicators aren't "recalculated" — they're fetched from external sources.

---

### Schema Exports

#### [MODIFY] [__init__.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/schemas/__init__.py)

Export `PipelineQuerySchema` and `RecalculateQuerySchema`.

---

### Percentile Count Validation

#### [MODIFY] [percentile_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/percentile_service.py)

Add a `_validate_count` method and call it inside `generate_percentile` **before** proceeding with calculation:

```python
def _validate_count(self, indicators_count: int, date) -> None:
    """
    Compare indicator row count for the new date vs the last
    percentile date's row count. If diff > 5%, raise an error.
    """
    last_percentile_date = percentile_repo.get_max_percentile_date()
    if not last_percentile_date:
        return  # First run, no baseline to compare

    last_percentile_rows = percentile_repo.get_percentiles_by_date(
        last_percentile_date
    )
    last_count = len(last_percentile_rows)
    if last_count == 0:
        return

    diff_pct = abs(indicators_count - last_count) / last_count
    if diff_pct > 0.05:
        raise ValueError(
            f"Count validation failed for {date}: "
            f"indicators={indicators_count}, "
            f"last_percentile={last_count}, "
            f"diff={diff_pct:.1%} (threshold=5%)"
        )
```

**Injection point** in `generate_percentile` — after building `indicators_data_list` and before merging DataFrames:
```python
# After line: metrics_df = metrics_df.fillna(0).infer_objects(copy=False)
self._validate_count(len(metrics_df), date)
```

> [!IMPORTANT]
> This ensures that if indicators suddenly has significantly fewer/more stocks than the last percentile run (e.g. partial updates, missing data), the pipeline halts early instead of producing skewed percentiles.

---

### Route Layer

#### [MODIFY] [app_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/app_routes.py)

**1. `CleanupAfterDate.delete`** — Use the boolean flags from `args` to conditionally delete:
```python
if args.get('marketdata', True):
    deleted_counts['marketdata'] = marketdata_repo.delete_after_date(start_date)
# ... same pattern for indicators, percentile, score, ranking
```

**2. `RunPipeline.post`** — Accept `PipelineQuerySchema` as JSON body input and conditionally run each step:
```python
if args.get('init', True):
    # run init
if args.get('marketdata', True):
    # run marketdata
# ... etc.
```

**3. New `RecalculateFromDate` class** at `/api/v1/app/recalculate`:
- Accepts `RecalculateQuerySchema` as query params
- For each enabled table: delete data ≥ `start_date`, then regenerate
- Order: percentile → score → ranking (respecting the dependency chain)
- Uses existing `delete_after_date` + `backfill_percentiles` / `generate_composite_scores` / `generate_rankings`

---

## Verification Plan

### Manual Verification

Since there are no existing tests in this project, verification will be manual via Swagger UI:

1. **Start the app** and navigate to Swagger at `/swagger-ui`
2. **Cleanup endpoint**: Call `DELETE /api/v1/app/cleanup` with `start_date` and `marketdata=false` — verify only non-marketdata tables are affected
3. **Pipeline endpoint**: Call `POST /api/v1/app/run-pipeline` with `{"init": false, "marketdata": false}` — verify only indicators/percentile/score/ranking steps run
4. **Recalculate endpoint**: Call `POST /api/v1/app/recalculate?start_date=2025-01-01&score=false` — verify only percentile+ranking are recalculated
5. **All-defaults**: Call each endpoint with no boolean flags — should behave exactly like current behavior (all `true`)

> [!IMPORTANT]
> I'd recommend you test these against your actual running instance. Would you like to suggest a specific date range for testing, or shall I use a recent date?
