from datetime import date
from typing import List, Tuple
from scipy import optimize


def calculate_xirr(cash_flows: List[Tuple[float, date]], guess: float = 0.1) -> float:
    """
    Calculate XIRR (Extended Internal Rate of Return) for a series of cash flows.
    
    Parameters:
        cash_flows (List[Tuple[float, date]]): List of (amount, date) tuples.
            Amounts should be negative for investments and positive for returns.
        guess (float): Initial guess for IRR (default: 0.1)
    
    Returns:
        float: Annualized IRR as a decimal, or 0.0 if calculation fails/invalid
    
    Edge Cases:
        - Returns 0.0 if cash_flows is empty
        - Returns 0.0 if all amounts are 0
        - Returns 0.0 if all amounts have same sign (no investment or return)
        - Returns 0.0 if optimization fails to converge
    
    Example:
        >>> from datetime import date
        >>> cash_flows = [(-10000, date(2024, 1, 1)), (12000, date(2024, 12, 31))]
        >>> xirr = calculate_xirr(cash_flows)
        >>> round(xirr, 4)
        0.2000
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
