from providers.finnhub_provider import FinnhubProvider
from market.risk_engine import RiskEngine


class MarketService:

    def __init__(self):
        self.data = FinnhubProvider()
        self.risk = RiskEngine()

    def get_dashboard(self):

        # ----------------------------
        # Download Market Data
        # ----------------------------

        spy = self.data.get_quote("SPY")
        qqq = self.data.get_quote("QQQ")
        btc = self.data.get_quote("IBIT")

        # ----------------------------
        # Daily % Changes
        # ----------------------------

        es_change = spy["dp"]
        qqq_change = qqq["dp"]
        btc_change = btc["dp"]

        # Temporary placeholders until we connect them
        vix_change = -1
        oil_change = 0
        dxy_change = 0
        us10y_change = 0

        # ----------------------------
        # Ask the Risk Engine
        # ----------------------------

        risk = self.risk.calculate(
            es_change,
            qqq_change,
            vix_change,
            oil_change,
            btc_change,
            dxy_change,
            us10y_change
        )

        # ----------------------------
        # Build Dashboard
        # ----------------------------

        return {
            "risk": risk["mood"],
            "score": risk["score"],
            "reasons": risk["reasons"],

            "theme": "📈 Market Open",

            "es": f"{es_change:+.2f}%",
            "nq": f"{qqq_change:+.2f}%",
            "vix": "Loading...",
            "oil": "Loading...",
            "btc": f"{btc_change:+.2f}%",
            "dxy": "Loading...",
            "us10y": "Loading...",

            "leader": "Technology",
            "loser": "Unknown"
        }