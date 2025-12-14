
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from router.ranking_router import calculate_score

class TestRankingRouter(unittest.TestCase):

    @patch('router.ranking_router.requests.get')
    def test_calculate_score(self, mock_get):
        # Mock responses
        mock_instruments_resp = MagicMock()
        mock_instruments_resp.status_code = 200
        mock_instruments_resp.json.return_value = [
            {'tradingsymbol': 'INFY', 'instrument_token': 123},
            {'tradingsymbol': 'TCS', 'instrument_token': 456}
        ]
        
        mock_price_resp = MagicMock()
        mock_price_resp.status_code = 200
        # return dummy price data
        mock_price_resp.json.return_value = {
            'tradingsymbol': 'INFY', 'close': 1500, 'volume': 100000
        }
        
        mock_indicators_resp = MagicMock()
        mock_indicators_resp.status_code = 200
        # return dummy indicators
        mock_indicators_resp.json.return_value = {
            'tradingsymbol': 'INFY', 
            'ema_50_slope': 0.05,
            'ppo_12_26_9': 1.2,
            'ppoh_12_26_9': 1.1,
            'risk_adj_return': 2.0,
            'rvol': 1.5,
            'price_vol_corr': 0.3,
            'bbb_20_2_2': 0.1,
            'rsi_14': 60,
            'distance_from_ema_200': 0.05,
            'percent_b': 0.8
        }

        # Side effect for requests.get
        def side_effect(url):
            if '/instruments' in url:
                return mock_instruments_resp
            elif '/market_data/latest' in url:
                return mock_price_resp
            elif '/indicators/latest' in url:
                return mock_indicators_resp
            return MagicMock(status_code=404)

        mock_get.side_effect = side_effect

        # Run the function
        result_df = calculate_score()

        # Assertions
        self.assertIsNotNone(result_df)
        self.assertFalse(result_df.empty)
        self.assertIn('composite_score', result_df.columns)
        self.assertTrue(len(result_df) > 0)
        
        print("\nTest Result Head:")
        print(result_df.head())

if __name__ == '__main__':
    unittest.main()
