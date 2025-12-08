# Stocks Screener V3

A powerful, Python-based technical analysis tool designed to screen Nifty 500 stocks. This application automates the process of fetching market data, calculating complex technical indicators, and filtering stocks based on a multi-factor strategy to identify high-probability trading candidates.

## 🚀 Introduction

Stocks Screener V3 is built to help traders find potential momentum and trend-following setups without manually scanning hundreds of charts. It leverages the **Zerodha Kite Connect API** for market data and uses a local SQLite database for efficiency. The core philosophy uses a combination of Trend, Momentum, Volatility, and Volume analysis to grade and rank stocks.

## 📂 Project Structure

The project follows a modular Service-Oriented Architecture (SOA):

- **`services/`**: Core business logic and services.
    - `screener_service.py`: Main orchestration service.
    - `kite_service.py`: Handles Kite Connect authentication and session.
    - `market_data_service.py`: Manages data fetching and caching.
    - `analysis_service.py`: Computes technical indicators (RSI, MACD, etc.).
    - `strategy_service.py`: Applies filtration rules.
    - `reporting_service.py`: Generates reports and charts.
    - `ranking_service.py`: Ranks the best picks.
    - `position_sizing_service.py`: Calculates risk and position sizes.
- **`config/`**: Configuration files.
    - `app_config.py`: Central strategy parameters.
- **`database/`**: Database interaction.
    - `sqlite_manager.py`: SQLite handler.
- **`utils/`**: Shared utilities.
    - `logger.py`: Application logging.
- **`data/`**: Data storage.
    - `stocks.db`: SQLite database.
    - `working_instruments.csv`: List of instruments to scan.
    - `position_input.txt` / `charts_input.txt`: Input files for scripts.
- **`scripts/`**: Standalone tools.
    - `generate_charts.py`: Generate health card charts for specific tickers.
    - `calculate_position_size.py`: Calculate position sizes for tickers.

## 📋 Pre-requisites

1.  **Python 3.13+**
2.  **Kite Connect API Key & Secret** (from [Zerodha Developers](https://kite.trade/))

### Dependencies

Install the required packages:

```bash
pip install pandas requests kiteconnect matplotlib openpyxl
```

## 🔐 Setup & Configuration

**CRITICAL STEP**: Security configuration.

1.  Create a file named `local_secrets.py` in the **root directory** of the project.
2.  Add your Kite Connect API credentials to this file:

    ```python
    # local_secrets.py
    KITE_API_KEY = "your_api_key_here"
    KITE_API_SECRET = "your_api_secret_here"
    ```

    *Note: `local_secrets.py` is ignored by git to keep your credentials safe.*

3.  (Optional) Adjust strategy parameters in `config/app_config.py`.

## 🏃‍♂️ How to Run

### 1. Run the Main Screener
This will fetch data, analyze stocks, and print winners to the console.

```bash
python main.py
```

Results are saved to `results/results.csv`.

### 2. Generate Charts
To generate technical "Health Card" charts for specific stocks:
1.  Add stock symbols (e.g., `RELIANCE`, `TCS`) to `data/charts_input.txt`.
2.  Run the script:

    ```bash
    python scripts/generate_charts.py
    ```

### 3. Calculate Position Sizes
To calculate risk-managed position sizes:
1.  Add stock symbols to `data/position_input.txt`.
2.  Run the script:

    ```bash
    python scripts/calculate_position_size.py
    ```

## 📊 Strategy Highlights

-   **Trend**: 50 SMA > 200 SMA.
-   **Momentum**: RSI > 48, Positive ROC, Rising Stochastic.
-   **Volatility**: Bollinger Band Squeezes (Bandwidth < 15-20%).
-   **Confirmation**: MACD Bullish Crossover.
-   **Volume**: Rising Volume Trend (Short EMA > Long EMA).

---

**Disclaimer**: *This tool is for educational and research purposes only. Do not use it as the sole basis for investment decisions.*
