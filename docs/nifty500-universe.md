# NIFTY 500 research baseline

The supplied constituent file `ind_nifty500list.csv` is the current Strategy 3
screening universe. An unchanged copy is preserved at
`data/reference/nifty500/2026-09-27.csv` as the first observed snapshot. The
file contains 501 unique ISINs: 500 `EQ` rows used by the scan and one `BE`
row (HFCL) retained in the snapshot. Strategy 3 uses NIFTY 500 price history
for its residual momentum calculation.

This is a **current-member historical baseline**. The CSV has no effective
membership dates. Applying these members to earlier market history introduces
survivorship bias. Historical event-study reports carry this limitation and
must not be described as point-in-time NIFTY 500 backtests.

Each Strategy 3 indicator build reads the current CSV and records every row in
`nifty500_membership_snapshots`, keyed by observation date and file SHA-256.
Future CSV changes can therefore be retained when a build runs. Save a dated
copy of each replacement CSV under `data/reference/nifty500/` before replacing
the current file. Historical membership should only be used for point-in-time
research after its effective dates have been acquired and validated.
