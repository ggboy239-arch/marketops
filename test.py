from services.market_data import MarketData

market = MarketData()

print(
    market.get_quote("AAPL")
)