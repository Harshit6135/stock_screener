import pandas as pd
import matplotlib.pyplot as plt
import os

class ChartGenerator:
    def __init__(self, market_data):
        self.market_data = market_data

    def generate_chart(self, ticker):
        df = self.market_data[ticker]
        
        fig, axes = plt.subplots(3, 1, figsize=(15, 10), gridspec_kw={'height_ratios': [3, 1, 1]})
        fig.suptitle(f'{ticker} - Health Card', fontsize=16)

        # Price and EMAs
        axes[0].plot(df.index, df['Close'], label='Close')
        axes[0].plot(df.index, df['Short_MA'], label='50-Day EMA', linestyle='--')
        axes[0].plot(df.index, df['Long_MA'], label='200-Day EMA', linestyle='--')
        axes[0].set_title('Price Action & Trend')
        axes[0].legend()

        # RSI
        axes[1].plot(df.index, df['RSI'], label='RSI')
        axes[1].plot(df.index, df['RSI_Signal'], label='RSI Signal', linestyle='--')
        axes[1].axhline(y=55, color='r', linestyle='--', label='RSI Threshold (55)')
        axes[1].set_title('Momentum (RSI)')
        axes[1].legend()

        # MACD
        axes[2].plot(df.index, df['MACD'], label='MACD')
        axes[2].plot(df.index, df['Signal_Line'], label='Signal Line', linestyle='--')
        axes[2].set_title('Trend Confirmation (MACD)')
        axes[2].legend()

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        # Create charts directory if it doesn't exist
        if not os.path.exists('charts'):
            os.makedirs('charts')
            
        plt.savefig(f'charts/{ticker}_chart.png')
        plt.close()
        print(f"Chart saved for {ticker}")

class ReportingService:
    def __init__(self, results):
        self.results = results
        self.df = pd.DataFrame(results)

    def generate_summary(self):
        print("\nSCAN SUMMARY:")
        print(self.df['Status'].value_counts())
        print(self.df['setup_type'].value_counts())
        
        # Calculate and print additional stats
        if not self.df.empty:
            trend_ok_count = self.df['Trend_OK'].sum() if 'Trend_OK' in self.df.columns else 0
            rsi_ok_count = self.df['RSI_OK'].sum() if 'RSI_OK' in self.df.columns else 0
            squeeze_ok_count = self.df['Squeeze_OK'].sum() if 'Squeeze_OK' in self.df.columns else 0
            macd_ok_count = self.df['MACD_OK'].sum() if 'MACD_OK' in self.df.columns else 0
            vol_rising_count = self.df['vol_rising'].sum() if 'vol_rising' in self.df.columns else 0
            
            print(f"\nTrend OK: {trend_ok_count}")
            print(f"RSI OK: {rsi_ok_count}")
            print(f"Squeeze OK: {squeeze_ok_count}")
            print(f"MACD OK: {macd_ok_count}")
            print(f"Volume Rising: {vol_rising_count}")
        
        print("------------------------------")

    def get_winners(self):
        winners = self.df[self.df['Status'] == "MATCH"]
        print(f"Found {len(winners)} Matches:")
        return winners

    def display_winners(self, winners):
        if not winners.empty:
            print(winners[[
                'Symbol', 'Status', 'setup_type', 'Summary', 'Price', 'Trend_OK', 'RSI', 'RSI_OK',
                'Bandwidth', 'Squeeze_OK', 'MACD', 'MACD_OK', 'Volume', 'vol_rising'
            ]])

    def display_all_results(self):
        print("\nAll Results (First 10):")
        print(self.df.head(10)[[
            'Symbol', 'Status', 'setup_type', 'Summary', 'Price', 'Trend_OK', 'RSI', 'RSI_OK',
            'Bandwidth', 'Squeeze_OK', 'MACD', 'MACD_OK', 'Volume', 'vol_rising'
        ]])
    
    def save_to_csv(self, winners):
        if not winners.empty:
            # Create results directory if it doesn't exist
            if not os.path.exists('results'):
                os.makedirs('results')
                
            winners.to_csv('results/results.csv', index=False)
            print("\nResults saved to results/results.csv")
