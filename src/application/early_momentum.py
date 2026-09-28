"""Isolated, content-addressed Strategy 3 research stages."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.early_momentum_rules import parse_rules
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.indicators.custom import early_momentum_feature_series
from src.platform_kernel import DomainValidationError, QualityStatus


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def adjust_bars(bars, actions, end):
    """Split/bonus-adjust prices and inverse-adjust volume to one end-date basis.

    Inputs are nominal bars; no dividend/total-return claim is made.
    Preserve nominal close for the historical rupee-price eligibility floor.
    """
    result = []
    for bar in bars:
        factor = 1.0
        for action in actions:
            if str(bar['as_of_date']) < action['effective_date'] <= end.isoformat():
                if action['action_type'] == 'SPLIT':
                    factor /= float(action['ratio'])
                elif action['action_type'] == 'BONUS':
                    factor /= 1 + float(action['ratio'])
        result.append({**bar, **{key: float(bar[key]) * factor for key in ('open', 'high', 'low', 'close')},
                       'volume': float(bar['volume']) / factor, 'nominal_close': float(bar['close'])})
    return result


def _required(item, fields, feature):
    missing = [field for field in fields if field not in item]
    if missing:
        raise DomainValidationError(
            f"Strategy 3 raw cache lacks {', '.join(missing)} required for {feature}; rebuild indicators with support for this feature"
        )


def rank_day(values, rules=None):
    """Rank the price-eligible cross-section, then require positive strength."""
    rules = parse_rules(rules)
    for item in values.values():
        basic = ('symbol', rules.ranking_factor, 'relative_volume_50')
        legacy = ('nominal_close', 'trend_ok', 'extension_atr') if rules.version == 1 else ()
        _required(item, basic + legacy, 'ranking')
        squeeze_field = {'current': 'bbw_percentile_126', 'prior10_minimum': 'bbw_prior10_min_percentile',
                         'prior_session': 'bbw_prior_percentile_126'}[rules.squeeze_mode]
        _required(item, (squeeze_field,), 'squeeze')
        if rules.version == 2:
            _required(item, ('adv30_value', 'prior20_volume', 'prior252_volume', 'lower_bb20_2'), 'v4 filters')
        _required(item, ('cross_ok',) if rules.trigger == 'bb_cross'
                  else ('prior20_high', 'prior20_high_cross_ok'), 'trigger')
    eligible = [key for key, item in values.items() if
                (item['nominal_close'] > 50 if rules.version == 1 else
                 item['adv30_value'] > rules.adv30_minimum)]
    ordered = sorted(eligible, key=lambda key: (-values[key][rules.ranking_factor], values[key]['symbol'], key))
    ranks = {key: rank for rank, key in enumerate(ordered, 1)}
    result = {}
    for key, original in values.items():
        item = dict(original)
        rank = ranks.get(key)
        enough = len(ordered) >= 5 if rules.version == 1 else bool(ordered)
        top = rank is not None and enough and rank <= math.ceil(len(ordered) * rules.residual_top_fraction)
        squeeze_ok = item[squeeze_field] <= rules.squeeze_threshold
        if rules.trigger == 'bb_cross':
            cross_ok = bool(item['cross_ok'])
        else:
            cross_ok = bool(item['prior20_high_cross_ok'])
        if rules.version == 2:
            checks = {'liquidity_ok': key in eligible, 'residual_top_quintile': top,
                      'squeeze_ok': squeeze_ok,
                      'low_volume_ok': item['prior20_volume'] < item['prior252_volume'],
                      'cross_ok': cross_ok,
                      'volume_ok': item['relative_volume_50'] > rules.volume_minimum,
                      'stop_ok': item['lower_bb20_2'] > 0}
        else:
            checks = {'price_ok': item['nominal_close'] > 50, 'residual_positive': item[rules.ranking_factor] > 0,
                      'residual_top_quintile': top, 'trend_ok': bool(item['trend_ok']),
                      'squeeze_ok': squeeze_ok, 'cross_ok': cross_ok,
                      'volume_ok': item['relative_volume_50'] > rules.volume_minimum,
                      'extension_ok': item['extension_atr'] < rules.extension_maximum}
        if rules.close_location_minimum is not None:
            _required(item, ('close_location',), 'close_location_minimum')
            checks['close_location_ok'] = item['close_location'] >= rules.close_location_minimum
        if rules.max_daily_move_atr is not None:
            _required(item, ('daily_move_atr',), 'max_daily_move_atr')
            checks['daily_move_atr_ok'] = item['daily_move_atr'] <= rules.max_daily_move_atr
        if rules.benchmark_regime_required:
            _required(item, ('benchmark_regime_ok',), 'benchmark_regime_required')
            checks['benchmark_regime_ok'] = bool(item['benchmark_regime_ok'])
        item.update(checks)
        item['residual_rank'] = rank
        item['residual_percentile'] = rank / len(ordered) if rank is not None else None
        item['signal_reason_codes'] = [k for k, v in checks.items() if not v]
        item['raw_signal'] = not item['signal_reason_codes']
        result[key] = item
    return result


def size_v4_position(equity, available_cash, fill, stop, adv30_value, rules=None):
    """Whole-share order respecting nominal risk, concentration, ADV and cash."""
    from src.application.early_momentum_rules import V4_RULES

    rules = parse_rules(V4_RULES if rules is None else rules)
    if rules.version != 2 or not all(math.isfinite(x) for x in (equity, available_cash, fill, stop, adv30_value)):
        raise DomainValidationError('valid v4 rules and finite sizing inputs are required')
    if equity <= 0 or not 0 <= available_cash <= equity or fill <= stop or stop <= 0 or adv30_value <= 0:
        raise DomainValidationError('invalid v4 sizing inputs')
    budget = min(equity * rules.risk_fraction * fill / (fill - stop),
                 equity * rules.position_cap_fraction,
                 adv30_value * rules.participation_fraction,
                 available_cash)
    shares = math.floor(budget / fill)
    return {'shares': shares, 'order_value': shares * fill,
            'nominal_risk': shares * (fill - stop)}


def evaluate_event(day, values, bars, sessions, rules=None):
    """An absent next exchange session expires the entry; it never delays it."""
    rules = parse_rules(rules)
    future = [session for session in sessions if session > day][:20]
    event = {'signal_date': day, 'symbol': values['symbol'], 'component_values': values,
             'close_T': bars.get(day, {}).get('close'), 'fill_price': None,
             'next_session': future[0] if future else None, 'open_next': None, 'gap_pct': None,
             'execution_status': 'unexecutable_missing_open'}
    if day not in bars or not future or future[0] not in bars:
        return event
    limit = float(bars[day]['close']) * 1.03
    fill = float(bars[future[0]]['open'])
    event['open_limit'] = limit
    if not math.isfinite(fill) or fill <= 0:
        return event
    event.update(open_next=fill, gap_pct=fill / float(bars[day]['close']) - 1)
    if fill > limit:
        event['execution_status'] = 'gap_skipped'
        return event
    if rules.version == 2:
        stop = float(values['lower_bb20_2'])
        event['initial_stop'] = stop
        if not math.isfinite(stop) or stop <= 0:
            event['execution_status'] = 'invalid_stop_skipped'
            return event
        if fill <= stop:
            event['execution_status'] = 'below_stop_skipped'
            return event
        # Normalize to one rupee of portfolio equity; the event study does not
        # assume all overlapping signals can be held simultaneously.
        risk_weight = rules.risk_fraction * fill / (fill - stop)
        event['risk_and_name_cap_weight'] = min(risk_weight, rules.position_cap_fraction)
        event['order_value_limit_inr'] = rules.participation_fraction * float(values['adv30_value'])
    event.update(execution_status='executed', fill_price=fill)
    for horizon in (1, 2, 5, 10, 20):
        window = [bars.get(session) for session in future[:horizon]]
        if len(window) != horizon or any(bar is None for bar in window):
            event[f'h{horizon}_status'] = 'insufficient_future_data'
            continue
        price_fields = ('open', 'close', 'low', 'high') if rules.version == 2 else ('close', 'low', 'high')
        if any(not all(math.isfinite(float(bar[k])) and float(bar[k]) > 0 for k in price_fields) for bar in window):
            event[f'h{horizon}_status'] = 'invalid_future_data'
            continue
        event[f'h{horizon}_status'] = 'complete'
        event[f'return_{horizon}'] = float(window[-1]['close']) / fill - 1
        exit_price = float(window[-1]['close'])
        if rules.version == 2:
            for bar in window:
                opening = float(bar['open'])
                if opening <= stop:
                    exit_price = opening
                    break
                if float(bar['low']) <= stop:
                    exit_price = stop
                    break
            event[f'stopped_return_{horizon}'] = exit_price / fill - 1
        event[f'net_return_{horizon}'] = exit_price / fill - 1 - rules.round_trip_cost_bps / 10_000
        event[f'mae_{horizon}'] = max(0.0, 1 - min(float(bar['low']) for bar in window) / fill)
        event[f'mfe_{horizon}'] = max(0.0, max(float(bar['high']) for bar in window) / fill - 1)
    return event


def summarize(events, rows, rules=None):
    rules = parse_rules(rules)
    def stats(sample):
        return {'count': len(sample), 'mean': mean(sample) if sample else None,
                'median': median(sample) if sample else None,
                'p90': sorted(sample)[math.ceil(len(sample) * .9) - 1] if sample else None}
    statuses = Counter(event['execution_status'] for event in events)
    horizons = {}
    for h in (1, 2, 5, 10, 20):
        returns = [e[f'return_{h}'] for e in events if f'return_{h}' in e]
        horizons[str(h)] = {key: stats([e[f'{key}_{h}'] for e in events if f'{key}_{h}' in e])
                            for key in ('return', 'stopped_return', 'net_return', 'mae', 'mfe')}
        horizons[str(h)]['failed_breakout_rate'] = sum(v < 0 for v in returns) / len(returns) if returns else None
    remaining = list(rows)
    funnel = {'analytical_eligible': len(remaining)}
    funnel_checks = (('liquidity_ok', 'residual_top_quintile', 'squeeze_ok', 'low_volume_ok', 'cross_ok', 'volume_ok', 'stop_ok')
                     if rules.version == 2 else
                     ('price_ok', 'residual_positive', 'residual_top_quintile', 'trend_ok', 'squeeze_ok', 'cross_ok', 'volume_ok', 'extension_ok'))
    for check in funnel_checks:
        remaining = [row for row in remaining if row.get(check)]
        funnel[check] = len(remaining)
    optional_checks = (
        ('close_location_ok', rules.close_location_minimum is not None),
        ('daily_move_atr_ok', rules.max_daily_move_atr is not None),
        ('benchmark_regime_ok', rules.benchmark_regime_required),
    )
    for check, active in optional_checks:
        if active:
            remaining = [row for row in remaining if row.get(check)]
            funnel[check] = len(remaining)
    count = len(events)
    gaps = [e['gap_pct'] for e in events if e.get('gap_pct') is not None]
    return {'raw_signal_count': count, 'execution_status_counts': dict(statuses),
            'round_trip_cost_bps': rules.round_trip_cost_bps,
            'execution_rate': statuses['executed'] / count if count else None,
            'gap_skipped_rate': statuses['gap_skipped'] / count if count else None,
            'gap_distribution': stats(gaps), 'horizons': horizons, 'signal_funnel': funnel,
            'failure_reason_counts': dict(Counter(reason for row in rows for reason in row['signal_reason_codes'])),
            'symbol_counts': dict(Counter(e['symbol'] for e in events)),
            'distinct_symbols': len({e['symbol'] for e in events})}


def validation_success(yearly):
    """Fixed descriptive gates; these are not a statistical significance test."""
    gates = {}
    for year in ('2024', '2025'):
        pair = yearly.get(year, {})
        strategy, baseline = pair.get('strategy', {}), pair.get('baseline', {})
        s20 = strategy.get('horizons', {}).get('20', {})
        b20 = baseline.get('horizons', {}).get('20', {})
        s5 = strategy.get('horizons', {}).get('5', {})
        b5 = baseline.get('horizons', {}).get('5', {})
        net_s = s20.get('net_return', {})
        net_b = b20.get('net_return', {})
        mae_s = s5.get('mae', {}).get('p90')
        mae_b = b5.get('mae', {}).get('p90')
        fail_s = s5.get('failed_breakout_rate')
        fail_b = b5.get('failed_breakout_rate')
        gates[year] = {
            'minimum_complete_20': net_s.get('count', 0) >= 30 and net_b.get('count', 0) >= 30,
            'positive_net_20_mean': net_s.get('mean') is not None and net_s['mean'] > 0,
            'net_20_mean_above_baseline': net_s.get('mean') is not None and net_b.get('mean') is not None and net_s['mean'] > net_b['mean'],
            'p90_mae_5_below_baseline': mae_s is not None and mae_b is not None and mae_s < mae_b,
            'failed_breakout_5_below_baseline': fail_s is not None and fail_b is not None and fail_s < fail_b,
        }
    return {'definition': 'All five descriptive gates must pass independently in 2024 and 2025; 50 bps round-trip cost is an explicit assumption, not measured slippage.',
            'yearly_gates': gates,
            'passed': all(all(g.values()) for g in gates.values())}


class EarlyMomentumJobs:
    STRATEGY_ID = 'strategy3'
    INDICATOR_SET = 'strategy3:early-momentum-v3'
    NAMESPACE = 'early_momentum_v3'

    def __init__(self, market, publisher, runtime, universe_csv_path=None):
        self.market, self.publisher, self.runtime = market, publisher, runtime
        self.universe_csv_path = Path(universe_csv_path) if universe_csv_path is not None else Path(__file__).parents[2] / 'ind_nifty500list.csv'
        migrate_sqlite(market.path, 'early_momentum_v3_stages', {1: (
            'CREATE TABLE early_momentum_v3_stages (stage TEXT, start_date TEXT, end_date TEXT, artifact_id TEXT NOT NULL, PRIMARY KEY(stage,start_date,end_date))',
        )})
        migrate_sqlite(market.path, 'nifty500_membership_snapshots', {1: (
            'CREATE TABLE nifty500_membership_snapshots (observed_on TEXT NOT NULL, csv_sha256 TEXT NOT NULL, symbol TEXT NOT NULL, isin TEXT NOT NULL, series TEXT NOT NULL, PRIMARY KEY(observed_on,csv_sha256,isin))',
        )})

    @staticmethod
    def _dates(payload):
        if not isinstance(payload, dict) or set(payload) != {'start_date', 'end_date'}:
            raise DomainValidationError('Strategy 3 requires start_date and end_date only')
        try:
            start, end = (date.fromisoformat(str(payload[key])) for key in ('start_date', 'end_date'))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError('Strategy 3 dates must be ISO dates') from exc
        if start > end or (end - start).days > 366 * 6 or end >= datetime.now(ZoneInfo('Asia/Kolkata')).date():
            raise DomainValidationError('Strategy 3 requires a completed historical range of at most six years')
        return start, end

    def _universe(self):
        if not self.universe_csv_path.is_file():
            raise DomainValidationError(f'Strategy 3 NIFTY 500 constituent file is missing: {self.universe_csv_path}')
        csv_bytes = self.universe_csv_path.read_bytes()
        csv_sha256 = hashlib.sha256(csv_bytes).hexdigest()
        reader = csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig')))
        if not reader.fieldnames or not {'Symbol', 'Series', 'ISIN Code'} <= set(reader.fieldnames):
            raise DomainValidationError('Strategy 3 NIFTY 500 CSV requires Symbol, Series and ISIN Code columns')
        rows = list(reader)
        all_members = [(str(row['Symbol']).strip(), str(row['ISIN Code']).strip(), str(row['Series']).strip())
                       for row in rows]
        if not all_members or any(not symbol or len(isin) != 12 or not series for symbol, isin, series in all_members):
            raise DomainValidationError('Strategy 3 NIFTY 500 CSV contains invalid members')
        if len({isin for _, isin, _ in all_members}) != len(all_members):
            raise DomainValidationError('Strategy 3 NIFTY 500 CSV contains duplicate ISINs')
        members = [(str(row['Symbol']).strip(), str(row['ISIN Code']).strip())
                   for row in rows if str(row['Series']).strip() == 'EQ']
        if not members or len({symbol for symbol, _ in members}) != len(members):
            raise DomainValidationError('Strategy 3 NIFTY 500 CSV contains duplicate EQ members')
        observed_on = datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
        with sqlite_connection(self.market.path) as connection:
            connection.executemany(
                'INSERT OR IGNORE INTO nifty500_membership_snapshots (observed_on,csv_sha256,symbol,isin,series) VALUES (?,?,?,?,?)',
                [(observed_on, csv_sha256, symbol, isin, series) for symbol, isin, series in all_members],
            )
        return {isin for _, isin in members}

    def _source(self, start, end):
        constituents = self._universe()
        benchmark = self.market.instrument('NIFTY 500')
        histories = self.market.histories(start - timedelta(days=900), end,
                                          isins=constituents | {str(benchmark['isin'])})
        benchmark_id = str(benchmark['instrument_id'])
        if benchmark_id not in histories:
            raise DomainValidationError('NIFTY 500 benchmark history is required')
        histories = {key: value for key, value in histories.items()
                     if value[1]['exchange'] == 'NSE' and
                     (key == benchmark_id or str(value[1]['isin']) in constituents)}
        actions = defaultdict(list)
        for category, artifact_id in self.publisher.store.artifact_locations():
            if category == 'corporate-actions/facts':
                _, fact = self.publisher.store.read_json(category, artifact_id)
                if fact['instrument_id'] in histories and fact['effective_date'] <= end.isoformat():
                    actions[fact['instrument_id']].append(fact)
        for facts in actions.values():
            facts.sort(key=lambda f: (f['effective_date'], f.get('action_id', '')))
        return histories, dict(actions), benchmark_id

    def _publish(self, stage, start, end, payload, upstream=()):
        payload = {**payload, 'implementation_hash': digest([
            Path(__file__).read_text(encoding='utf-8'),
            (Path(__file__).parents[1] / 'indicators/custom/early_momentum.py').read_text(encoding='utf-8'),
        ])}
        artifact_id = str(uuid5(NAMESPACE_URL, digest(payload)))
        # Keep the established category readable by the existing report API;
        # v3 isolation is carried by its stage table, content IDs and metadata.
        category = f'research/strategy3-{stage}'
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(category, artifact_id, payload, upstream_ids=upstream, quality=QualityStatus.PARTIAL)
        # Immutable snapshot replacement removes obsolete rows, even for a zero-signal run.
        with sqlite_connection(self.market.path) as connection:
            connection.execute('INSERT OR REPLACE INTO early_momentum_v3_stages VALUES (?,?,?,?)',
                               (stage, start.isoformat(), end.isoformat(), artifact_id))
        return artifact_id

    def _load(self, stage, start, end):
        with sqlite_connection(self.market.path, read_only=True) as connection:
            row = connection.execute('SELECT artifact_id FROM early_momentum_v3_stages WHERE stage=? AND start_date=? AND end_date=?',
                                     (stage, start.isoformat(), end.isoformat())).fetchone()
        if row is None:
            raise DomainValidationError(f'Strategy 3 {stage} is missing for this exact range; build it first')
        _, payload = self.publisher.store.read_json(f'research/strategy3-{stage}', row[0])
        return row[0], payload

    def rebuild_indicators(self, payload, context):
        start, end = self._dates(payload)
        histories, actions, benchmark_id = self._source(start, end)
        constituents = self._universe()
        matched = {str(identity['isin']) for key, (_, identity) in histories.items()
                   if key != benchmark_id}
        rows = {}
        for number, (key, (bars, identity)) in enumerate(histories.items(), 1):
            if str(identity['isin']).startswith('INDEX:'):
                continue
            adjusted = adjust_bars(bars, actions.get(key, []), end)
            nominal = {str(b['as_of_date']): b['nominal_close'] for b in adjusted}
            series = early_momentum_feature_series(adjusted, histories[benchmark_id][0])
            rows[key] = {day: {**item, 'nominal_close': nominal[day], 'symbol': identity['symbol']}
                         for day, item in series.items() if start.isoformat() <= day <= end.isoformat()}
            context.checkpoint(progress={'stage': 'strategy3_indicators', 'processed_instruments': number, 'total_instruments': len(histories)})
        artifact = self._publish('indicators', start, end, {
            **payload, 'namespace': self.NAMESPACE, 'indicator_set': self.INDICATOR_SET,
            'benchmark': 'NIFTY 500', 'universe_source': str(self.universe_csv_path.name),
            'universe_member_count': len(constituents), 'universe_matched_count': len(matched),
            'universe_missing_isins': sorted(constituents - matched),
            'universe_csv_sha256': hashlib.sha256(self.universe_csv_path.read_bytes()).hexdigest(),
            'source_hash': digest([histories, actions]), 'rows': rows,
            'indicator_feature_hash': digest((Path(__file__).parents[1] / 'indicators/custom/early_momentum.py').read_text(encoding='utf-8')),
            'adjustment_basis': 'nominal input bars plus recorded split/bonus facts; volume inverse adjusted',
            'limitations': ['Corporate-action fact coverage is not certified',
                            'Current NIFTY 500 EQ membership applied to historical dates; survivorship bias'],
        })
        return {'artifact_id': artifact, 'rows': sum(len(series) for series in rows.values())}

    def rebuild_rankings(self, payload, context):
        if not isinstance(payload, dict) or not set(payload) <= {'start_date', 'end_date', 'rules'}:
            raise DomainValidationError('Strategy 3 rankings require start_date, end_date and optional rules only')
        start, end = self._dates({key: payload[key] for key in ('start_date', 'end_date') if key in payload})
        rules = parse_rules(payload.get('rules'))
        rule_spec, rule_hash = rules.to_dict(), digest(rules.to_dict())
        raw_id, raw = self._load('indicators', start, end)
        current_feature_hash = digest((Path(__file__).parents[1] / 'indicators/custom/early_momentum.py').read_text(encoding='utf-8'))
        if raw.get('indicator_feature_hash') != current_feature_hash:
            raise DomainValidationError('Strategy 3 raw feature implementation changed; rebuild indicators')
        if raw.get('universe_csv_sha256') != hashlib.sha256(self.universe_csv_path.read_bytes()).hexdigest():
            raise DomainValidationError('Strategy 3 NIFTY 500 universe changed; rebuild indicators')
        by_day = defaultdict(dict)
        for key, series in raw['rows'].items():
            for day, values in series.items():
                by_day[day][key] = values
        ranked = {}
        for day, values in sorted(by_day.items()):
            ranked[day] = rank_day(values, rules)
            context.checkpoint(progress={'stage': 'strategy3_rankings', 'session': day})
        artifact = self._publish('rankings', start, end, {
            'start_date': start.isoformat(), 'end_date': end.isoformat(), 'namespace': self.NAMESPACE,
            'raw_artifact_id': raw_id,
            'rules': rule_spec, 'rules_hash': rule_hash, 'rows': ranked,
        }, (raw_id,))
        return {'artifact_id': artifact, 'sessions': len(ranked)}

    def event_study(self, payload, context):
        if not isinstance(payload, dict) or not set(payload) <= {'start_date', 'end_date', 'evaluation_end_date'}:
            raise DomainValidationError('Strategy 3 event study requires dates and optional evaluation_end_date only; rules come from rankings')
        start, end = self._dates({key: payload[key] for key in ('start_date', 'end_date') if key in payload})
        evaluation_end = None
        if payload.get('evaluation_end_date') is not None:
            try:
                evaluation_end = date.fromisoformat(str(payload['evaluation_end_date']))
            except ValueError as exc:
                raise DomainValidationError('evaluation_end_date must be an ISO date') from exc
            if evaluation_end > end:
                raise DomainValidationError('development evaluation_end_date must be <= end_date')
        raw_id, raw = self._load('indicators', start, end)
        ranks_id, ranks = self._load('rankings', start, end)
        current_feature_hash = digest((Path(__file__).parents[1] / 'indicators/custom/early_momentum.py').read_text(encoding='utf-8'))
        if raw.get('indicator_feature_hash') != current_feature_hash:
            raise DomainValidationError('Strategy 3 raw feature implementation changed; rebuild indicators then rankings')
        if raw.get('universe_csv_sha256') != hashlib.sha256(self.universe_csv_path.read_bytes()).hexdigest():
            raise DomainValidationError('Strategy 3 NIFTY 500 universe changed; rebuild indicators then rankings')
        if ranks['raw_artifact_id'] != raw_id:
            raise DomainValidationError('Strategy 3 rankings are stale; rebuild rankings')
        histories, facts, _ = self._source(start, end)
        if digest([histories, facts]) != raw['source_hash']:
            raise DomainValidationError('Strategy 3 indicators are stale after source changes; rebuild indicators then rankings')
        if digest(ranks.get('rules')) != ranks.get('rules_hash'):
            raise DomainValidationError('Strategy 3 rankings contain invalid rule metadata')
        rules = parse_rules(ranks['rules'])
        cutoff = evaluation_end or min(end + timedelta(days=60), datetime.now(ZoneInfo('Asia/Kolkata')).date() - timedelta(days=1))
        histories, facts, benchmark_id = self._source(start, cutoff)
        sessions = [str(b['as_of_date']) for b in histories[benchmark_id][0]]
        adjusted = {key: {str(b['as_of_date']): b for b in adjust_bars(bars, facts.get(key, []), cutoff)}
                    for key, (bars, _) in histories.items()}
        events, baseline = [], []
        for day, values in sorted(ranks['rows'].items()):
            for key, item in values.items():
                baseline_eligible = item['liquidity_ok'] if rules.version == 2 else item['price_ok']
                for selected, destination in ((item['raw_signal'], events),
                                              (baseline_eligible and item['naive_52w_high_cross_ok'], baseline)):
                    if selected:
                        destination.append({'instrument_id': key, **evaluate_event(day, item, adjusted.get(key, {}), sessions, rules)})
            context.checkpoint(progress={'stage': 'strategy3_event_study', 'session': day})
        rows = [row for values in ranks['rows'].values() for row in values.values()]
        report = {**payload, 'strategy_id': 'strategy3', 'signal_start_date': start.isoformat(),
                  'signal_end_date': end.isoformat(), 'outcome_cutoff_date': cutoff.isoformat(),
                  'rules': ranks['rules'], 'rules_hash': ranks['rules_hash'],
                  'mae_convention': 'positive loss magnitude; entry session is day 1',
                  'limitations': raw['limitations'], 'summary': summarize(events, rows, ranks['rules']),
                  'baseline': summarize(baseline, [], rules), 'events': events, 'baseline_events': baseline,
                  'baseline_definition': 'first close cross above prior 252-session close high, same universe, liquidity and next-open execution',
                  'research_periods': {'development': [2022, 2023], 'validation_previously_viewed': [2024, 2025], 'exposed': [2026]},
                  'portfolio_note': 'Event returns are unweighted; 1% risk, 10% name cap, 1% ADV30 order cap, and 100% gross exposure require a separate portfolio simulator.',
                  'raw_artifact_id': raw_id, 'rankings_artifact_id': ranks_id,
                  'evaluation_source_hash': digest([histories, facts]), 'yearly': {}}
        for year in range(start.year, end.year + 1):
            prefix = str(year)
            yearly_rows = [row for day, values in ranks['rows'].items() if day.startswith(prefix) for row in values.values()]
            report['yearly'][prefix] = {
                'strategy': summarize([e for e in events if e['signal_date'].startswith(prefix)], yearly_rows, ranks['rules']),
                'baseline': summarize([e for e in baseline if e['signal_date'].startswith(prefix)], [], rules),
            }
        report['validation_success'] = (validation_success(report['yearly'])
                                        if rules.version == 2 and {'2024', '2025'} <= set(report['yearly'])
                                        else None)
        artifact = self._publish('event-study', start, end, report, (raw_id, ranks_id))
        return {'artifact_id': artifact, **{k: v for k, v in report.items() if k not in ('events', 'baseline_events')}}
