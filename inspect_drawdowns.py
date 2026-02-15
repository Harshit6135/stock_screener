import sqlite3
import pandas as pd

def inspect_drawdowns():
    conn = sqlite3.connect('instance/backtest.db')
    
    # Impact days from previous analysis
    impact_days = ['2025-03-25', '2025-01-28', '2025-10-21']
    
    for day in impact_days:
        print(f"\n=== ACTIONS ON {day} ===")
        actions = pd.read_sql(f"SELECT * FROM actions WHERE action_date='{day}'", conn)
        if not actions.empty:
            print(actions[['symbol', 'type', 'execution_price', 'units', 'reason']].to_string())
        else:
            print("No actions found (valuation drop only?)")
            
        print(f"--- HOLDINGS ON {day} ---")
        holdings = pd.read_sql(f"SELECT * FROM investment_holdings WHERE date='{day}'", conn)
        if not holdings.empty:
             print(holdings[['symbol', 'current_price', 'current_sl']].to_string())

    conn.close()

if __name__ == "__main__":
    inspect_drawdowns()
