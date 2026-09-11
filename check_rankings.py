import sqlite3
conn = sqlite3.connect('instance/market_data.db')
cur = conn.cursor()
cur.execute("SELECT strategy_id, MIN(ranking_date), MAX(ranking_date), COUNT(*) FROM ranking GROUP BY strategy_id")
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
