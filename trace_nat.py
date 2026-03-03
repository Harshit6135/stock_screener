import json
import sys
import logging

data = json.load(open('backtest_history/20260228_185450_45/trades.json'))

for count, t_item in enumerate(data):
    if t_item.get('symbol') == 'NATIONALUM':
        print(f"{t_item.get('entry_date', t_item.get('date', t_item.get('action_date')))} - {t_item.get('exit_date', 'OPEN')} - {t_item.get('type')}: {t_item.get('units')} units @ {t_item.get('price', t_item.get('exit_price'))} - Reason: {t_item.get('reason', '')}")

