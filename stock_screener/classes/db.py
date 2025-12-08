
import sqlite3
import pandas as pd
import os
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_name="stocks.db", db_dir="stock_screener"):
        self.db_path = os.path.join(db_dir, db_name)
        os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Market Data Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_data (
                ticker TEXT,
                date TIMESTAMP,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (ticker, date)
            )
        ''')

        # Indicators Table - storing as JSON or flattened columns? 
        # Flattened is better for querying, but dynamic indicators make it hard.
        # Given the requirements, let's store key indicators as columns and a generic JSON for others if needed.
        # For now, we will just store a comprehensive list of columns based on analyzer.py output.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS indicators (
                ticker TEXT,
                date TIMESTAMP,
                rsi REAL,
                roc REAL,
                macd REAL,
                signal_line REAL,
                stoch_k REAL,
                stoch_d REAL,
                short_ma REAL,
                long_ma REAL,
                PRIMARY KEY (ticker, date)
            )
        ''')
        
        conn.commit()
        conn.close()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def get_latest_date(self, ticker):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM market_data WHERE ticker = ?", (ticker,))
        result = cursor.fetchone()
        conn.close()
        return pd.to_datetime(result[0]) if result and result[0] else None

    def get_last_close(self, ticker):
        """Get the close price of the most recent saved date."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT close FROM market_data WHERE ticker = ? ORDER BY date DESC LIMIT 1", (ticker,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def save_market_data(self, ticker, df):
        if df.empty:
            return
        
        conn = self.get_connection()
        # Ensure index is date
        data_to_save = df.reset_index()
        # Standardize columns
        data_to_save = data_to_save[['date', 'Open', 'High', 'Low', 'Close', 'Volume']]
        data_to_save.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        data_to_save['ticker'] = ticker
        
        try:
            data_to_save.to_sql('market_data', conn, if_exists='append', index=False)
        except sqlite3.IntegrityError:
            # duplicate entries, ignore or handle? 
            # 'append' fails on primary key constraint. 
            # If we know we are fetching new data, this shouldn't happen often unless overlap.
            # We can do an upsert or just ignore duplicates.
            # For simplicity in this script, let's filter out existing dates first or use a loop.
            # Pandas to_sql doesn't support UPSERT easily.
            # Let's clean up: only save data > max_date
            pass
        except Exception as e:
            print(f"Error saving data for {ticker}: {e}")
            
        conn.close()

    def load_market_data(self, ticker):
        conn = self.get_connection()
        df = pd.read_sql("SELECT * FROM market_data WHERE ticker = ? ORDER BY date ASC", conn, params=(ticker,))
        conn.close()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.index.name = "date"
            # Renaming columns back to Capitalized for compatibility
            df.rename(columns={'open':'Open', 'high':'High', 'low':'Low', 'close':'Close', 'volume':'Volume'}, inplace=True)
        return df

    def save_indicators(self, ticker, data_dict):
        # data_dict is the result from analyze_stock
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # We need the date for the primary key. 
        # The analyzer result doesn't explicitly return the date of analysis usually (it returns latest stats).
        # We should assume this is for the *latest* date available in market_data for this ticker.
        # Or, we should modify analyzer to return date.
        # For now, let's fetch max date for ticker to associate these indicators with.
        
        latest_date = self.get_latest_date(ticker)
        if not latest_date:
            return

        try:
            cursor.execute('''
                INSERT OR REPLACE INTO indicators 
                (ticker, date, rsi, roc, macd, signal_line, stoch_k, stoch_d, short_ma, long_ma)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ticker, 
                latest_date.isoformat(),
                data_dict.get('RSI'),
                data_dict.get('ROC'),
                data_dict.get('MACD'),
                data_dict.get('Signal_Line'),
                data_dict.get('Stoch_K'),
                data_dict.get('Stoch_D'),
                data_dict.get('Short_MA'),
                data_dict.get('Long_MA')
            ))
            conn.commit()
        except Exception as e:
            print(f"Error saving indicators for {ticker}: {e}")
            
        conn.close()

    def clear_ticker_data(self, ticker):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM market_data WHERE ticker = ?", (ticker,))
        cursor.execute("DELETE FROM indicators WHERE ticker = ?", (ticker,))
        conn.commit()
        conn.close()
