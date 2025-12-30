from datetime import date, timedelta
import requests
import pandas as pd
import os
import sys

# Add the project root to sys.path to allow importing from config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Strategy1Parameters

base_url = "http://127.0.0.1:5000"
start_date = date(2010, 1, 1)
end_date = date(2025, 12, 26)
export_dir = "data/exports"

# Create export directory if it doesn't exist
os.makedirs(export_dir, exist_ok=True)

# Initialize strategy parameters
params = Strategy1Parameters()

current_date = start_date
while current_date <= end_date:
    date_str = current_date.strftime("%Y-%m-%d")
    print(f"Processing for {date_str}...")
    
    # Fetch rankings from API
    try:
        response = requests.get(f"{base_url}/api/v1/ranking/query/{date_str}")
        
        if response.status_code == 200:
            rankings = response.json()
            if rankings:
                df = pd.DataFrame(rankings)
                
                # Calculate component scores
                df['final_trend_score'] = (
                    df['trend_rank'].fillna(0) * params.trend_rank_weight +
                    df['trend_extension_rank'].fillna(0) * params.trend_extension_rank_weight +
                    df['trend_start_rank'].fillna(0) * params.trend_start_rank_weight
                )
                
                df['final_momentum_score'] = (
                    df['momentum_rsi_rank'].fillna(0) * params.momentum_rsi_rank_weight +
                    df['momentum_ppo_rank'].fillna(0) * params.momentum_ppo_rank_weight +
                    df['momentum_ppoh_rank'].fillna(0) * params.momentum_ppoh_rank_weight
                )
                
                df['final_vol_score'] = (
                    df['rvolume_rank'].fillna(0) * params.rvolume_rank_weight +
                    df['price_vol_corr_rank'].fillna(0) * params.price_vol_corr_rank_weight
                )
                
                df['final_structure_score'] = (
                    df['structure_rank'].fillna(0) * params.structure_rank_weight +
                    df['structure_bb_rank'].fillna(0) * params.structure_bb_rank_weight
                )
                
                # Calculate composite score
                df['composite_score'] = (
                    params.trend_strength_weight * df['final_trend_score'] +
                    params.momentum_velocity_weight * df['final_momentum_score'] +
                    params.risk_efficiency_weight * df['efficiency_rank'].fillna(0) +
                    params.conviction_weight * df['final_vol_score'] +
                    params.structure_weight * df['final_structure_score']
                )
                
                # Sort by composite score
                df = df.sort_values('composite_score', ascending=False)
                
                # Save to CSV
                export_path = os.path.join(export_dir, f"ranking_{date_str}.csv")
                df.to_csv(export_path, index=False)
                print(f"  Saved {len(df)} records to {export_path}")
            else:
                print(f"  No rankings found for {date_str}")
        else:
            print(f"  Error fetching data for {date_str}: {response.status_code}")
    except Exception as e:
        print(f"  Exception for {date_str}: {e}")

    current_date += timedelta(days=1)

print("All Processing Completed")