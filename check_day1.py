import sqlite3

conn = sqlite3.connect('instance/backtest.db')
c = conn.cursor()

# Check first Monday's buy actions  
c.execute("""
    SELECT action_date, symbol, units, prev_close, execution_price, capital 
    FROM actions WHERE type='buy' AND status='Approved' AND action_date='2021-01-04'
""")
rows = c.fetchall()
print("=== Day 1 Buy Actions ===")
print(f"{'date':<12} {'symbol':<12} {'units':>6} {'prev_close':>12} {'exec_price':>12} {'capital':>12}")
total_at_exec = 0
total_at_prev = 0
for r in rows:
    print(f"{r[0]:<12} {r[1]:<12} {r[2]:>6} {r[3]:>12.2f} {r[4]:>12.2f} {r[5]:>12.2f}")
    total_at_exec += r[2] * r[4]  # units * execution_price
    total_at_prev += r[2] * r[3]  # units * prev_close
print(f"\nTotal units*exec_price = {total_at_exec:.2f}")
print(f"Total units*prev_close = {total_at_prev:.2f}")
print(f"Total capital column   = {sum(r[5] for r in rows):.2f}")

# Check holdings for same day
c.execute("""
    SELECT symbol, units, entry_price, entry_date, current_price, date
    FROM investment_holdings WHERE entry_date='2021-01-04'
    ORDER BY date LIMIT 20
""")
print("\n=== Day 1 Holdings ===")
holdings = c.fetchall()
total_holding_bought = 0
for h in holdings:
    print(f"  {h[0]:<12} units={h[1]:>5} entry_price={h[2]:>10.2f} entry_date={h[3]} current={h[4]:>10.2f} date={h[5]}")
    if h[3] == h[5]:  # entry_date == date
        total_holding_bought += h[1] * h[2]
print(f"\nTotal bought (entry_date==date): {total_holding_bought:.2f}")

conn.close()
