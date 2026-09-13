import os
from datetime import datetime
from zoneinfo import ZoneInfo

from market.government_power_engine import GovernmentPowerEngine
from market.market_service import MarketService
from market.news_engine import NewsEngine


PT_ZONE = ZoneInfo("America/Los_Angeles")


class MarketChangeEngine:
    """Explain why the market may be changing.

    This combines live MarketOps market data, routed news, and optional federal
    power/policy records. It does not claim one headline caused a move unless the
    relationship is obvious; it teaches likely economic paths to verify next.
    """

    def __init__(self):
        self.market = MarketService()
        self.news = NewsEngine()
        self.gov_power = GovernmentPowerEngine()
        self.news_window_hours = float(os.getenv("MARKET_CHANGE_NEWS_LOOKBACK_HOURS", "6"))
        self.include_policy = self._env_bool("MARKET_CHANGE_INCLUDE_POLICY", True)
        self.significant_threshold = float(os.getenv("MARKET_CHANGE_THRESHOLD_PERCENT", "0.75"))
        self.last_policy_error = "None"

    def build_explainer(self, focus=None):
        focus = (focus or "market").strip().upper()
        dashboard = self.market.get_dashboard()
        changed_assets = self._changed_assets(dashboard)
        news_items = self._news_items()
        policy_items = self._policy_items() if self.include_policy else []

        possible_drivers = self._possible_drivers(dashboard, changed_assets, news_items, policy_items)
        economics = self._economics_translation(dashboard, changed_assets, policy_items)
        sectors = self._sector_paths(dashboard, changed_assets, policy_items)
        confirm = self._confirm_next(dashboard, changed_assets, sectors)
        confidence = self._confidence(changed_assets, news_items, policy_items)

        return {
            "focus": focus,
            "updated": self._timestamp(),
            "risk": dashboard.get("risk", "Unknown"),
            "score": dashboard.get("score", "Unknown"),
            "theme": dashboard.get("theme", "Live Market"),
            "leader": dashboard.get("leader", "Unknown"),
            "weakest": dashboard.get("loser", "Unknown"),
            "warning": dashboard.get("warning_signal", "Unknown"),
            "changed_assets": changed_assets,
            "possible_drivers": possible_drivers,
            "economics": economics,
            "sectors": sectors,
            "confirm": confirm,
            "confidence": confidence,
            "top_news": news_items[:5],
            "policy_items": policy_items[:3],
            "significant": self._is_significant(changed_assets),
            "signature": self._signature(changed_assets, dashboard),
            "policy_error": self.last_policy_error,
        }

    def _changed_assets(self, dashboard):
        raw = dashboard.get("raw", {})
        checks = [
            ("market", "S&P futures / SPY"),
            ("tech", "Nasdaq futures / QQQ"),
            ("fear", "VIX / fear"),
            ("oil", "oil"),
            ("gold", "gold"),
            ("dollar", "U.S. dollar"),
            ("rates", "10Y yield / rates"),
            ("bitcoin", "Bitcoin / crypto"),
        ]
        rows = []
        for key, label in checks:
            quote = raw.get(key, {})
            value = self._safe_float(quote.get("change_percent"))
            if value is None:
                continue
            status = quote.get("status", "Unknown")
            stale = bool(quote.get("stale"))
            threshold = self._asset_threshold(key)
            direction = "up" if value >= 0 else "down"
            importance = "major" if abs(value) >= threshold else "minor"
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "symbol": quote.get("symbol", key),
                    "change": value,
                    "direction": direction,
                    "importance": importance,
                    "status": status,
                    "stale": stale,
                    "line": f"{label}: {value:+.2f}% ({status}{', stale' if stale else ''})",
                }
            )
        rows.sort(key=lambda item: abs(item["change"]), reverse=True)
        return rows

    def _asset_threshold(self, key):
        if key == "fear":
            return 4.0
        if key in ("oil", "bitcoin"):
            return 1.5
        if key == "gold":
            return 0.75
        if key in ("dollar", "rates"):
            return 0.40
        return self.significant_threshold

    def _news_items(self):
        original_window = self.news.max_age_hours
        try:
            self.news.max_age_hours = max(original_window, self.news_window_hours)
            report = self.news.get_top_news(limit=20, category="all")
            return [item for item in report.get("items", []) if item.get("provider") != "Reddit RSS"]
        except Exception:
            return []
        finally:
            self.news.max_age_hours = original_window

    def _policy_items(self):
        try:
            report = self.gov_power.build_report()
            self.last_policy_error = "; ".join(report.get("errors", [])[:2]) or "None"
            return report.get("items", [])[:5]
        except Exception as error:
            self.last_policy_error = repr(error)
            return []

    def _possible_drivers(self, dashboard, changed_assets, news_items, policy_items):
        drivers = []
        lower_theme = str(dashboard.get("theme", "")).lower()
        changes = {item["key"]: item["change"] for item in changed_assets}

        market = changes.get("market", 0)
        tech = changes.get("tech", 0)
        fear = changes.get("fear", 0)
        oil = changes.get("oil", 0)
        gold = changes.get("gold", 0)
        dollar = changes.get("dollar", 0)
        rates = changes.get("rates", 0)
        bitcoin = changes.get("bitcoin", 0)

        if market < -0.5 and tech < -0.5 and fear > 1:
            drivers.append("Risk-off: stocks are down while VIX/fear is up, so investors may be reducing risk.")
        if market > 0.5 and tech > 0.5 and fear < 0:
            drivers.append("Risk-on: stocks are up while VIX/fear is down, so investors may be adding risk.")
        if rates > 0.4 or dollar > 0.4:
            drivers.append("Rates/dollar pressure: higher yields or a stronger dollar can pressure growth stocks, tech, and multinational earnings.")
        if oil > 1.5:
            drivers.append("Oil/inflation pressure: higher oil can help energy names but raise inflation and cost concerns.")
        if oil < -1.5:
            drivers.append("Oil relief: lower oil can reduce inflation pressure but may hurt energy producers.")
        if gold > 0.75 and market < 0:
            drivers.append("Safety bid: gold rising while stocks fall can mean investors are looking for protection.")
        if bitcoin > 1.5 and tech > 0:
            drivers.append("Speculative risk appetite: Bitcoin and Nasdaq strength together can show more appetite for risk.")
        if "ai" in lower_theme or "tech" in lower_theme:
            drivers.append("Tech/AI leadership: Nasdaq or AI-linked names may be driving the tone more than the whole market.")

        for item in news_items[:3]:
            title = item.get("title", "")
            source = item.get("source", "Unknown")
            age = item.get("age_label", "Unknown")
            if title:
                drivers.append(f"Headline lead: {source} — {title} ({age}).")

        for item in policy_items[:2]:
            title = item.get("title", "")
            branch = item.get("branch", "Policy")
            if title:
                drivers.append(f"Federal/policy lead: {branch} — {title}.")

        if not drivers:
            drivers.append("No clear driver yet. Treat the move as price-first until news, volume, or policy confirms it.")

        return drivers[:7]

    def _economics_translation(self, dashboard, changed_assets, policy_items):
        changes = {item["key"]: item["change"] for item in changed_assets}
        lines = []
        market = changes.get("market", 0)
        tech = changes.get("tech", 0)
        fear = changes.get("fear", 0)
        oil = changes.get("oil", 0)
        dollar = changes.get("dollar", 0)
        rates = changes.get("rates", 0)

        if market < 0 or tech < 0:
            lines.append("Stocks down usually means investors are worried about future profits, higher costs, tighter money, or uncertainty.")
        if market > 0 or tech > 0:
            lines.append("Stocks up usually means investors expect better growth, easier conditions, lower fear, or stronger earnings demand.")
        if fear > 0:
            lines.append("VIX up means protection is getting more expensive; that often shows fear or hedging.")
        if rates > 0:
            lines.append("Rates up can make future earnings worth less today and can pressure tech/growth valuations.")
        if dollar > 0:
            lines.append("A stronger dollar can pressure commodities and overseas revenue for U.S. multinationals.")
        if oil > 0:
            lines.append("Oil up can increase costs for consumers, airlines, shipping, and manufacturers, while helping energy producers.")

        for item in policy_items[:2]:
            translate = item.get("translate")
            if translate:
                lines.append(f"Policy economics: {translate}")

        if not lines:
            lines.append("The economic path is not clear yet. Wait for price, volume, sector reaction, or official data to confirm.")
        return lines[:6]

    def _sector_paths(self, dashboard, changed_assets, policy_items):
        changes = {item["key"]: item["change"] for item in changed_assets}
        sectors = []
        if changes.get("tech", 0) != 0:
            sectors.append("Tech/AI: QQQ, NVDA, AMD, SMH, SOXX")
        if changes.get("oil", 0) != 0:
            sectors.append("Energy/oil: XOM, CVX, XLE, CL=F")
        if changes.get("rates", 0) != 0:
            sectors.append("Rates/banks/real estate: XLF, KRE, XHB, VNQ, US10Y")
        if changes.get("dollar", 0) != 0:
            sectors.append("Dollar-sensitive: multinationals, commodities, gold, emerging markets")
        if changes.get("bitcoin", 0) != 0:
            sectors.append("Crypto/speculative risk: BTC-USD, COIN, IBIT, ETH-USD")
        for item in policy_items[:3]:
            for sector in item.get("sectors", [])[:2]:
                tickers = item.get("payload", {}).get("confirm_next", [])
                if tickers:
                    sectors.append(f"Policy sector: {sector} — watch {', '.join(tickers[:5])}")
                else:
                    sectors.append(f"Policy sector: {sector}")
        return self._dedupe(sectors)[:7]

    def _confirm_next(self, dashboard, changed_assets, sectors):
        checks = ["!pulse", "!watchtest", "!chart SPY 1d", "!chart QQQ 1d", "!news post"]
        keys = {item["key"] for item in changed_assets[:4]}
        if "oil" in keys:
            checks.append("!chart CL=F 5d")
        if "gold" in keys:
            checks.append("!chart GC=F 5d")
        if "bitcoin" in keys:
            checks.append("!chart BTC-USD 5d")
        if self.include_policy:
            checks.append("!power")
        checks.append("Compare sector ETF vs SPY to see if the move is broad or sector-specific.")
        checks.append("Do not assume causation until headline, price, volume, and sector reaction line up.")
        return checks[:9]

    def _confidence(self, changed_assets, news_items, policy_items):
        significant = [item for item in changed_assets if item.get("importance") == "major" and not item.get("stale")]
        score = 0
        score += min(len(significant), 3)
        score += 1 if news_items else 0
        score += 1 if policy_items else 0
        if score >= 4:
            return "Medium-High: multiple market signals plus news/policy leads. Still confirm with charts and source links."
        if score >= 2:
            return "Medium: some signals line up, but this is still an explanation framework, not proof."
        return "Low: not enough confirmed signals yet. Watch price/volume and fresh headlines."

    def _is_significant(self, changed_assets):
        return any(item.get("importance") == "major" and not item.get("stale") for item in changed_assets)

    def _signature(self, changed_assets, dashboard):
        major = [item for item in changed_assets if item.get("importance") == "major" and not item.get("stale")]
        if not major:
            return "no-major-move"
        parts = [f"{item['key']}:{item['direction']}" for item in major[:4]]
        return "|".join(parts) + f"|{dashboard.get('theme', '')}"

    def _safe_float(self, value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result:
            return None
        return result

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _timestamp(self):
        return datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
