

    def update_capital_after_trade(
        self,
        action_type: str,
        trade_value: float,
        gain_loss: float = 0
    ) -> float:
        """
        Update capital after executing a trade.
        
        Args:
            action_type: BUY, SELL, or SWAP
            trade_value: Value of the trade
            gain_loss: Profit or loss (for SELL)
            
        Returns:
            New capital value
        """
        if action_type == 'BUY':
            self.current_capital -= trade_value
        elif action_type == 'SELL':
            self.current_capital += trade_value
        
        return self.current_capital

"""
ATR-Based Position Sizing (Volatility Sizing)

Ensures equal risk per position regardless of stock volatility.
Formula: Shares = Risk_Amount / (ATR × Stop_Multiplier)
"""





    def calculate_capital_allocation(
        total_capital: float,
        num_positions: int,
        risk_per_trade: float,
        stocks: list
    ) -> list:
        """
        Allocate capital across multiple stocks based on their volatility.
        
        Args:
            total_capital: Total available capital
            num_positions: Target number of positions
            risk_per_trade: Risk per position
            stocks: List of dicts with 'symbol', 'price', 'atr'
        
        Returns:
            List of allocations with shares and position values
        """
        allocations = []
        remaining_capital = total_capital
        
        for stock in stocks[:num_positions]:
            if remaining_capital <= 0:
                break
                
            sizing = calculate_position_size(
                risk_per_trade=risk_per_trade,
                atr=stock.get('atr', 0),
                current_price=stock.get('price', 0),
                max_position_value=remaining_capital
            )
            
            if sizing['shares'] > 0:
                allocation = {
                    'symbol': stock['symbol'],
                    'shares': sizing['shares'],
                    'price': stock.get('price', 0),
                    'position_value': sizing['position_value'],
                    'risk_amount': sizing['risk_amount']
                }
                allocations.append(allocation)
                remaining_capital -= sizing['position_value']
        
        return allocations


    def rebalance_on_sale(
        current_capital: float,
        sale_proceeds: float,
        gain_loss: float
    ) -> dict:
        """
        Update capital after selling a position.
        
        Args:
            current_capital: Current available capital
            sale_proceeds: Proceeds from sale (shares × sale_price)
            gain_loss: Profit or loss from the trade
        
        Returns:
            Dict with new capital and stats
        """
        new_capital = current_capital + sale_proceeds
        
        return {
            "previous_capital": round(current_capital, 2),
            "sale_proceeds": round(sale_proceeds, 2),
            "gain_loss": round(gain_loss, 2),
            "new_capital": round(new_capital, 2)
        }







    def _calculate_entry_position(self, symbol: str, price: float, atr: float) -> dict:
        """
        Calculate position size and stop-loss for a new entry.
        """

        sizing = calculate_position_size(
            atr=atr,
            stop_multiplier=self.stop_multiplier,
            risk_per_trade=self.risk_per_trade,
            current_price=price,
            max_position_value=self.current_capital
        )

        # Calculate initial stop-loss
        initial_stop = calculate_initial_stop_loss(
            buy_price=price,
            atr=atr
        )

        return {
            'tradingsymbol': symbol,
            'buy_price': price,
            'num_shares': sizing['shares'],
            'atr_at_entry': atr,
            'initial_stop_loss': round(initial_stop, 2),
            'current_stop_loss': round(initial_stop, 2),
            'position_value': sizing['position_value'],
            'risk_amount': sizing['risk_amount']
        }
