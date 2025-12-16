"""
Main Router - Dashboard and orchestration routes
"""
from flask import Blueprint, render_template, request, jsonify

from router.day0_router import init_db
from router.kite_router import get_latest_data
from router.ranking_router import calculate_score
from router.indicators_router import calculate_indicators
from models import ActionsModel


main_bp = Blueprint('main', __name__)


@main_bp.route("/")
def dashboard():
    """Render the main dashboard"""
    return render_template('dashboard.html')


@main_bp.route("/day0")
def day0():
    """Initialize database with Day 0 setup"""
    init_db()
    return "Day 0 completed."


@main_bp.route("/update_market_data")
def update_market_data():
    """Fetch latest market data for all instruments"""
    get_latest_data()
    return "Market data update completed."


@main_bp.route("/update_indicators")
def calc_indicators():
    """Calculate indicators for all instruments"""
    calculate_indicators()
    return "Calculation of Indicators completed."


@main_bp.route("/latest_rank")
def generate_ranking():
    """Generate latest rankings and scores"""
    calculate_score()
    return "Ranking completed and saved."


@main_bp.route("/api/actions")
def get_actions():
    """Get actions with optional date filter, sorted by composite_score desc"""
    date_filter = request.args.get('date')
    query = ActionsModel.query
    if date_filter:
        query = query.filter(ActionsModel.action_date == date_filter)
    actions = query.order_by(ActionsModel.composite_score.desc().nullslast()).all()
    return jsonify([{
        'id': a.id,
        'action_date': str(a.action_date),
        'action_type': a.action_type,
        'tradingsymbol': a.tradingsymbol,
        'composite_score': a.composite_score,
        'units': a.units,
        'expected_price': a.expected_price,
        'amount': a.amount,
        'swap_from_symbol': a.swap_from_symbol,
        'swap_from_units': a.swap_from_units,
        'swap_from_price': a.swap_from_price,
        'status': a.status
    } for a in actions])
