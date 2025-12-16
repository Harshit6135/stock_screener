"""
Portfolio Management API Endpoints

Provides endpoints for:
- Managing invested stocks
- Risk configuration
- Top 20 rankings
- Action generation
"""
from datetime import date
import requests

from db import db
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from sqlalchemy.exc import SQLAlchemyError

from models import RiskConfigModel, InvestedModel, RankingModel, ActionsModel
from schemas import (
    RiskConfigSchema, 
    InvestedSchema, InvestedInputSchema,
    RankingSchema, Top20Schema,
    ActionsSchema, GenerateActionsInputSchema
)
from services.portfolio_service import PortfolioService
from utils.stop_loss import calculate_initial_stop_loss


blp = Blueprint("portfolio", __name__, description="Portfolio management operations")
BASE_URL = "http://127.0.0.1:5000"


# ==================== RISK CONFIG ====================

@blp.route("/risk_config")
class RiskConfig(MethodView):
    @blp.response(200, RiskConfigSchema)
    def get(self):
        """Get current risk configuration"""
        config = RiskConfigModel.query.first()
        if not config:
            # Create default config if none exists
            config = RiskConfigModel(
                initial_capital=100000.0,
                current_capital=100000.0,
                risk_per_trade=1000.0,
                max_positions=15,
                buffer_percent=0.25,
                exit_threshold=40.0,
                stop_loss_multiplier=2.0
            )
            db.session.add(config)
            db.session.commit()
        return config

    @blp.arguments(RiskConfigSchema)
    @blp.response(200, RiskConfigSchema)
    def put(self, config_data):
        """Update risk configuration"""
        config = RiskConfigModel.query.first()
        if not config:
            config = RiskConfigModel(**config_data)
            db.session.add(config)
        else:
            for field, value in config_data.items():
                if hasattr(config, field):
                    setattr(config, field, value)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        return config


# ==================== INVESTED STOCKS ====================

@blp.route("/invested")
class InvestedList(MethodView):
    @blp.response(200, InvestedSchema(many=True))
    def get(self):
        """Get all invested stocks"""
        return InvestedModel.query.all()

    @blp.arguments(InvestedInputSchema)
    @blp.response(201, InvestedSchema)
    def post(self, invest_data):
        """Add a new invested stock with calculated stop-loss"""
        symbol = invest_data['tradingsymbol']
        buy_price = invest_data['buy_price']
        num_shares = invest_data['num_shares']
        
        # Check if already invested
        existing = InvestedModel.query.filter_by(tradingsymbol=symbol).first()
        if existing:
            abort(400, message=f"Already invested in {symbol}")
        
        # Get ATR from indicators
        atr = None
        try:
            resp = requests.get(f"{BASE_URL}/indicators/latest/{symbol}")
            if resp.status_code == 200:
                indicator_data = resp.json()
                atr = indicator_data.get('atrr_14')
        except Exception:
            pass
        
        # Get risk config for stop multiplier
        config = RiskConfigModel.query.first()
        stop_multiplier = config.stop_loss_multiplier if config else 2.0
        
        # Calculate stop-loss
        initial_stop = calculate_initial_stop_loss(buy_price, atr or (buy_price * 0.03), stop_multiplier)
        
        invested = InvestedModel(
            tradingsymbol=symbol,
            buy_price=buy_price,
            num_shares=num_shares,
            buy_date=date.today(),
            atr_at_entry=atr,
            initial_stop_loss=round(initial_stop, 2),
            current_stop_loss=round(initial_stop, 2)
        )
        
        try:
            db.session.add(invested)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        
        return invested

    @blp.response(200, {"message": str})
    def delete(self):
        """Clear all invested stocks"""
        try:
            num_deleted = db.session.query(InvestedModel).delete()
            db.session.commit()
            return {"message": f"Deleted {num_deleted} positions"}
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))


