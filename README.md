# Stocks Screener V3

A powerful, Python-based technical analysis tool designed to screen Nifty 500 stocks. This application automates the process of fetching market data, calculating complex technical indicators, and filtering stocks based on a multi-factor strategy to identify high-probability trading candidates.

## 🚀 Introduction

Stocks Screener V3 is built to help traders finding potential momentum and trend-following setups without manually scanning hundreds of charts. It leverages the `yfinance` API for market data and uses a local SQLite database for efficiency. The core philosophy uses a combination of Trend, Momentum, Volatility, and Volume analysis to grade and rank stocks.

## 🧠 Strategy & Technical Indicators

The screener applies a robust set of technical checks defined in `stock_screener/config.py`:

### 1. Trend Analysis
- **Primary Trend**: Checks if the price is above the **200-day Simple Moving Average (SMA)** ("The Sandbox Floor").
- **Intermediate Trend**: Analyzes the **50-day SMA** to gauge medium-term direction.

### 2. Momentum
- **RSI (Relative Strength Index)**: Looks for stocks with RSI > 48 (configurable), indicating bullish momentum but not necessarily overbought.
- **ROC (Rate of Change)**: Measures the velocity of price changes over a 10-day period.
- **Stochastic Oscillator**: Uses %K (14) and %D (3) to identify overbought (>80) and oversold (<20) conditions.

### 3. Volatility (The Squeeze)
- **Bollinger Bands**: Uses a 20-period SMA with 2 standard deviations.
- **Bandwidth**: Calculates the width of the bands to identify "Squeezes" (periods of low volatility often followed by explosive moves).
- **Consolidation**: Filters for stocks within a specific bandwidth threshold (e.g., 15-20%) over a lookback period (~6 months).

### 4. GPS (Trend Confirmation)
- **MACD (Moving Average Convergence Divergence)**: Standard 12/26/9 setting to confirm trend direction and momentum.

### 5. Volume
- **Volume Analysis**: Compares short-term (5-day) vs long-term (20-day) Volume EMAs to detect institutional accumulation or distribution.

## 📋 Pre-requisites

Ensure you have the following installed on your system:

- **Python 3.8+**
- **pip** (Python package installer)

### Required Libraries

Install the necessary Python dependencies:

```bash
pip install pandas yfinance requests
```

*(Note: `sqlite3` and `logging` are standard Python libraries and do not need installation.)*

## 🛠️ Implementation Overview

The project is structured for modularity and scalability:

- **`main.py`**: The entry point of the application.
- **`stock_screener/`**:
    - **`screener.py`**: Orchestrates the screening process.
    - **`classes/`**:
        - `nse_client.py`: Fetches the list of Nifty 500 tickers.
        - `yahoo_client.py`: Downloads historical market data using `yfinance`.
        - `analyzer.py`: Calculates proper technical indicators (RSI, Bollinger Bands, MACD, etc.).
        - `strategy.py`: Applies the filtering logic based on the calculated indicators.
        - `ranker.py`: Scores and ranks the "winning" stocks.
        - `db.py`: Manages the SQLite database (`stocks.db`) for caching data and storing results.
        - `report_generator.py`: Handles CSV export and console output.
    - **`config.py`**: Central configuration file for tweaking strategy parameters (SMA periods, RSI thresholds, etc.).

## 🏃‍♂️ How to Run

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone <repository_url>
    cd stocks_screener_v3
    ```

2.  **Run the Screener**:
    Execute the main script from the root directory:
    ```bash
    python main.py
    ```

3.  **View Results**:
    -   **Console**: The script will print the process, winners, and the top 5 ranked stocks.
    -   **CSV**: A full report of the winning stocks is saved to `results.csv`.
    -   **Database**: All calculated indicators are stored in `stock_screener/stocks.db` for further analysis.

## 📊 Feature Highlights

-   **Automated Nifty 500 fetching**: Always screens the current index constituents.
-   **Intelligent Caching**: Saves data to SQLite to avoid hitting API limits and valid redundant fetches.
-   **Customizable Strategy**: Easily tweak parameters in `config.py` to fit your trading style.
-   **Ranking System**: Doesn't just filter; checks for the *best* setups based on a momentum score.
-   **Ranking Logic**: Winners are ranked based on a composite score of RSI, ROC, and other momentum factors.

---

**Disclaimer**: *This tool is for educational and research purposes only. Do not use it as the sole basis for investment decisions.*
