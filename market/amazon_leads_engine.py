import os
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

import requests


AMAZON = 0
NEW = 1
SALES = 3
BUY_BOX_SHIPPING = 18
TOYS_ROOT = 165793011


@dataclass
class Lead:
    asin: str
    title: str
    brand: str
    lane: str
    amazon_price: float | None
    exit_price: float | None
    profit: float | None
    roi: float | None
    rank: int | None
    monthly_sold: int | None
    drops30: int | None
    sellers: int | None
    amazon_oos90: int | None
    score: int
    reason: str
    methods: str

    @property
    def amazon_url(self):
        return f"https://www.amazon.com/dp/{self.asin}"

    @property
    def keepa_url(self):
        return f"https://keepa.com/#!product/1-{self.asin}"

    @property
    def chart_url(self):
        return f"https://graph.keepa.com/pricehistory.png?asin={self.asin}&domain=com&range=365&width=1000&height=500"


class AmazonLeadsEngine:
    """Find Amazon-retail hold opportunities with conservative, auditable math."""

    API = "https://api.keepa.com"
    BRANDS = {
        "barbie", "crayola", "disney", "fisher-price", "funko", "hasbro",
        "hot wheels", "jazwares", "just play", "lego", "loungefly", "mattel",
        "mcfarlane toys", "mga entertainment", "moose toys", "neca", "nerf",
        "play-doh", "pokemon", "ravensburger", "spin master", "star wars",
    }
    BLOCKED = ("generic", "unbranded", "bundle", "bulk", "wholesale", "custom")

    def __init__(self):
        self.key = os.getenv("KEEPA_API_KEY", "").strip()
        self.timeout = int(os.getenv("KEEPA_TIMEOUT_SECONDS", "25"))
        self.max_products = int(os.getenv("AMAZON_LEADS_MAX_PRODUCTS", "20"))
        self.min_profit = float(os.getenv("AMAZON_LEADS_MIN_PROFIT", "10"))
        self.min_roi = float(os.getenv("AMAZON_LEADS_MIN_ROI", "20"))
        self.max_roi = float(os.getenv("AMAZON_LEADS_MAX_ROI", "100"))
        self.referral_rate = float(os.getenv("AMAZON_LEADS_REFERRAL_RATE", ".15"))
        self.fba_fee = float(os.getenv("AMAZON_LEADS_EST_FBA_FEE", "4.50"))

    def scan(self):
        if not self.key:
            raise RuntimeError("KEEPA_API_KEY is missing")
        discovered = {}
        strategies = (
            ("30-day rank + stock cycling", self._selection("30")),
            ("90-day rank + stock cycling", self._selection("90")),
            ("180-day sustained demand", self._selection("180")),
            ("Amazon currently OOS", self._selection("oos")),
        )
        for label, selection in strategies:
            payload = self._get("/query", selection=selection)
            for asin in payload.get("asinList") or []:
                discovered.setdefault(asin, []).append(label)

        asins = list(discovered)[: self.max_products]
        if not asins:
            return []
        products = self._get(
            "/product", asin=",".join(asins), stats=180, history=0, buybox=1,
        ).get("products") or []
        leads = []
        for product in products:
            product["_lead_methods"] = discovered.get(product.get("asin"), [])
            lead = self._evaluate(product)
            if lead:
                leads.append(lead)
        return sorted(leads, key=lambda x: (x.score, x.roi or 0, x.monthly_sold or 0), reverse=True)

    def _selection(self, window):
        # Product Finder requires perPage >= 50. We request a valid page, then
        # cap product-detail calls separately with AMAZON_LEADS_MAX_PRODUCTS.
        selection = {
            "page": 0,
            "perPage": 50,
            "productType": [0],
            "rootCategory": [str(TOYS_ROOT)],
            "current_COUNT_NEW_gte": 2,
            "current_COUNT_NEW_lte": 20,
            "monthlySold_gte": 20,
        }
        if window == "30":
            selection.update({
                "current_SALES_lte": 175000,
                "salesRankDrops30_gte": 5,
                "outOfStockCountAmazon30_gte": 1,
                "sort": [["salesRankDrops30", "desc"]],
            })
        elif window == "90":
            selection.update({
                "avg90_SALES_lte": 175000,
                "salesRankDrops90_gte": 15,
                "outOfStockCountAmazon90_gte": 1,
                "sort": [["salesRankDrops90", "desc"]],
            })
        elif window == "180":
            selection.update({
                "avg180_SALES_lte": 200000,
                "salesRankDrops180_gte": 25,
                "buyBoxStatsAmazon180_lte": 40,
                "sort": [["salesRankDrops180", "desc"]],
            })
        else:
            selection.update({
                "current_AMAZON_lte": -1,
                "current_SALES_lte": 200000,
                "salesRankDrops30_gte": 5,
                "sort": [["monthlySold", "desc"]],
            })
        return selection

    def _evaluate(self, p):
        brand = str(p.get("brand") or "").strip()
        title = str(p.get("title") or "Untitled product").strip()
        haystack = f"{brand} {title}".lower()
        if not any(b in haystack for b in self.BRANDS) or any(b in haystack for b in self.BLOCKED):
            return None
        stats = p.get("stats") or {}
        current = stats.get("current") or []
        avg90 = stats.get("avg90") or []
        avg180 = stats.get("avg180") or []
        amazon = self._price(self._at(current, AMAZON))
        exits = [self._price(self._at(a, BUY_BOX_SHIPPING)) for a in (avg90, avg180)]
        exits = [x for x in exits if x]
        exit_price = round(median(exits), 2) if exits else self._price(self._at(current, BUY_BOX_SHIPPING))
        historic_buy = self._price(self._at(avg90, AMAZON)) or self._price(self._at(avg180, AMAZON))
        buy = amazon or historic_buy
        profit = roi = None
        if buy and exit_price and exit_price > buy:
            profit = round(exit_price * (1 - self.referral_rate) - self.fba_fee - buy, 2)
            roi = round(profit / buy * 100, 1)
        rank = self._positive(self._at(current, SALES))
        sellers = self._positive(self._at(current, NEW))
        monthly = self._positive(p.get("monthlySold"))
        drops = self._positive(stats.get("salesRankDrops30"))
        oos90 = self._positive((stats.get("outOfStockPercentage90") or [None])[AMAZON])
        qualifies = profit is not None and profit >= self.min_profit and roi is not None and self.min_roi <= roi <= self.max_roi
        if amazon and qualifies:
            lane, reason = "hold", "Amazon is in stock; modeled exit meets the hold thresholds."
        elif not amazon and (monthly or 0) >= 50:
            lane, reason = "pressure", "Amazon is out of stock; watch for an Amazon restock at or below the max buy."
        else:
            lane, reason = "review", "Demand/stock pressure is promising, but price history needs manual review."
        score = min(100, (25 if not amazon else 15) + min(monthly or 0, 200) // 5 + min(drops or 0, 30) + (20 if qualifies else 0))
        return Lead(str(p.get("asin")), title[:250], brand or "Known licensed brand", lane, amazon, exit_price, profit, roi, rank, monthly, drops, sellers, oos90, score, reason, ", ".join(p.get("_lead_methods") or ["Keepa discovery"]))

    def max_buy_price(self, lead):
        if not lead.exit_price:
            return None
        return round((lead.exit_price * (1 - self.referral_rate) - self.fba_fee) / (1 + self.min_roi / 100), 2)

    def _get(self, path, **params):
        params["key"] = self.key
        params["domain"] = 1
        if "selection" in params:
            import json
            params["selection"] = json.dumps(params["selection"], separators=(",", ":"))
        response = requests.get(self.API + path, params=params, timeout=self.timeout)
        if not response.ok:
            detail = response.text.strip()[:500]
            raise RuntimeError(f"Keepa HTTP {response.status_code}: {detail or 'request rejected'}")
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"Keepa: {data['error']}")
        return data

    @staticmethod
    def _at(values, index):
        return values[index] if isinstance(values, list) and len(values) > index else None

    @staticmethod
    def _price(value):
        return round(value / 100, 2) if isinstance(value, (int, float)) and value > 0 else None

    @staticmethod
    def _positive(value):
        return int(value) if isinstance(value, (int, float)) and value >= 0 else None

