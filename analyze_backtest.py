import sqlite3
import pandas as pd

def analyze_backtest():
    conn = sqlite3.connect('instance/backtest.db')
    
    with open('analysis_results.txt', 'w') as f:
        # 1. Summary Metrics
        f.write("\n=== EQUITY CURVE (Monthly) ===\n")
        summary = pd.read_sql("SELECT date, portfolio_value, remaining_capital, portfolio_risk FROM investment_summary ORDER BY date", conn)
        summary['date'] = pd.to_datetime(summary['date'])
        try:
            monthly = summary.resample('ME', on='date').last()
        except TypeError:
            monthly = summary.resample('M', on='date').last()
            
        f.write(monthly[['portfolio_value', 'remaining_capital']].to_string() + "\n")
        
        initial_cap = summary.iloc[0]['portfolio_value'] if not summary.empty else 100000
        final_cap = summary.iloc[-1]['portfolio_value'] if not summary.empty else 0
        drawdown = (final_cap - initial_cap) / initial_cap * 100
        f.write(f"\nInitial: {initial_cap:,.2f} | Final: {final_cap:,.2f} | Return: {drawdown:.2f}%\n")

        # 2. Trade Analysis
        f.write("\n=== TRADE PERFORMANCE ===\n")
        actions = pd.read_sql("SELECT * FROM actions WHERE status='Approved' ORDER BY action_date", conn)
        
        sells = actions[actions['type'] == 'sell'].copy()
        buys = actions[actions['type'] == 'buy'].copy()
        
        f.write(f"Total Buys: {len(buys)}\n")
        f.write(f"Total Sells: {len(sells)}\n")
        
        total_sell_value = (sells['units'] * sells['execution_price']).sum()
        total_buy_value = (buys['units'] * buys['execution_price']).sum()
        f.write(f"Total Buy Value: {total_buy_value:,.2f}\n")
        f.write(f"Total Sell Value: {total_sell_value:,.2f}\n")
        f.write(f"Net Cash Flow: {total_sell_value - total_buy_value:,.2f}\n")

        # 3. Transaction Costs
        buy_costs = buys['buy_cost'].sum() if 'buy_cost' in buys.columns else 0
        sell_costs = sells['sell_cost'].sum() if 'sell_cost' in sells.columns else 0
        f.write(f"Total Transaction Costs: {buy_costs + sell_costs:,.2f}\n")

        # 4. Stop Loss Analysis
        if not sells.empty:
            sl_sells = sells[sells['reason'].str.contains('stop', case=False, na=False)]
            f.write(f"Stop-Loss Sells: {len(sl_sells)} ({len(sl_sells)/len(sells)*100:.1f}% of sells)\n")
            
            if not sl_sells.empty:
                f.write("Sample SL Sells:\n")
                f.write(sl_sells[['action_date', 'symbol', 'execution_price', 'reason']].head().to_string() + "\n")

        # 5. Sanity Checks
        neg_cap = summary[summary['remaining_capital'] < 0]
        if not neg_cap.empty:
            f.write("\n[WARNING] NEGATIVE CAPITAL FOUND:\n")
            f.write(neg_cap.head().to_string() + "\n")
        else:
            f.write("\n[OK] Capital remained positive.\n")

    conn.close()

if __name__ == "__main__":
    analyze_backtest()