@blp.route("/invested/<string:tradingsymbol>")
class InvestedItem(MethodView):
    @blp.response(200, InvestedSchema)
    def get(self, tradingsymbol):
        """Get specific invested stock"""
        invested = InvestedModel.query.filter_by(tradingsymbol=tradingsymbol).first()
        if not invested:
            abort(404, message=f"Not invested in {tradingsymbol}")
        return invested

    @blp.response(200, {"message": str})
    def delete(self, tradingsymbol):
        """Remove specific invested stock"""
        invested = InvestedModel.query.filter_by(tradingsymbol=tradingsymbol).first()
        if not invested:
            abort(404, message=f"Not invested in {tradingsymbol}")
        try:
            db.session.delete(invested)
            db.session.commit()
            return {"message": f"Removed {tradingsymbol} from portfolio"}
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))


# ==================== RANKING ====================

@blp.route("/ranking/top20")
class Top20Ranking(MethodView):
    @blp.response(200, Top20Schema(many=True))
    def get(self):
        """Get top 20 ranked stocks (including invested)"""
        # Get latest ranking date
        latest = db.session.query(db.func.max(RankingModel.ranking_date)).scalar()
        if not latest:
            return []
        
        # Get invested symbols
        invested_symbols = {i.tradingsymbol for i in InvestedModel.query.all()}
        
        # Get top 20 from ranking
        rankings = RankingModel.query.filter(
            RankingModel.ranking_date == latest
        ).order_by(
            RankingModel.composite_score.desc()
        ).limit(20).all()
        
        result = []
        for i, r in enumerate(rankings, 1):
            result.append({
                'tradingsymbol': r.tradingsymbol,
                'composite_score': r.composite_score,
                'rank_position': i,
                'is_invested': r.tradingsymbol in invested_symbols,
                'ranking_date': r.ranking_date
            })
        
        return result


@blp.route("/ranking")
class RankingList(MethodView):
    @blp.arguments(RankingSchema(many=True))
    @blp.response(201, {"message": str})
    def post(self, ranking_data):
        """Bulk insert ranking data"""
        try:
            db.session.bulk_insert_mappings(RankingModel, ranking_data)
            db.session.commit()
            return {"message": f"Inserted {len(ranking_data)} ranking records"}
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))


# ==================== ACTIONS ====================

@blp.route("/actions")
class ActionsList(MethodView):
    @blp.response(200, ActionsSchema(many=True))
    def get(self):
        """Get all pending actions"""
        return ActionsModel.query.filter_by(executed=False).order_by(
            ActionsModel.action_date.desc()
        ).all()


