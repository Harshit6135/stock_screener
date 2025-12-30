from datetime import date, timedelta
import pandas as pd
import os
import glob

# Configuration
start_date = date(2010, 1, 1)
end_date = date(2025, 12, 26)
export_dir = "data/exports"
output_file = os.path.join(export_dir, "weekly_composite_scores.csv")

def get_monday(d):
    """Find the date of the Monday in the same week as the given date (or the date itself if it is a Monday)."""
    return d - timedelta(days=d.weekday())

# Find the first Monday >= start_date
current_monday = get_monday(start_date)
if current_monday < start_date:
    current_monday += timedelta(days=7)

weekly_results = []

print(f"Starting weekly aggregation from {current_monday} up to {end_date}...")

while current_monday <= end_date:
    monday_str = current_monday.strftime("%Y-%m-%d")
    
    # Previous week range: [Monday - 7, Monday - 1]
    prev_week_start = current_monday - timedelta(days=7)
    prev_week_end = current_monday - timedelta(days=1)
    
    # Gather all daily files in this range
    daily_dfs = []
    for i in range(7):
        day = prev_week_start + timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        file_path = os.path.join(export_dir, f"ranking_{day_str}.csv")
        
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                if 'tradingsymbol' in df.columns and 'composite_score' in df.columns:
                    daily_dfs.append(df[['tradingsymbol', 'composite_score']])
            except Exception as e:
                print(f"  Error reading {file_path}: {e}")
    
    if daily_dfs:
        # Combine all days for the previous week
        combined_df = pd.concat(daily_dfs)
        
        # Calculate average per symbol
        weekly_avg = combined_df.groupby('tradingsymbol')['composite_score'].mean().reset_index()
        
        # Add date column
        weekly_avg['date'] = monday_str
        
        # Sort by composite score descending
        weekly_avg = weekly_avg.sort_values('composite_score', ascending=False)
        
        # Reorder columns: date, tradingsymbol, composite_score
        weekly_avg = weekly_avg[['date', 'tradingsymbol', 'composite_score']]
        
        weekly_results.append(weekly_avg)
        print(f"  Processed weekly average for {monday_str} ({len(daily_dfs)} days of data)")
    else:
        print(f"  No data found for the week preceding {monday_str}")
    
    # Move to the next Monday
    current_monday += timedelta(days=7)

if weekly_results:
    final_df = pd.concat(weekly_results)
    final_df.to_csv(output_file, index=False)
    print(f"\nSuccessfully saved consolidated weekly scores to {output_file}")
    print(f"Total rows: {len(final_df)}")
else:
    print("\nNo data aggregated. Check if daily ranking files exist in data/exports/")

print("Weekly Aggregation Completed")