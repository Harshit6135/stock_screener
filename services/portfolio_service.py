def evaluate_challenger_vs_incumbent(self,
                                        incumbent_score: float,
                                        challenger_score: float,
                                        buffer: float = 0.25) -> Tuple[bool, str]:
        """
        Hysteresis loop for portfolio rotation
        
        Args:
            incumbent_score: Score of currently held stock
            challenger_score: Score of new candidate
            buffer: Switching threshold (default 25%)
            
        Returns:
            (should_switch, reason)
        """
        threshold = incumbent_score * (1 + buffer)
        
        if challenger_score > threshold:
            return (True, 
                   f"Switch: Challenger ({challenger_score:.2f}) exceeds "
                   f"threshold ({threshold:.2f})")
        else:
            return (False, 
                   f"Hold: Challenger ({challenger_score:.2f}) below "
                   f"threshold ({threshold:.2f})")
    
    def check_degradation_exit(self, score: float, 
                              threshold: float = 50.0) -> Tuple[bool, str]:
        """
        Check if stock should be exited due to degradation
        
        Args:
            score: Current composite score
            threshold: Minimum acceptable score
            
        Returns:
            (should_exit, reason)
        """
        if score < threshold:
            return (True, 
                   f"Exit: Score ({score:.2f}) below threshold ({threshold})")
        return (False, f"Hold: Score ({score:.2f}) acceptable")
    
    def calculate_atr_position_size(self,
                                   total_capital: float,
                                   risk_per_trade: float,
                                   atr: float,
                                   current_price: float,
                                   stop_multiplier: float = 2.0) -> int:
        """
        Calculate ATR-based position size for equal risk allocation
        
        Args:
            total_capital: Total available capital
            risk_per_trade: Risk percentage per trade (e.g., 0.02 for 2%)
            atr: Current ATR value
            current_price: Current stock price
            stop_multiplier: ATR multiplier for stop loss
            
        Returns:
            Number of shares to buy
        """
        risk_amount = total_capital * risk_per_trade
        risk_per_share = atr * stop_multiplier
        shares = int(risk_amount / risk_per_share)
        
        return max(1, shares)  # Minimum 1 share


        def evaluate_challenger_vs_incumbent(self,
                                        incumbent_score: float,
                                        challenger_score: float,
                                        buffer: float = 0.25) -> Tuple[bool, str]:
        """
        Hysteresis loop for portfolio rotation
        
        Args:
            incumbent_score: Score of currently held stock
            challenger_score: Score of new candidate
            buffer: Switching threshold (default 25%)
            
        Returns:
            (should_switch, reason)
        """
        threshold = incumbent_score * (1 + buffer)
        
        if challenger_score > threshold:
            return (True, 
                   f"Switch: Challenger ({challenger_score:.2f}) exceeds "
                   f"threshold ({threshold:.2f})")
        else:
            return (False, 
                   f"Hold: Challenger ({challenger_score:.2f}) below "
                   f"threshold ({threshold:.2f})")
    
    def check_degradation_exit(self, score: float, 
                              threshold: float = 50.0) -> Tuple[bool, str]:
        """
        Check if stock should be exited due to degradation
        
        Args:
            score: Current composite score
            threshold: Minimum acceptable score
            
        Returns:
            (should_exit, reason)
        """
        if score < threshold:
            return (True, 
                   f"Exit: Score ({score:.2f}) below threshold ({threshold})")
        return (False, f"Hold: Score ({score:.2f}) acceptable")
    
    def calculate_atr_position_size(self,
                                   df: pd.DataFrame,
                                   total_capital: float,
                                   risk_per_trade: float,
                                   current_price: float,
                                   atr_period: int = 14,
                                   stop_multiplier: float = 2.0) -> int:
        """
        Calculate ATR-based position size for equal risk allocation
        
        Args:
            df: DataFrame with OHLC data
            total_capital: Total available capital
            risk_per_trade: Risk percentage per trade (e.g., 0.02 for 2%)
            current_price: Current stock price
            atr_period: ATR calculation period
            stop_multiplier: ATR multiplier for stop loss
            
        Returns:
            Number of shares to buy
        """
        atr = ta.atr(df['high'], df['low'], df['close'], length=atr_period)
        current_atr = atr.iloc[-1]
        
        risk_amount = total_capital * risk_per_trade
        risk_per_share = current_atr * stop_multiplier
        shares = int(risk_amount / risk_per_share)
        
        return max(1, shares)  # Minimum 1 share


# ==========================================
# 3. PORTFOLIO DECISION ENGINE
# ==========================================
def calculate_position_size(capital, risk_per_trade, atr, close):
    """Calculate position size using ATR-based volatility sizing"""
    stop_loss_dist = 2 * atr  # 2 ATR stop loss
    risk_amount = capital * risk_per_trade
    shares = risk_amount / stop_loss_dist
    return int(shares), round(close - stop_loss_dist, 2)

