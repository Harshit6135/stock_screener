"""Run the fixed VAVCS v4 development and validation windows.

Usage: python tools/strategy3_v4.py --database instance/system.db --output v4-results.json
The current Nifty 500 CSV is applied retrospectively, so survivorship bias remains.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.early_momentum_rules import V4_RULES
from src.platform_kernel import DomainValidationError
from tools.strategy3_experiment import _context, build_runtime

WINDOWS = {
    'development': ('2022-01-01', '2023-12-31'),
    'validation_previously_viewed': ('2024-01-01', '2025-12-31'),
}


def run(database: Path) -> dict:
    jobs, _publisher = build_runtime(database)
    output = {'rules': V4_RULES.to_dict(), 'windows': {}}
    for label, (start, end) in WINDOWS.items():
        dates = {'start_date': start, 'end_date': end}
        indicators = jobs.rebuild_indicators(dates, _context(label + ':indicators'))
        rankings = jobs.rebuild_rankings({**dates, 'rules': V4_RULES.to_dict()}, _context(label + ':rankings'))
        study = jobs.event_study(dates, _context(label + ':event-study'))
        output['windows'][label] = {'indicators': indicators, 'rankings': rankings,
                                    'event_study': study}
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'instance/system.db')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.database)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'validation_success':
                      result['windows']['validation_previously_viewed']['event_study']['validation_success']},
                     indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except DomainValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
