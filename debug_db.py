import sqlite3
import json

conn = sqlite3.connect('instance/backtest.db')
cursor = conn.cursor()

output = []

# Summary table - most important for a year review
output.append("===== INVESTMENT_SUMMARY (ALL WEEKS) =====")
schema = cursor.execute("PRAGMA table_info(investment_summary)").fetchall()
col_names = [s[1] for s in schema]
output.append(f"Columns: {col_names}")
rows = cursor.execute("SELECT * FROM investment_summary ORDER BY date").fetchall()
for row in rows:
    d = dict(zip(col_names, row))
    output.append(json.dumps(d))

# Actions summary - count by type per week
output.append("\n\n===== ACTIONS SUMMARY BY WEEK =====")
rows = cursor.execute("""
    SELECT action_date, type, COUNT(*) as cnt, 
           SUM(units * COALESCE(execution_price, 0)) as total_value
    FROM actions 
    WHERE status = 'Approved'
    GROUP BY action_date, type 
    ORDER BY action_date, type
""").fetchall()
for row in rows:
    output.append(f"  {row[0]} | {row[1]:4s} | count={row[2]:2d} | value={row[3]:>12.2f}")

# Holdings snapshot - just the last week
output.append("\n\n===== LATEST HOLDINGS =====")
schema = cursor.execute("PRAGMA table_info(investment_holdings)").fetchall()
col_names = [s[1] for s in schema]
last_date = cursor.execute("SELECT MAX(date) FROM investment_holdings").fetchone()[0]
output.append(f"Latest date: {last_date}")
rows = cursor.execute("SELECT * FROM investment_holdings WHERE date = ? ORDER BY symbol", (last_date,)).fetchall()
for row in rows:
    d = dict(zip(col_names, row))
    output.append(json.dumps(d, indent=2))

# Key stats
output.append("\n\n===== KEY STATS =====")
first_summary = cursor.execute("SELECT * FROM investment_summary ORDER BY date LIMIT 1").fetchone()
last_summary = cursor.execute("SELECT * FROM investment_summary ORDER BY date DESC LIMIT 1").fetchone()
first_cols = [s[1] for s in cursor.execute("PRAGMA table_info(investment_summary)").fetchall()]
first_d = dict(zip(first_cols, first_summary))
last_d = dict(zip(first_cols, last_summary))
output.append(f"Start date: {first_d['date']}, End date: {last_d['date']}")
output.append(f"Initial capital: {first_d['starting_capital']}")
output.append(f"Final portfolio value: {last_d['portfolio_value']}")
output.append(f"Final gain: {last_d['gain']} ({last_d['gain_percentage']}%)")

# Count total actions
total_buys = cursor.execute("SELECT COUNT(*) FROM actions WHERE type='buy' AND status='Approved'").fetchone()[0]
total_sells = cursor.execute("SELECT COUNT(*) FROM actions WHERE type='sell' AND status='Approved'").fetchone()[0]
output.append(f"Total buys: {total_buys}, Total sells: {total_sells}")

# Stop loss sells
sl_sells = cursor.execute("SELECT COUNT(*) FROM actions WHERE type='sell' AND reason LIKE '%stoploss%'").fetchone()[0]
output.append(f"Stop-loss sells: {sl_sells}")

# Check for any negative prices or suspicious data
neg_prices = cursor.execute("SELECT COUNT(*) FROM investment_holdings WHERE current_price <= 0").fetchone()[0]
output.append(f"Holdings with negative/zero prices: {neg_prices}")

# Check for holdings where current_price < current_sl (should have been stopped out)
breached = cursor.execute("""
    SELECT symbol, date, current_price, current_sl, entry_price 
    FROM investment_holdings 
    WHERE current_price < current_sl
    ORDER BY date
""").fetchall()
output.append(f"\nHoldings where current_price < current_sl (potential missed stop-losses): {len(breached)}")
for b in breached[:20]:  # Show first 20
    output.append(f"  {b[1]} | {b[0]:12s} | price={b[2]:>8.2f} | SL={b[3]:>8.2f} | entry={b[4]:>8.2f}")

conn.close()

with open('debug_db_output.txt', 'w') as f:
    f.write('\n'.join(output))
print("Done - output in debug_db_output.txt")
