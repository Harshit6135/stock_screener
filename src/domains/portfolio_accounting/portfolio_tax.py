"""Portfolio-only listed-equity tax estimates without loss offsets."""

from datetime import date
from decimal import Decimal


def portfolio_tax_estimates(journal: list[dict], as_of: date) -> list[dict]:
    start_year = as_of.year if as_of.month >= 4 else as_of.year - 1
    estimates = []
    for year in (start_year, start_year - 1):
        start, end = date(year, 4, 1), date(year + 1, 3, 31)
        short, long = Decimal(0), Decimal(0)
        for trade in journal:
            bought, sold = date.fromisoformat(trade["buy_date"]), date.fromisoformat(trade["sell_date"])
            if not start <= sold <= min(end, as_of):
                continue
            # Until itemized charges are available, use gross gains. Bundled
            # trade fees can contain STT, which is not a capital-gains deduction.
            gain = (Decimal(trade["sell_price"]) - Decimal(trade["buy_gross_price"])) * trade["units"]
            if gain <= 0:
                continue  # User explicitly requested no loss offsets.
            try:
                anniversary = bought.replace(year=bought.year + 1)
            except ValueError:
                anniversary = date(bought.year + 1, 2, 28)
            if sold > anniversary:
                long += gain
            else:
                short += gain
        taxable_long = max(Decimal(0), long - Decimal(125000))
        base = short * Decimal("0.20") + taxable_long * Decimal("0.125")
        cess = base * Decimal("0.04")
        estimates.append({
            "label": f"FY {year}–{str(year + 1)[2:]}",
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "short_term_gains": str(short), "long_term_gains": str(long),
            "long_term_exemption": "125000", "taxable_long_term_gains": str(taxable_long),
            "base_tax": str(base), "cess": str(cess),
            "estimated_tax": str((base + cess).quantize(Decimal("0.01"))),
            "basis": "positive_gross_realised_gains_no_loss_offsets",
        })
    return estimates
