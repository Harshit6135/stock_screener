# Day 0 Setup Guide

The Day 0 process initializes your stock universe by loading instrument data from NSE and BSE.

---

## Data Sources

### NSE (National Stock Exchange)

**URL:** https://www.nseindia.com/static/market-data/securities-available-for-trading

1. Navigate to the page
2. Download **EQUITY_L.csv** (list of all equity securities)
3. Save to `data/` folder

### BSE (Bombay Stock Exchange)

**URL:** https://www.bseindia.com/corporates/List_Scrips.html

1. Navigate to the page
2. Select **Segment = T** (Trading segment)
3. Click "Submit" and download CSV
4. Save to `data/` folder

---

## Day 0 Process

### Step 1: Place CSV Files

```
data/
├── EQUITY_L.csv          # NSE securities
├── bse_equity_t.csv      # BSE securities (Segment T)
```

### Step 2: Run Day 0 Endpoint

```bash
curl http://localhost:5000/day0
```

This will:
1. Read NSE and BSE CSV files
2. Merge and deduplicate by ISIN
3. Fetch additional data from yfinance (market cap, previous close)
4. Filter stocks (price > ₹75, mcap > ₹500 crore)
5. Enrich with Kite instrument tokens
6. Save to `instruments` and `master` tables

### Step 3: Verify

```bash
# Check instruments loaded
curl http://localhost:5000/instruments

# Should return list of ~1700 stocks
```

---

## Filtering Rules

| Rule | Threshold | Reason |
|------|-----------|--------|
| Price | > ₹75 | Avoid penny stocks |
| Market Cap | > ₹500 Cr | Liquidity filter |
| Asset Class | != "Mutual Fund" | Focus on equities |
| Issuer | != "Asset Management" | Exclude ETFs |

---

## Refresh Schedule

| Task | Frequency | Endpoint |
|------|-----------|----------|
| Day 0 (instruments) | Monthly | `/day0` |
| Price data | Daily | `/home` |
| Indicators | Daily | `/update_indicators` |
| Rankings | Daily | `/latest_rank` |

---

## Common Issues

### "No instruments found"
- Ensure CSV files are in `data/` folder
- Check CSV column names match expected format

### "Kite token missing"
- Run Kite authentication first
- Check `access_token.txt` exists

### "yfinance timeout"
- Network issue, retry after some time
- Process continues with available data
