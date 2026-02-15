import sqlite3
import pandas as pd

conn = sqlite3.connect('instance/backtest.db')

# Check actions around 2025-12-08 (Monday) and the week
print("=== Actions for week of 2025-12-08 ===")
actions = pd.read_sql("""
    SELECT action_date, type, status, symbol, units, prev_close, execution_price, capital, reason
    FROM actions 
    WHERE action_date BETWEEN '2025-12-05' AND '2025-12-12'
    ORDER BY action_date, type, status
""", conn)
print(actions.to_string())

# Check if there are any pending actions that week
print("\n=== Pending actions during that week ===")
pending = pd.read_sql("""
    SELECT action_date, type, status, symbol, units, capital
    FROM actions 
    WHERE status = 'Pending' AND action_date BETWEEN '2025-12-01' AND '2025-12-12'
    ORDER BY action_date
""", conn)
print(pending.to_string() if not pending.empty else "  No pending actions found")

# Check a broader pattern: weeks where daily sells happen
print("\n=== Daily (non-Monday) sells vs buys ===")
daily = pd.read_sql("""
    SELECT action_date, type, status, COUNT(*) as cnt, SUM(units * COALESCE(execution_price, 0)) as value
    FROM actions 
    WHERE action_date IN (
        SELECT DISTINCT action_date FROM actions 
        WHERE type='sell' AND status='Approved' AND reason LIKE '%stoploss%'
    )
    GROUP BY action_date, type, status
    ORDER BY action_date DESC
    LIMIT 40
""", conn)
print(daily.to_string())

# Check summary around that date
print("\n=== Summaries around 2025-12-08 ===")
summaries = pd.read_sql("""
    SELECT date, starting_capital, sold, bought, 
           (starting_capital + sold - bought) as remaining,
           portfolio_value, gain_percentage
    FROM investment_summary 
    WHERE date BETWEEN '2025-12-01' AND '2025-12-12'
    ORDER BY date
""", conn)
print(summaries.to_string())

conn.close()
