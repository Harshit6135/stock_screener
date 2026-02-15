"""Diagnostic: Why does the backtest show -58% returns?"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('instance/backtest.db')
out = []

def p(msg=""):
    out.append(str(msg))

p("=" * 80)
p("1. SUMMARY TABLE - Key columns")
p("=" * 80)
summary = pd.read_sql("""
    SELECT date, starting_capital, sold, bought, 
           (starting_capital + sold - bought) as remaining,
           portfolio_value, gain_percentage
    FROM investment_summary ORDER BY date
""", conn)
p(summary.to_string())

p("\n" + "=" * 80)
p("2. CAPITAL CHAIN: starting_capital vs previous remaining?")
p("=" * 80)
breaks = 0
for i in range(1, len(summary)):
    prev_remaining = summary.iloc[i-1]['remaining']
    curr_starting = summary.iloc[i]['starting_capital']
    diff = curr_starting - prev_remaining
    if abs(diff) > 0.02:
        p(f"  BREAK {summary.iloc[i]['date']}: prev_remain={prev_remaining:.2f} → start={curr_starting:.2f} gap={diff:.2f}")
        breaks += 1
if breaks == 0:
    p("  Chain is consistent ✓")
else:
    p(f"  Total breaks: {breaks}")

p("\n" + "=" * 80)
p("3. BOUGHT mismatch: summary.bought vs actual buy actions value")
p("=" * 80)
buys = pd.read_sql("""
    SELECT action_date as date, SUM(units * COALESCE(execution_price, 0)) as action_val
    FROM actions WHERE type='buy' AND status='Approved'
    GROUP BY action_date
""", conn)
merged = summary[['date', 'bought']].merge(buys, on='date', how='left').fillna(0)
merged['diff'] = merged['bought'] - merged['action_val']
bad = merged[abs(merged['diff']) > 1]
p(f"  Mismatches: {len(bad)} out of {len(merged)}")
if not bad.empty:
    p(bad.to_string())

p("\n" + "=" * 80)
p("4. SOLD mismatch: summary.sold vs actual sell actions value")
p("=" * 80)
sells = pd.read_sql("""
    SELECT action_date as date, SUM(units * COALESCE(execution_price, 0)) as action_val
    FROM actions WHERE type='sell' AND status='Approved'
    GROUP BY action_date
""", conn)
merged_s = summary[['date', 'sold']].merge(sells, on='date', how='left').fillna(0)
merged_s['diff'] = merged_s['sold'] - merged_s['action_val']
bad_s = merged_s[abs(merged_s['diff']) > 1]
p(f"  Mismatches: {len(bad_s)} out of {len(merged_s)}")
if not bad_s.empty:
    p(bad_s.to_string())

p("\n" + "=" * 80)
p("5. PORTFOLIO VALUE reconciliation")
p("=" * 80)
issues = []
for _, row in summary.iterrows():
    d = row['date']
    h = pd.read_sql(f"SELECT units, current_price FROM investment_holdings WHERE date='{d}'", conn)
    if h.empty:
        continue
    hv = (h['units'] * h['current_price']).sum()
    rem = row['remaining']
    expected = hv + rem
    actual = row['portfolio_value']
    diff = actual - expected
    if abs(diff) > 1:
        issues.append(f"  {d}: holdings={hv:.2f} + remaining={rem:.2f} = {expected:.2f}, actual={actual:.2f}, diff={diff:.2f}")
p(f"  Issues: {len(issues)}")
for iss in issues[:10]:
    p(iss)

p("\n" + "=" * 80)
p("6. SL SELLS breakdown")
p("=" * 80)
sl_data = pd.read_sql("""
    SELECT action_date, symbol, units, execution_price, reason
    FROM actions WHERE type='sell' AND status='Approved' AND reason LIKE '%stoploss%'
    ORDER BY action_date
""", conn)
p(f"  Total SL sells: {len(sl_data)}")
if not sl_data.empty:
    sl_data['weekday'] = pd.to_datetime(sl_data['action_date']).dt.day_name()
    p(f"  By day of week:")
    p(sl_data['weekday'].value_counts().to_string())

p("\n" + "=" * 80)
p("7. MULTIPLE SUMMARIES per week?")
p("=" * 80)
all_dates = pd.read_sql("SELECT date FROM investment_summary ORDER BY date", conn)
all_dates['date'] = pd.to_datetime(all_dates['date'])
all_dates['week'] = all_dates['date'].dt.strftime('%Y-W%W')
wc = all_dates.groupby('week').size()
multi = wc[wc > 1]
p(f"  Weeks with >1 summary record: {len(multi)}")
if not multi.empty:
    p(multi.head(20).to_string())

p("\n" + "=" * 80)
p("8. FIRST / LAST records")
p("=" * 80)
p(f"  Date range: {summary.iloc[0]['date']} to {summary.iloc[-1]['date']}")
p(f"  Total summary records: {len(summary)}")
p(f"  First PV: {summary.iloc[0]['portfolio_value']}")
p(f"  Last PV: {summary.iloc[-1]['portfolio_value']}")
total_buys = pd.read_sql("SELECT COUNT(*) as c FROM actions WHERE type='buy' AND status='Approved'", conn).iloc[0]['c']
total_sells = pd.read_sql("SELECT COUNT(*) as c FROM actions WHERE type='sell' AND status='Approved'", conn).iloc[0]['c']
p(f"  Total approved buys: {total_buys}")
p(f"  Total approved sells: {total_sells}")

conn.close()

with open('diagnose_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print("Output written to diagnose_output.txt")
