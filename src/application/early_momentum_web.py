"""Read-only Strategy 3 report view, backed by immutable published results."""

from flask import Blueprint, jsonify, render_template_string

from src.platform_kernel import DomainValidationError


def create_early_momentum_blueprint(store):
    blueprint = Blueprint('strategy3_reports', __name__)

    @blueprint.get('/api/v2/strategy3/reports/<artifact_id>')
    def report_json(artifact_id):
        try:
            _, report = store.read_json('research/strategy3-event-study', artifact_id)
        except DomainValidationError:
            return jsonify(error='Strategy 3 report not found'), 404
        return jsonify(report)

    @blueprint.get('/strategy3/reports/<artifact_id>')
    def report_page(artifact_id):
        try:
            _, report = store.read_json('research/strategy3-event-study', artifact_id)
        except DomainValidationError:
            return 'Strategy 3 report not found', 404
        return render_template_string('''<!doctype html><title>Strategy 3 entry study</title>
        <main><h1>Strategy 3 entry study</h1><p>{{r.start_date}} to {{r.end_date}}</p>
        <p>{{r.mae_convention}}</p>{% for note in r.limitations %}<p>{{note}}</p>{% endfor %}
        <h2>Entry diagnostics</h2><table><tr><th>Metric</th><th>Strategy 3</th><th>52-week high baseline</th></tr>
        {% for key in ['raw_signal_count','execution_rate','gap_skipped_rate','distinct_symbols'] %}
        <tr><td>{{key}}</td><td>{{r.summary[key]}}</td><td>{{r.baseline[key]}}</td></tr>{% endfor %}</table>
        <h2>Signal funnel</h2><pre>{{r.summary.signal_funnel | tojson(indent=2)}}</pre>
        <h2>Returns and excursions</h2><pre>{{r.summary.horizons | tojson(indent=2)}}</pre>
        <h2>Baseline</h2><pre>{{r.baseline.horizons | tojson(indent=2)}}</pre>
        <h2>Yearly results</h2><pre>{{r.yearly | tojson(indent=2)}}</pre></main>''', r=report)

    return blueprint
