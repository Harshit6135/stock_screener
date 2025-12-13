



def orchestrator():

    # Step 1
    # Get all the instrumets via get_instruments api

    # Step 2
    # Run for loop for all the tickers
    # Get last updated market data  for each ticker and get values from last updated date till today
    # put it database via post call in market data

    # Step 3
    # in same loop of above check last updated date for indicator and get data from 200 days before that day to max of (last_Updated_indicator, last_updated_price), and
    # combine it will data extracted above and then calculate indicators for missing days,
    # add values of indicators via post indicator table
