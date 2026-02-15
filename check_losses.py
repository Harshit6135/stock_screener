import sqlite3
import pandas as pd

def check_max_loss():
    conn = sqlite3.connect('instance/backtest.db')
    
    # Get all sells with their corresponding buys (approximate via FIFO or just symbol matching)
    # Since we don't link buy-sell explicitly in DB easily, let's look at sell execution price vs previous close or avg buy price
    # Actually, we can just look at the 'reason' or calculate % diff from previous close if available
    
    print("\n=== LARGE LOSS CHECK ===")
    sells = pd.read_sql("SELECT * FROM actions WHERE type='sell' AND status='Approved'", conn)
    
    # We don't have entry price in actions table directly for sells.
    # But we can assume the loss is roughly (entry - exit). 
    # Let's check if execution_price is suspiciously low compared to something?
    # Better: check the `sell_value` vs `capital` at that time?
    # Or just check if any sell has execution_price near 0.
    
    min_price = sells['execution_price'].min()
    print(f"Min Sell Price: {min_price}")
    
    # Check for largest drops
    # We can't easily calculate exact P&L per trade without linking buys/sells. 
    # But we can check if the daily drop in portfolio value exceeds expected bounds.
    
    summary = pd.read_sql("SELECT date, portfolio_value FROM investment_summary ORDER BY date", conn)
    summary['pct_change'] = summary['portfolio_value'].pct_change() * 100
    
    min_day_change = summary['pct_change'].min()
    print(f"Max Daily Portfolio Drop: {min_day_change:.2f}%")
    
    worst_days = summary.nsmallest(5, 'pct_change')
    print("Worst Days:")
    print(worst_days)

    conn.close()

if __name__ == "__main__":
    check_max_loss()
