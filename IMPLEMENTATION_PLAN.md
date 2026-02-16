# Capital Events — Track Infusions / Withdrawals

When `initial_capital` in config is increased, every calculation that does `initial_capital - total_bought + total_sold` produces wrong cash balances because it assumes the capital was always that amount. This plan introduces a **capital_events** table so each infusion/withdrawal is a dated, auditable record.

## Proposed Changes

### Investment Model Layer

#### [MODIFY] [investments_model.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/investments_model.py)

Add a new `CapitalEventModel` class alongside the existing holdings/summary models:

```python
class CapitalEventModel(db.Model):
    __tablename__ = 'capital_events'
    __bind_key__ = 'personal'

    id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    event_type = db.Column(db.String(20), nullable=False)   # 'initial' | 'infusion' | 'withdrawal'
    note = db.Column(db.String(200), nullable=True)
```

#### [MODIFY] [models/\_\_init\_\_.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/__init__.py)

Export `CapitalEventModel`.

---

### Repository Layer

#### [MODIFY] [investment_repository.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/repositories/investment_repository.py)

Add CRUD for capital events:

| Method | Purpose |
|--------|---------|
| `get_all_capital_events()` | All events ordered by date asc |
| `get_total_capital(target_date)` | Sum of amounts where `date <= target_date` |
| `insert_capital_event(event_dict)` | Insert one event |
| `delete_all_capital_events()` | Cleanup helper |

#### [MODIFY] [repositories/\_\_init\_\_.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/repositories/__init__.py)

No change needed — `InvestmentRepository` is already exported.

---

### Service Layer

#### [MODIFY] [investment_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/investment_service.py)

Replace every `initial_capital = float(config_data.initial_capital)` with a call to the repo:

| Method | Old | New |
|--------|-----|-----|
| `get_portfolio_summary` (L48) | `config.initial_capital` | `self.inv_repo.get_total_capital(summary_date)` |
| `_calculate_xirr` | Only buy/sell cashflows | Also inject each capital event as negative cashflow at its date |
| `recalculate_summary` (L277/291) | `initial_capital` from config | `get_total_capital(first_date)` for seed; each week uses cumulative capital up to that week |

Add new method:
- `add_capital_event(date, amount, event_type, note)` — validates and delegates to repo.

#### [MODIFY] [actions_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/actions_service.py)

| Location | Old | New |
|----------|-----|-----|
| `generate_actions` L286 | `self.config.initial_capital` | `self.investment_repo.get_total_capital(action_date)` |
| `get_summary` L600 | `self.config.initial_capital` | `self.investment_repo.get_total_capital(action_date)` |

---

### API Layer

#### [MODIFY] [investment_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/investment_routes.py)

Add two new endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/investment/capital-events` | `GET` | List all capital events |
| `/api/v1/investment/capital-events` | `POST` | Record a new infusion/withdrawal |

Schema:
```python
class CapitalEventSchema(ma.Schema):
    date   = ma.fields.Date(required=True)
    amount = ma.fields.Float(required=True)
    event_type = ma.fields.String(required=True)  # 'infusion' | 'withdrawal'
    note   = ma.fields.String(load_default="")
```

---

### Database Migration

After deploying, the user must **seed the initial capital event** once:

```
POST /api/v1/investment/capital-events
{ "date": "2025-XX-XX", "amount": 100000, "event_type": "initial", "note": "Starting capital" }
```

> [!IMPORTANT]
> The existing `initial_capital` field in config remains as a fallback / default seed value. If the `capital_events` table is empty, the system will auto-seed it with `config.initial_capital` at the earliest summary date to ensure backward compatibility.

---

## Verification Plan

### Manual Verification

1. Start the app → new `capital_events` table should be created automatically by SQLAlchemy
2. `POST /api/v1/investment/capital-events` with an initial event → confirm 201
3. `GET /api/v1/investment/capital-events` → confirm the event is returned
4. Hit `/api/v1/investment/summary` → confirm `remaining_capital` and gains use the capital events total rather than the config value
5. Add a second infusion event → confirm summary recalculates with new total
6. Hit `/api/v1/investment/summary/recalculate` → confirm all historical summaries now use correct weekly capital
