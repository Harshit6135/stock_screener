import pandas as pd

class Ranker:
    def rank_stocks(self, results):
        df = pd.DataFrame(results)
        
        # Calculate momentum score
        df['momentum_score'] = (df['RSI'] + df['ROC']) / 2
        
        # Sort by momentum score
        ranked_df = df.sort_values(by='momentum_score', ascending=False)
        
        # Get top 5
        top_5 = ranked_df.head(5)
        
        return top_5
