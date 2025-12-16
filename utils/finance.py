import datetime
from scipy import optimize

def calculate_xirr(cash_flows, guess=0.1):
    """
    Calculate XIRR for a series of cash flows.
    pass in a list of (amount, date) tuples.
    amounts should be negative for investments and positive for returns.
    """
    if not cash_flows:
        return 0.0
    
    # Remove cashflows with 0 amount
    cash_flows = [(amt, dt) for amt, dt in cash_flows if amt != 0]
    
    if not cash_flows:
        return 0.0

    # Check if we have at least one positive and one negative cash flow
    amounts = [cf[0] for cf in cash_flows]
    if all(a > 0 for a in amounts) or all(a < 0 for a in amounts):
        return 0.0

    # sort by date
    cash_flows.sort(key=lambda x: x[1])
    
    start_date = cash_flows[0][1]
    
    def npv(rate):
        total = 0.0
        for amount, dt in cash_flows:
            days = (dt - start_date).days
            total += amount / ((1 + rate) ** (days / 365.0))
        return total

    try:
        return optimize.newton(npv, guess)
    except (RuntimeError, OverflowError):
        return 0.0
