"""Portfolio-only tax estimates with same-year losses, without carry-forward."""

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
            gain = (
                (Decimal(trade["sell_price"]) - Decimal(trade["buy_gross_price"])) * trade["units"]
                - Decimal(trade.get("tax_deductible_charges", "0"))
            )
            try:
                anniversary = bought.replace(year=bought.year + 1)
            except ValueError:
                anniversary = date(bought.year + 1, 2, 28)
            if sold > anniversary:
                long += gain
            else:
                short += gain
        # Long-term losses offset only long-term gains. Short-term losses can
        # also offset remaining long-term gains, within this financial year.
        taxable_short = max(Decimal(0), short)
        long_after_offsets = max(Decimal(0), max(Decimal(0), long) + min(Decimal(0), short))
        taxable_long = max(Decimal(0), long_after_offsets - Decimal(125000))
        base = taxable_short * Decimal("0.20") + taxable_long * Decimal("0.125")
        cess = base * Decimal("0.04")
        estimates.append({
            "label": f"FY {year}–{str(year + 1)[2:]}",
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "short_term_gains": str(short), "long_term_gains": str(long),
            "taxable_short_term_gains": str(taxable_short),
            "long_term_gains_after_offsets": str(long_after_offsets),
            "long_term_exemption": "125000", "taxable_long_term_gains": str(taxable_long),
            "base_tax": str(base), "cess": str(cess),
            "estimated_tax": str((base + cess).quantize(Decimal("0.01"))),
            "basis": "net_realised_gains_with_same_year_loss_offsets_no_carry_forward",
        })
    return estimates
