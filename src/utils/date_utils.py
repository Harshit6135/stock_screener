import os
import csv
from typing import List, Set
from datetime import date, timedelta

# Load holidays from CSV
def _load_holidays() -> Set[date]:
    holidays = set()
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    csv_path = os.path.join(project_root, 'nse_bse_holidays_kite_2015_onwards.csv')
    
    if os.path.exists(csv_path):
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    d = date.fromisoformat(row['Date'])
                    holidays.add(d)
                except (ValueError, KeyError):
                    continue
    return holidays

NSE_HOLIDAYS = _load_holidays()

def reload_holidays():
    """O-9: Reload NSE_HOLIDAYS from CSV without restarting the app."""
    global NSE_HOLIDAYS
    NSE_HOLIDAYS = _load_holidays()

def is_holiday(d: date) -> bool:
    """Check if a date is a weekend or an NSE/BSE holiday."""
    if d.weekday() >= 5:  # Saturday or Sunday
        return True
    return d in NSE_HOLIDAYS

def get_friday_of_week(d: date) -> date:
    """
    Get the Friday of the week containing date d (Friday = weekday 4).
    If d is Sat/Sun, returns the previous Friday.
    """
    weekday = d.weekday()
    if weekday > 4:  # Saturday (5) or Sunday (6)
        days_to_subtract = weekday - 4
        return d - timedelta(days=days_to_subtract)
    else:
        days_to_add = 4 - weekday
        return d + timedelta(days=days_to_add)

def get_prev_friday(d: date) -> date:
    """
    Get the previous Friday for data lookups.

    Rankings and indicators are stored on Fridays. This
    resolves any date to its data-lookup Friday:
      - Friday → same day
      - Mon-Thu → previous week's Friday
      - Sat/Sun → same week's Friday

    Parameters:
        d (date): Any calendar date

    Returns:
        date: The resolved Friday
    """
    weekday = d.weekday()  # Monday=0, Friday=4
    if weekday == 4:  # Friday
        return d
    elif weekday < 4:  # Mon-Thu: go back to last Friday
        days_back = weekday + 3  # Mon=3, Tue=4, Wed=5, Thu=6
        return d - timedelta(days=days_back)
    else:  # Sat=5, Sun=6: go back to Friday
        days_back = weekday - 4  # Sat=1, Sun=2
        return d - timedelta(days=days_back)


def get_business_days(start_date: date, end_date: date) -> List[date]:
    """
    Get all trading days (Mon-Fri, excluding NSE/BSE holidays) between
    start and end dates inclusive.
    """
    days = []
    current = start_date
    while current <= end_date:
        if not is_holiday(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def get_next_business_day(d: date) -> date:
    """
    Get the next trading day (skip weekends and NSE/BSE holidays).
    """
    next_day = d + timedelta(days=1)
    while is_holiday(next_day):
        next_day += timedelta(days=1)
    return next_day

def get_previous_business_day(d: date) -> date:
    """
    Get the previous trading day (skip weekends and NSE/BSE holidays).
    """
    prev_day = d - timedelta(days=1)
    while is_holiday(prev_day):
        prev_day -= timedelta(days=1)
    return prev_day

def get_week_fridays(start_date: date, end_date: date) -> list[date]:
    """
    Get all Fridays (weekday 4) between start and end dates inclusive.
    """
    fridays = []
    current = start_date
    # Align to first Friday if not already
    while current.weekday() != 4:
         current += timedelta(days=1)
    
    while current <= end_date:
        fridays.append(current)
        current += timedelta(days=7)
    return fridays

def get_week_starts(start_date: date, end_date: date) -> List[date]:
    """
    Get all week start dates between start and end dates inclusive.
    A week start is usually Monday, but moves to Tuesday (or next business day)
     if Monday is a holiday.
    """
    week_starts = []
    current = start_date
    
    # Align to first Monday
    while current.weekday() != 0:
        current += timedelta(days=1)
        
    while current <= end_date:
        # Find the first trading day of THIS calendar week (Mon–Fri only).
        # Stop searching if we cross into the next week (i.e. reach next Mon).
        first_day = current
        week_end = current + timedelta(days=4)  # Friday of this week
        while is_holiday(first_day) and first_day <= week_end:
            first_day += timedelta(days=1)

        if not is_holiday(first_day) and first_day <= end_date:
            week_starts.append(first_day)

        current += timedelta(weeks=1)
    return week_starts
