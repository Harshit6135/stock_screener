"""
Date Utilities

Consolidated date logic for backtesting and live trading services.
"""
from typing import List
from datetime import date, timedelta


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
    Get all business days (Monday-Friday) between start and end dates inclusive.
    """
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            days.append(current)
        current += timedelta(days=1)
    return days


def get_next_business_day(d: date) -> date:
    """
    Get the next business day (skip Sat/Sun).
    """
    next_day = d + timedelta(days=1)
    while next_day.weekday() > 4:
        next_day += timedelta(days=1)
    return next_day

def get_previous_business_day(d: date) -> date:
    """
    Get the previous business day (skip Sat/Sun).
    """
    prev_day = d - timedelta(days=1)
    while prev_day.weekday() > 4:
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

def get_week_mondays(start_date, end_date) -> List[date]:
    """Get all Mondays between start and end dates"""
    mondays = []
    current = start_date
    while current.weekday() != 0:
        current += timedelta(days=1)
    while current <= end_date:
        mondays.append(current)
        current += timedelta(weeks=1)
    return mondays

