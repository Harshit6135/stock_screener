# Strategy 3 final comparison

Holdout signal window: `2025-01-01` through `2026-09-18`

| Rules | Window | Event-study artifact | Complete h20 | Mean h20 |
|---|---|---|---:|---:|
| legacy | development | e140683d-3ed4-592e-8854-88a9ea5e12ed | 520 | 1.76% |
| legacy | validation | f1af0df6-d7f8-5a88-91c8-3b4124751c58 | 335 | -0.39% |
| C5_raw63_skip5 | development | 17243810-d5c4-597a-a556-fb30946a4866 | 471 | 2.30% |
| C5_raw63_skip5 | validation | 1534fc9f-83b5-5a83-a44c-fd28b4d5d6b5 | 292 | 0.11% |

## Returns by window and year

| Rules | Window | Year | Signals | Executed | Horizon | Complete | Mean | Median | Failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy | development | all | 544 | 523 | 1 | 523 | -0.35% | -0.57% | 60.04% |
| legacy | development | all | 544 | 523 | 5 | 522 | -0.35% | -0.85% | 56.70% |
| legacy | development | all | 544 | 523 | 10 | 521 | 0.27% | -0.25% | 52.40% |
| legacy | development | all | 544 | 523 | 20 | 520 | 1.76% | 0.55% | 47.88% |
| legacy | development | 2022 | 179 | 167 | 1 | 167 | -0.30% | -0.45% | 58.68% |
| legacy | development | 2022 | 179 | 167 | 5 | 167 | -0.64% | -1.07% | 56.89% |
| legacy | development | 2022 | 179 | 167 | 10 | 167 | -0.44% | -0.44% | 53.29% |
| legacy | development | 2022 | 179 | 167 | 20 | 167 | -0.20% | -0.62% | 51.50% |
| legacy | development | 2023 | 197 | 193 | 1 | 193 | -0.20% | -0.54% | 61.14% |
| legacy | development | 2023 | 197 | 193 | 5 | 193 | -0.02% | -0.61% | 55.96% |
| legacy | development | 2023 | 197 | 193 | 10 | 193 | 1.28% | 0.65% | 47.67% |
| legacy | development | 2023 | 197 | 193 | 20 | 193 | 2.88% | 0.84% | 46.11% |
| legacy | development | 2024 | 168 | 163 | 1 | 163 | -0.57% | -0.77% | 60.12% |
| legacy | development | 2024 | 168 | 163 | 5 | 162 | -0.43% | -1.01% | 57.41% |
| legacy | development | 2024 | 168 | 163 | 10 | 161 | -0.22% | -0.88% | 57.14% |
| legacy | development | 2024 | 168 | 163 | 20 | 160 | 2.45% | 1.44% | 46.25% |
| legacy | validation | all | 382 | 369 | 1 | 369 | -0.37% | -0.65% | 59.62% |
| legacy | validation | all | 382 | 369 | 5 | 366 | -0.62% | -0.82% | 55.46% |
| legacy | validation | all | 382 | 369 | 10 | 358 | -0.39% | -1.10% | 58.10% |
| legacy | validation | all | 382 | 369 | 20 | 335 | -0.39% | -1.83% | 55.22% |
| legacy | validation | 2025 | 226 | 221 | 1 | 221 | -0.31% | -0.46% | 58.37% |
| legacy | validation | 2025 | 226 | 221 | 5 | 221 | -1.06% | -1.03% | 57.47% |
| legacy | validation | 2025 | 226 | 221 | 10 | 221 | -1.04% | -1.19% | 59.28% |
| legacy | validation | 2025 | 226 | 221 | 20 | 221 | -1.76% | -2.45% | 60.18% |
| legacy | validation | 2026 | 156 | 148 | 1 | 148 | -0.45% | -0.75% | 61.49% |
| legacy | validation | 2026 | 156 | 148 | 5 | 145 | 0.05% | -0.31% | 52.41% |
| legacy | validation | 2026 | 156 | 148 | 10 | 137 | 0.66% | -1.00% | 56.20% |
| legacy | validation | 2026 | 156 | 148 | 20 | 114 | 2.27% | 1.43% | 45.61% |
| C5_raw63_skip5 | development | all | 509 | 475 | 1 | 475 | -0.56% | -0.74% | 60.21% |
| C5_raw63_skip5 | development | all | 509 | 475 | 5 | 473 | -0.65% | -1.35% | 58.56% |
| C5_raw63_skip5 | development | all | 509 | 475 | 10 | 472 | 0.19% | -0.69% | 53.18% |
| C5_raw63_skip5 | development | all | 509 | 475 | 20 | 471 | 2.30% | 0.54% | 46.92% |
| C5_raw63_skip5 | development | 2022 | 189 | 174 | 1 | 174 | -0.87% | -0.96% | 62.64% |
| C5_raw63_skip5 | development | 2022 | 189 | 174 | 5 | 174 | -1.30% | -1.50% | 62.64% |
| C5_raw63_skip5 | development | 2022 | 189 | 174 | 10 | 174 | -0.89% | -1.14% | 54.02% |
| C5_raw63_skip5 | development | 2022 | 189 | 174 | 20 | 174 | 0.15% | -0.30% | 50.57% |
| C5_raw63_skip5 | development | 2023 | 171 | 163 | 1 | 163 | -0.31% | -0.68% | 58.28% |
| C5_raw63_skip5 | development | 2023 | 171 | 163 | 5 | 163 | -0.37% | -1.03% | 57.67% |
| C5_raw63_skip5 | development | 2023 | 171 | 163 | 10 | 163 | 1.56% | -0.23% | 50.31% |
| C5_raw63_skip5 | development | 2023 | 171 | 163 | 20 | 163 | 4.45% | 1.77% | 41.72% |
| C5_raw63_skip5 | development | 2024 | 149 | 138 | 1 | 138 | -0.48% | -0.70% | 59.42% |
| C5_raw63_skip5 | development | 2024 | 149 | 138 | 5 | 136 | -0.14% | -0.83% | 54.41% |
| C5_raw63_skip5 | development | 2024 | 149 | 138 | 10 | 135 | -0.08% | -1.18% | 55.56% |
| C5_raw63_skip5 | development | 2024 | 149 | 138 | 20 | 134 | 2.49% | 0.52% | 48.51% |
| C5_raw63_skip5 | validation | all | 328 | 317 | 1 | 317 | -0.40% | -0.50% | 58.99% |
| C5_raw63_skip5 | validation | all | 328 | 317 | 5 | 316 | -0.75% | -0.96% | 56.01% |
| C5_raw63_skip5 | validation | all | 328 | 317 | 10 | 307 | -0.12% | -0.80% | 54.07% |
| C5_raw63_skip5 | validation | all | 328 | 317 | 20 | 292 | 0.11% | -1.35% | 53.77% |
| C5_raw63_skip5 | validation | 2025 | 197 | 192 | 1 | 192 | -0.39% | -0.42% | 57.29% |
| C5_raw63_skip5 | validation | 2025 | 197 | 192 | 5 | 192 | -1.04% | -1.24% | 59.38% |
| C5_raw63_skip5 | validation | 2025 | 197 | 192 | 10 | 192 | -0.33% | -1.06% | 55.21% |
| C5_raw63_skip5 | validation | 2025 | 197 | 192 | 20 | 192 | -0.95% | -2.24% | 61.98% |
| C5_raw63_skip5 | validation | 2026 | 131 | 125 | 1 | 125 | -0.42% | -0.70% | 61.60% |
| C5_raw63_skip5 | validation | 2026 | 131 | 125 | 5 | 124 | -0.32% | -0.16% | 50.81% |
| C5_raw63_skip5 | validation | 2026 | 131 | 125 | 10 | 115 | 0.24% | -0.52% | 52.17% |
| C5_raw63_skip5 | validation | 2026 | 131 | 125 | 20 | 100 | 2.15% | 3.64% | 38.00% |

## Limitations

- 0 corporate-action facts existed at experiment time; nominal bars are therefore unadjusted by recorded facts
- The instrument set is the current survivor universe; results are subject to survivorship bias
- The validation period had previously been viewed, so this was not a blind validation
- Returns exclude transaction costs and slippage, per user instruction
