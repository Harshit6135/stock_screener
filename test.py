import sys
sys.path.insert(0, 'src')
from run import app
from src.services.percentile_service import PercentileService

with app.app_context():
    try:
        PercentileService('strategy1').backfill_percentiles()
    except Exception as e:
        import traceback
        traceback.print_exc()
