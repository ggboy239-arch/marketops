import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

import requests
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


AMAZON = 0
COUNT_NEW = 11
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
    history: dict

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
        "barbie", "disney", "fisher-price", "funko", "hasbro",
        "hot wheels", "jazwares", "just play", "lego", "loungefly", "mattel",
        "mcfarlane toys", "mga entertainment", "moose toys", "neca", "nerf",
        "play-doh", "pokemon", "ravensburger", "spin master", "star wars",
    }
    BLOCKED = ("generic", "unbranded", "bundle", "bulk", "wholesale", "custom")

    def __init__(self):
        self.key = os.getenv("KEEPA_API_KEY", "").strip()
        self.timeout = int(os.getenv("KEEPA_TIMEOUT_SECONDS", "25"))
        self.max_products = max(10, min(20, int(os.getenv("AMAZON_LEADS_MAX_PRODUCTS", "20"))))
        self._scan_number = 0
        self._candidate_cursor = 0
        self.last_scan_stats = {"discovered": 0, "products": 0, "qualified": 0}
        self.min_profit = float(os.getenv("AMAZON_LEADS_MIN_PROFIT", "10"))
        self.min_roi = float(os.getenv("AMAZON_LEADS_MIN_ROI", "20"))
        self.max_roi = float(os.getenv("AMAZON_LEADS_MAX_ROI", "100"))
        self.referral_rate = float(os.getenv("AMAZON_LEADS_REFERRAL_RATE", ".15"))
        self.fba_fee = float(os.getenv("AMAZON_LEADS_EST_FBA_FEE", "4.50"))

    def scan(self):
        if not self.key:
            raise RuntimeError("KEEPA_API_KEY is missing")
        discovered = {}
        pools = []
        rotating = (
            ("30-day rank + stock cycling", self._selection("30")),
            ("90-day rank + stock cycling", self._selection("90")),
            ("180-day sustained demand", self._selection("180")),
            ("Mattel / Barbie / Hot Wheels", self._selection("brands", ["Mattel", "Barbie", "Hot Wheels", "Fisher-Price"])),
            ("Other approved toy brands", self._selection("brands", ["Hasbro", "Jazwares", "Spin Master", "Funko", "Loungefly", "MGA Entertainment", "Moose Toys", "Just Play", "NECA", "McFarlane Toys", "Ravensburger"])),
        )
        # Every scan covers Amazon both in and out of stock. The final query
        # rotates time-window and brand methods to stay within the token budget.
        rotation = self._scan_number
        self._scan_number += 1
        strategies = (
            ("Amazon in stock + recent stock cycling", self._selection("instock")),
            ("Amazon currently OOS", self._selection("oos")),
            rotating[rotation % len(rotating)],
        )
        for label, selection in strategies:
            payload = self._get("/query", selection=selection)
            pool = payload.get("asinList") or []
            pools.append(pool)
            for asin in pool:
                discovered.setdefault(asin, []).append(label)

        # Round-robin across strategies so one dominant brand cannot consume
        # every product-detail slot.
        ordered_asins = []
        for index in range(50):
            for pool in pools:
                if index < len(pool) and pool[index] not in ordered_asins:
                    ordered_asins.append(pool[index])
        if not ordered_asins:
            self.last_scan_stats = {"discovered": len(discovered), "products": 0, "qualified": 0}
            return []

        # Advance through the entire discovered pool instead of repeatedly
        # analyzing the first batch. Wrap at the end for continuous monitoring.
        start = self._candidate_cursor % len(ordered_asins)
        asins = (ordered_asins + ordered_asins)[start:start + self.max_products]
        self._candidate_cursor = (start + len(asins)) % len(ordered_asins)
        products = self._get(
            "/product", asin=",".join(asins), stats=180, history=1, buybox=1,
        ).get("products") or []
        leads = []
        for product in products:
            product["_lead_methods"] = discovered.get(product.get("asin"), [])
            lead = self._evaluate(product)
            if lead:
                leads.append(lead)
        self.last_scan_stats = {"discovered": len(discovered), "products": len(products), "qualified": len(leads), "batch_start": start, "next_cursor": self._candidate_cursor}
        return self._diversified_sort(leads)

    def _selection(self, window, brands=None):
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
        if brands:
            selection["brand"] = brands
        if window == "30":
            selection.update({
                "current_SALES_gte": 50000,
                "current_SALES_lte": 250000,
                "salesRankDrops30_gte": 5,
                "outOfStockCountAmazon30_gte": 1,
                "sort": [["salesRankDrops30", "desc"]],
            })
        elif window == "90":
            selection.update({
                "avg90_SALES_gte": 50000,
                "avg90_SALES_lte": 250000,
                "salesRankDrops90_gte": 15,
                "outOfStockCountAmazon90_gte": 1,
                "sort": [["salesRankDrops90", "desc"]],
            })
        elif window == "180":
            selection.update({
                "avg180_SALES_gte": 50000,
                "avg180_SALES_lte": 250000,
                "salesRankDrops180_gte": 25,
                "buyBoxStatsAmazon180_lte": 40,
                "sort": [["salesRankDrops180", "desc"]],
            })
        elif window == "instock":
            selection.update({
                "current_AMAZON_gte": 1,
                "current_SALES_gte": 50000,
                "current_SALES_lte": 250000,
                "outOfStockCountAmazon90_gte": 1,
                "salesRankDrops30_gte": 3,
                "sort": [["salesRankDrops30", "desc"]],
            })
        elif window == "oos":
            selection.update({
                "current_AMAZON_lte": -1,
                "current_SALES_gte": 50000,
                "current_SALES_lte": 250000,
                "salesRankDrops30_gte": 5,
                "sort": [["monthlySold", "desc"]],
            })
        else:
            selection.update({
                "current_SALES_gte": 50000,
                "current_SALES_lte": 250000,
                "salesRankDrops30_gte": 3,
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
        oos_exit, history_buy = self._oos_prices(p.get("csv"))
        fallback_exits = [self._price(self._at(a, BUY_BOX_SHIPPING)) for a in (avg90, avg180)]
        fallback_exits = [x for x in fallback_exits if x]
        exit_price = oos_exit or (round(median(fallback_exits), 2) if fallback_exits else self._price(self._at(current, BUY_BOX_SHIPPING)))
        historic_buy = history_buy or self._price(self._at(avg90, AMAZON)) or self._price(self._at(avg180, AMAZON))
        buy = amazon or historic_buy
        profit = roi = None
        if buy and exit_price and exit_price > buy:
            profit = round(exit_price * (1 - self.referral_rate) - self.fba_fee - buy, 2)
            roi = round(profit / buy * 100, 1)
        rank = self._positive(self._at(current, SALES))
        sellers = self._positive(self._at(current, COUNT_NEW))
        monthly = self._positive(p.get("monthlySold"))
        drops = self._positive(stats.get("salesRankDrops30"))
        oos90 = self._positive((stats.get("outOfStockPercentage90") or [None])[AMAZON])
        qualifies = profit is not None and profit >= self.min_profit and roi is not None and self.min_roi <= roi <= self.max_roi
        if not qualifies:
            return None
        if amazon:
            lane, reason = "hold", "Amazon is in stock; modeled exit meets the profit and ROI thresholds."
        else:
            lane, reason = "pressure", "Amazon is out of stock; historical Amazon buy and modeled exit meet the profit and ROI thresholds."
        score = min(100, (25 if not amazon else 15) + min(monthly or 0, 200) // 5 + min(drops or 0, 30) + (20 if qualifies else 0))
        return Lead(str(p.get("asin")), title[:250], brand or "Known licensed brand", lane, amazon, exit_price, profit, roi, rank, monthly, drops, sellers, oos90, score, reason, ", ".join(p.get("_lead_methods") or ["Keepa discovery"]), self._history(p.get("csv")))

    def _oos_prices(self, csv):
        csv = csv or []
        amazon_raw = self._at(csv, AMAZON)
        box_raw = self._at(csv, BUY_BOX_SHIPPING)
        if not isinstance(amazon_raw, list) or not isinstance(box_raw, list):
            return None, None

        epoch = datetime(2011, 1, 1, tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)

        def events(raw):
            result = []
            for index in range(0, len(raw) - 1, 2):
                minute, value = raw[index], raw[index + 1]
                if isinstance(minute, (int, float)) and isinstance(value, (int, float)):
                    result.append((epoch + timedelta(minutes=minute), value))
            return result

        amazon_events = events(amazon_raw)
        box_events = events(box_raw)
        if not amazon_events or not box_events:
            return None, None

        amazon_index = box_index = 0
        amazon_state = box_state = -1
        in_stock_buys = []
        oos_boxes = []
        day = cutoff.replace(hour=23, minute=59, second=59, microsecond=0)
        now = datetime.now(timezone.utc)
        while day <= now:
            while amazon_index < len(amazon_events) and amazon_events[amazon_index][0] <= day:
                amazon_state = amazon_events[amazon_index][1]
                amazon_index += 1
            while box_index < len(box_events) and box_events[box_index][0] <= day:
                box_state = box_events[box_index][1]
                box_index += 1
            if amazon_state > 0:
                in_stock_buys.append(amazon_state / 100)
            elif box_state > 0:
                oos_boxes.append(box_state / 100)
            day += timedelta(days=1)

        exit_price = round(median(oos_boxes), 2) if oos_boxes else None
        buy_price = round(median(in_stock_buys), 2) if in_stock_buys else None
        return exit_price, buy_price

    def _diversified_sort(self, leads):
        ranked = sorted(leads, key=lambda x: (x.score, x.roi or 0, x.monthly_sold or 0), reverse=True)
        groups = {}
        for lead in ranked:
            key = lead.brand.lower().replace("the lego group", "lego")
            groups.setdefault(key, []).append(lead)
        mixed = []
        while groups:
            for key in list(groups):
                mixed.append(groups[key].pop(0))
                if not groups[key]:
                    del groups[key]
        return mixed

    def _history(self, csv):
        csv = csv or []
        return {
            "Amazon": self._series(self._at(csv, AMAZON), True),
            "New / Buy Box": self._series(self._at(csv, BUY_BOX_SHIPPING), True),
            "Sales Rank": self._series(self._at(csv, SALES), False),
        }

    def chart_png(self, lead):
        price_series = [lead.history.get("Amazon", []), lead.history.get("New / Buy Box", [])]
        if not any(price_series):
            return None
        figure = Figure(figsize=(10, 4.8), dpi=120, facecolor="#10151f")
        FigureCanvasAgg(figure)
        axis = figure.add_subplot(111)
        axis.set_facecolor("#10151f")
        colors = {"Amazon": "#ff9900", "New / Buy Box": "#ff3ea5"}
        for name in ("Amazon", "New / Buy Box"):
            points = lead.history.get(name, [])
            if points:
                axis.step([p[0] for p in points], [p[1] for p in points], where="post", label=name, color=colors[name], linewidth=1.7)
        axis.set_ylabel("Price ($)", color="white")
        axis.tick_params(colors="white")
        axis.grid(alpha=.18)
        axis.legend(facecolor="#182131", labelcolor="white")
        axis.set_title(f"{lead.brand} • {lead.asin} • 365-day Keepa history", color="white")
        rank = lead.history.get("Sales Rank", [])
        if rank:
            rank_axis = axis.twinx()
            rank_axis.plot([p[0] for p in rank], [p[1] for p in rank], color="#74c476", alpha=.45, linewidth=.8)
            rank_axis.set_ylabel("Sales rank", color="#74c476")
            rank_axis.tick_params(colors="#74c476")
            rank_axis.invert_yaxis()
        figure.autofmt_xdate()
        figure.tight_layout()
        import io
        output = io.BytesIO()
        figure.savefig(output, format="png", facecolor=figure.get_facecolor())
        return output.getvalue()

    @staticmethod
    def _series(values, price):
        if not isinstance(values, list):
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=365)
        epoch = datetime(2011, 1, 1, tzinfo=timezone.utc)
        points = []
        for index in range(0, len(values) - 1, 2):
            moment, value = values[index], values[index + 1]
            if not isinstance(moment, (int, float)) or not isinstance(value, (int, float)) or value < 0:
                continue
            when = epoch + timedelta(minutes=moment)
            if when >= cutoff:
                points.append((when, value / 100 if price else value))
        return points

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
            if response.status_code == 429:
                try:
                    info = response.json()
                    left = int(info.get("tokensLeft", 0))
                    rate = max(1, int(info.get("refillRate", 1)))
                    refill_ms = int(info.get("refillIn", 0))
                    wait_minutes = max(1, round(max(0, -left) / rate + refill_ms / 60000 + 0.5))
                    raise RuntimeError(
                        f"Keepa tokens are refilling. Retry in about {wait_minutes} minute(s); "
                        "the scanner will also try automatically on its next cycle."
                    )
                except RuntimeError:
                    raise
                except Exception:
                    pass
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