@blp.route("/actions/generate")
class GenerateActions(MethodView):
    @blp.arguments(GenerateActionsInputSchema, location="json")
    @blp.response(201, ActionsSchema(many=True))
    def post(self, input_data):
        """Generate trade actions based on current rankings and portfolio"""
        ranking_date = input_data.get('ranking_date') or date.today()
        
        # Get risk config
        config = RiskConfigModel.query.first()
        if not config:
            abort(400, message="Risk config not set up. POST to /risk_config first.")
        
        # Get rankings
        rankings = RankingModel.query.filter(
            RankingModel.ranking_date == ranking_date
        ).order_by(RankingModel.composite_score.desc()).all()
        
        if not rankings:
            abort(404, message=f"No rankings found for {ranking_date}")
        
        # Get invested stocks
        invested = InvestedModel.query.all()
        invested_list = [
            {
                'tradingsymbol': i.tradingsymbol,
                'buy_price': i.buy_price,
                'num_shares': i.num_shares,
                'initial_stop_loss': i.initial_stop_loss,
                'current_stop_loss': i.current_stop_loss
            }
            for i in invested
        ]
        
        # Fetch current prices and ATRs
        current_prices = {}
        current_atrs = {}
        
        symbols = [r.tradingsymbol for r in rankings]
        for symbol in symbols:
            try:
                # Get price
                price_resp = requests.get(f"{BASE_URL}/market_data/latest/{symbol}")
                if price_resp.status_code == 200:
                    price_data = price_resp.json()
                    current_prices[symbol] = price_data.get('close', 0)
                
                # Get ATR
                ind_resp = requests.get(f"{BASE_URL}/indicators/latest/{symbol}")
                if ind_resp.status_code == 200:
                    ind_data = ind_resp.json()
                    current_atrs[symbol] = ind_data.get('atrr_14', 0)
            except Exception:
                continue
        
        # Build ranking DataFrame
        import pandas as pd
        ranked_df = pd.DataFrame([
            {'symbol': r.tradingsymbol, 'composite_score': r.composite_score}
            for r in rankings
        ])
        
        # Initialize portfolio service
        service = PortfolioService({
            'buffer_percent': config.buffer_percent,
            'exit_threshold': config.exit_threshold,
            'stop_loss_multiplier': config.stop_loss_multiplier,
            'risk_per_trade': config.risk_per_trade,
            'max_positions': config.max_positions,
            'current_capital': config.current_capital
        })
        
        # Generate actions
        actions = service.generate_actions(
            ranked_stocks=ranked_df,
            invested_stocks=invested_list,
            current_prices=current_prices,
            current_atrs=current_atrs,
            action_date=ranking_date
        )
        
        # Save actions to DB with amount and buy range
        action_records = []
        for action in actions:
            expected_price = action.get('expected_price', 0)
            units = action.get('units', 0)
            
            # Calculate amount
            action['amount'] = round(units * expected_price, 2) if expected_price else None
            
            # Calculate buy range (don't buy if gap up >2% or gap down >3%)
            if action.get('action_type') == 'BUY':
                action['buy_price_min'] = round(expected_price * 0.97, 2) if expected_price else None  # -3%
                action['buy_price_max'] = round(expected_price * 1.02, 2) if expected_price else None  # +2%
            
            action_model = ActionsModel(**action)
            db.session.add(action_model)
            action_records.append(action_model)
        
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        
        return action_records


@blp.route("/actions/<int:action_id>/execute")
class ExecuteAction(MethodView):
    @blp.response(200, ActionsSchema)
    def post(self, action_id):
        """Mark an action as executed and update capital"""
        action = ActionsModel.query.get(action_id)
        if not action:
            abort(404, message="Action not found")
        
        if action.executed:
            abort(400, message="Action already executed")
        
        config = RiskConfigModel.query.first()
        
        # Update capital based on action type
        if action.action_type == 'BUY':
            trade_value = action.units * action.expected_price
            config.current_capital -= trade_value
            
            # Add to invested
            invested = InvestedModel(
                tradingsymbol=action.tradingsymbol,
                buy_price=action.expected_price,
                num_shares=action.units,
                buy_date=action.action_date,
                initial_stop_loss=action.expected_price * 0.94,  # Temporary
                current_stop_loss=action.expected_price * 0.94
            )
            db.session.add(invested)
            
        elif action.action_type == 'SELL':
            trade_value = action.units * action.expected_price
            config.current_capital += trade_value
            
            # Remove from invested
            invested = InvestedModel.query.filter_by(tradingsymbol=action.tradingsymbol).first()
            if invested:
                db.session.delete(invested)
                
        elif action.action_type == 'SWAP':
            # Sell old
            sell_value = action.swap_from_units * action.swap_from_price
            config.current_capital += sell_value
            
            # Remove old invested
            old_invested = InvestedModel.query.filter_by(tradingsymbol=action.swap_from_symbol).first()
            if old_invested:
                db.session.delete(old_invested)
            
            # Buy new
            buy_value = action.units * action.expected_price
            config.current_capital -= buy_value
            
            # Add new invested
            new_invested = InvestedModel(
                tradingsymbol=action.tradingsymbol,
                buy_price=action.expected_price,
                num_shares=action.units,
                buy_date=action.action_date,
                initial_stop_loss=action.expected_price * 0.94,
                current_stop_loss=action.expected_price * 0.94
            )
            db.session.add(new_invested)
        
        action.executed = True
        action.status = 'INVESTED'
        action.executed_at = db.func.now()
        
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            abort(500, message=str(e))
        
        return action