def get_recommendation(scorecard, current_holdings):
    """
    Portfolio management logic with hysteresis buffer
    Returns recommendations for each holding
    """
    if len(scorecard) == 0:
        return pd.DataFrame()
    
    actions = []
    
    # Get top available challengers
    available_challengers = scorecard[~scorecard.index.isin(current_holdings)]
    
    if len(available_challengers) > 0:
        best_challenger = available_challengers.iloc[0]
        challenger_name = best_challenger.name
        challenger_score = best_challenger['Final_Score']
        print(f"\n🎯 Top Challenger: {challenger_name} (Score: {challenger_score:.2f})")
    else:
        challenger_name = None
        challenger_score = 0
    
    # Evaluate each current holding
    for stock in current_holdings:
        if stock not in scorecard.index:
            actions.append({
                'Stock': stock,
                'Current_Score': 0,
                'Action': '❌ SELL',
                'Reason': 'No valid data available',
                'Rec_Stop_Loss': 'N/A',
                'Rec_Position_Size': 0
            })
            continue
        
        current_score = scorecard.loc[stock, 'Final_Score']
        atr = scorecard.loc[stock, 'ATR_14']
        close = scorecard.loc[stock, 'Close']
        
        # Calculate required threshold for switching
        required_score = current_score * (1 + CONFIG['Switch_Buffer'])
        
        # Decision logic
        if current_score < CONFIG['Degradation_Threshold']:
            action = '🔴 EXIT'
            reason = f"Score degraded below {CONFIG['Degradation_Threshold']} (Current: {current_score:.1f})"
        elif challenger_name and challenger_score > required_score:
            action = '🔄 SWITCH'
            reason = f"Replace with {challenger_name} ({challenger_score:.1f}) >> Current ({current_score:.1f})"
        else:
            action = '✅ HOLD'
            reason = f"Score {current_score:.1f} is strong. Buffer protects from switch."
        
        # Calculate position sizing
        shares, stop_loss = calculate_position_size(
            CONFIG['Capital'], 
            CONFIG['Risk_Per_Trade'],
            atr,
            close
        )
        
        actions.append({
            'Stock': stock,
            'Current_Score': round(current_score, 2),
            'Action': action,
            'Reason': reason,
            'Rec_Stop_Loss': stop_loss,
            'Rec_Position_Size': shares
        })
    
    return pd.DataFrame(actions)


# ==========================================
# 3. PORTFOLIO DECISION ENGINE
# ==========================================
def calculate_position_size(capital, risk_per_trade, atr, close):
    """Calculate position size using ATR-based volatility sizing"""
    stop_loss_dist = 2 * atr  # 2 ATR stop loss
    risk_amount = capital * risk_per_trade
    shares = risk_amount / stop_loss_dist
    return int(shares), round(close - stop_loss_dist, 2)

def get_recommendation(scorecard, current_holdings):
    """
    Portfolio management logic with hysteresis buffer
    Returns recommendations for each holding
    """
    if len(scorecard) == 0:
        return pd.DataFrame()
    
    actions = []
    
    # Get top available challengers
    available_challengers = scorecard[~scorecard.index.isin(current_holdings)]
    
    if len(available_challengers) > 0:
        best_challenger = available_challengers.iloc[0]
        challenger_name = best_challenger.name
        challenger_score = best_challenger['Final_Score']
        print(f"\n🎯 Top Challenger: {challenger_name} (Score: {challenger_score:.2f})")
    else:
        challenger_name = None
        challenger_score = 0
    
    # Evaluate each current holding
    for stock in current_holdings:
        if stock not in scorecard.index:
            actions.append({
                'Stock': stock,
                'Current_Score': 0,
                'Action': '❌ SELL',
                'Reason': 'No valid data available',
                'Rec_Stop_Loss': 'N/A',
                'Rec_Position_Size': 0
            })
            continue
        
        current_score = scorecard.loc[stock, 'Final_Score']
        atr = scorecard.loc[stock, 'ATR_14']
        close = scorecard.loc[stock, 'Close']
        
        # Calculate required threshold for switching
        required_score = current_score * (1 + CONFIG['Switch_Buffer'])
        
        # Decision logic
        if current_score < CONFIG['Degradation_Threshold']:
            action = '🔴 EXIT'
            reason = f"Score degraded below {CONFIG['Degradation_Threshold']} (Current: {current_score:.1f})"
        elif challenger_name and challenger_score > required_score:
            action = '🔄 SWITCH'
            reason = f"Replace with {challenger_name} ({challenger_score:.1f}) >> Current ({current_score:.1f})"
        else:
            action = '✅ HOLD'
            reason = f"Score {current_score:.1f} is strong. Buffer protects from switch."
        
        # Calculate position sizing
        shares, stop_loss = calculate_position_size(
            CONFIG['Capital'], 
            CONFIG['Risk_Per_Trade'],
            atr,
            close
        )
        
        actions.append({
            'Stock': stock,
            'Current_Score': round(current_score, 2),
            'Action': action,
            'Reason': reason,
            'Rec_Stop_Loss': stop_loss,
            'Rec_Position_Size': shares
        })
    
    return pd.DataFrame(actions)