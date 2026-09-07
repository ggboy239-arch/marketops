import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from providers.finlight_provider import FinlightProvider
from providers.marketaux_provider import MarketauxProvider
from providers.reddit_provider import RedditProvider
from providers.rss_provider import RSSProvider


class NewsEngine:
    """Turns headlines into MarketOps news cards.

    Routing rules:
    - Sports/entertainment noise is blocked before category hints are used.
    - AI channel is strict: company names alone do not count as AI.
    - General/major news is allowed when it can affect markets, sectors, or companies.
    """

    AI_PURE_KEYWORDS = [
        "ai", "artificial intelligence", "generative ai", "openai", "chatgpt",
        "machine learning", "deep learning", "large language model", "llm",
        "semiconductor", "semiconductors", "chip", "chips", "gpu", "gpus",
        "data center", "data centers", "data centre", "data centres",
        "cloud ai", "ai model", "ai models", "ai training", "ai inference",
        "groq", "nvidia h100", "nvidia blackwell", "blackwell",
    ]

    AI_COMPANIES = [
        "nvidia", "nvda", "amd", "microsoft", "msft", "amazon", "amzn",
        "apple", "aapl", "google", "googl", "alphabet", "meta",
        "oracle", "orcl", "broadcom", "avgo", "tsmc", "arm",
    ]

    AI_CONTEXT_KEYWORDS = [
        "ai", "artificial intelligence", "generative ai", "chip", "chips",
        "semiconductor", "semiconductors", "gpu", "gpus", "data center",
        "data centers", "data centre", "data centres", "cloud ai", "openai",
        "chatgpt", "model training", "inference", "blackwell", "h100",
    ]

    FED_RATES_KEYWORDS = [
        "fed", "federal reserve", "powell", "rate hike", "rate cut", "rates",
        "interest rates", "yield", "yields", "treasury", "treasuries",
        "inflation", "cpi", "ppi", "pce", "jobs report", "payroll",
        "payrolls", "gdp", "unemployment", "jobless claims",
        "consumer prices", "producer prices", "bond yields",
        "treasury yields", "fomc", "monetary policy",
    ]

    GEO_STRONG_KEYWORDS = [
        "oil", "crude", "brent", "wti", "opec", "iran", "israel", "gaza",
        "west bank", "netanyahu", "hezbollah", "lebanon", "hormuz",
        "middle east", "russia", "ukraine", "kyiv", "taiwan", "north korea",
        "nato", "war", "sanctions", "missile", "attack", "ceasefire",
        "tariff", "tariffs", "trade war", "export controls", "china",
        "beijing", "south china sea", "red sea", "shipping lane",
    ]

    CHINA_CONTEXT_KEYWORDS = [
        "tariff", "tariffs", "trade", "exports", "export controls", "sanctions",
        "taiwan", "military", "economy", "economic", "markets", "stocks",
        "shares", "chips", "semiconductor", "rare earth", "supply chain",
    ]

    CRYPTO_KEYWORDS = [
        "bitcoin", "btc", "crypto", "cryptocurrency", "ethereum", "ether",
        "coinbase", "spot bitcoin etf", "bitcoin etf", "ethereum etf",
        "ether etf", "crypto etf",
    ]

    BROAD_MARKET_KEYWORDS = [
        "stocks", "stock futures", "shares", "wall street", "s&p", "s&p 500",
        "nasdaq", "dow", "futures", "global markets", "investors",
        "markets", "market wrap", "selloff", "sell-off", "rally",
        "risk appetite", "risk assets", "bond market", "dollar", "gold",
        "oil prices",
    ]

    GENERAL_NEWS_KEYWORDS = [
        "white house", "congress", "senate", "house votes", "supreme court",
        "court", "judge", "lawsuit", "president", "administration",
        "government shutdown", "national emergency", "cyberattack",
        "cyber attack", "ransomware", "data breach", "election", "vote",
        "immigration", "border", "protest", "strike", "hurricane",
        "wildfire", "earthquake", "public health", "fema", "national guard",
        "boeing", "runway", "aircraft", "airport", "amazon prime air",
        "antitrust", "anti-trust", "regulation", "regulator", "doj",
        "department of justice", "ftc", "sec", "fda", "recall", "probe",
        "investigation", "indictment", "charges", "settlement", "fine",
        "bank", "banking", "bank failure", "bankruptcy", "credit stress",
        "debt ceiling", "budget", "federal budget", "supply chain",
        "port", "ports", "rail", "railroad", "union", "labor", "factory",
        "plant", "shutdown", "outage", "power outage", "grid",
        "pentagon", "defense contract", "contract award", "medicaid",
        "medicare", "visa", "tariff", "tariffs", "trade", "sanctions",
    ]

    COMPANY_GENERAL_KEYWORDS = [
        "amazon", "amzn", "boeing", "ba", "apple", "aapl", "microsoft",
        "msft", "google", "alphabet", "meta", "tesla", "tsla", "walmart",
        "target", "costco", "lockheed", "lmt", "rtx", "exxon", "xom",
        "chevron", "cvx", "tyson", "tsn", "disney", "dis", "netflix",
        "nflx", "comcast", "cmcsa", "paramount", "wbd", "warner bros",
        "nike", "nke", "adidas",
    ]

    SPORTS_NOISE_KEYWORDS = [
        "nfl", "nba", "mlb", "nhl", "wnba", "ncaa", "college football",
        "college basketball", "football", "basketball", "baseball", "hockey",
        "soccer", "golf", "tennis", "cricket", "rugby", "f1", "formula 1",
        "formula one", "nascar", "indycar", "motogp", "ufc", "mma", "boxing",
        "wrestling", "wwe", "olympics", "olympic", "world cup", "fifa",
        "uefa", "premier league", "champions league", "la liga", "mls",
        "super bowl", "world series", "stanley cup", "march madness",
        "playoffs", "finals", "tournament", "match", "game recap",
        "quarterback", "touchdown", "home run", "pitcher", "goalkeeper",
        "us open", "grand slam", "draft pick", "free agent", "trade deadline",
    ]

    ENTERTAINMENT_NOISE_KEYWORDS = [
        "celebrity", "movie", "film", "box office", "actor", "actress",
        "music", "album", "song", "concert", "tour", "festival", "fashion",
        "recipe", "tv show", "trailer", "grammy", "grammys", "emmy", "emmys",
        "oscars", "hollywood", "red carpet", "streaming series",
    ]

    SPORTS_ENTERTAINMENT_KEEP_KEYWORDS = [
        "stock", "stocks", "shares", "earnings", "revenue", "profit",
        "guidance", "lawsuit", "antitrust", "regulator", "sec", "doj",
        "ftc", "merger", "acquisition", "bankruptcy", "labor strike",
        "strike", "media rights", "broadcast rights", "streaming rights",
        "sponsorship", "sponsor", "contract", "cyberattack", "data breach",
    ]

    IRRELEVANT_KEYWORDS = [
        "horoscope", "crossword", "wordle", "recipe", "celebrity baby",
        "fashion week", "dating", "relationship advice",
    ]

    OVERRIDE_KEEP_KEYWORDS = [
        "stocks", "shares", "stock futures", "oil", "crude", "fed",
        "inflation", "rate", "rates", "yield", "treasury", "war", "attack",
        "sanctions", "tariff", "tariffs", "ceasefire", "missile",
        "cyberattack", "cyber attack", "strike", "lawsuit", "regulation",
        "antitrust", "supply chain", "bank", "banking",
    ]

    MAJOR_GENERAL_BOOST_KEYWORDS = [
        "white house", "president", "congress", "supreme court", "tariff",
        "tariffs", "sanctions", "cyberattack", "ransomware", "data breach",
        "strike", "shutdown", "supply chain", "antitrust", "doj", "ftc",
        "sec", "recall", "bank failure", "defense contract", "oil",
    ]

    CATEGORY_ALIASES = {
        "all": None,
        "market": "📊 Broad Market",
        "markets": "📊 Broad Market",
        "broad": "📊 Broad Market",
        "breaking": "📊 Broad Market",
        "major": None,
        "ai": "🤖 AI / Tech",
        "tech": "🤖 AI / Tech",
        "fed": "🏦 Fed / Rates",
        "rates": "🏦 Fed / Rates",
        "calendar": "🏦 Fed / Rates",
        "geo": "🛢 Oil / Geopolitics",
        "geopolitics": "🛢 Oil / Geopolitics",
        "oil": "🛢 Oil / Geopolitics",
        "crypto": "₿ Crypto",
        "bitcoin": "₿ Crypto",
        "general": "🗞 General News",
        "national": "🗞 General News",
        "nationwide": "🗞 General News",
        "world": "🗞 General News",
        "usa": "🗞 General News",
        "us": "🗞 General News",
        "reddit": "🧵 Reddit Hot",
        "reddits": "🧵 Reddit Hot",
        "reddit-hot": "🧵 Reddit Hot",
        "social": "🧵 Reddit Hot",
    }

    CHANNEL_MAP = {
        "🤖 AI / Tech": "ai-news",
        "🏦 Fed / Rates": "fed",
        "🛢 Oil / Geopolitics": "geopolitics",
        "₿ Crypto": "crypto",
        "📊 Broad Market": "breaking-news",
        "🗞 General News": "general-news",
        "🧵 Reddit Hot": "reddit-hot",
    }

    CHANNEL_ORDER = [
        "breaking-news",
        "general-news",
        "ai-news",
        "fed",
        "geopolitics",
        "crypto",
        "reddit-hot",
    ]

    TAG_PRIORITY = [
        "🏦 Fed / Rates",
        "🛢 Oil / Geopolitics",
        "🤖 AI / Tech",
        "₿ Crypto",
        "📊 Broad Market",
        "🗞 General News",
        "🧵 Reddit Hot",
    ]

    def __init__(self):
        self.marketaux_provider = MarketauxProvider()
        self.finlight_provider = FinlightProvider()
        self.rss_provider = RSSProvider()
        self.reddit_provider = RedditProvider()
        self.fallback_to_rss = self._env_bool("NEWS_FALLBACK_RSS", default=True)
        self.use_finlight = self._env_bool("NEWS_USE_FINLIGHT", default=False)
        self.include_reddit = self._env_bool("REDDIT_ENABLED", default=True)
        self.max_age_hours = float(os.getenv("NEWS_MAX_AGE_HOURS", "1"))
        self.last_provider_used = "Not checked yet"

    def get_top_news(self, limit=5, category="all"):
        raw_items = self._get_raw_items(limit=60, category=category)
        classified_items = self._classify_items(raw_items)
        classified_items = [item for item in classified_items if self._is_fresh(item)]

        tag_filter = self._resolve_category(category)
        if tag_filter is not None:
            classified_items = [item for item in classified_items if tag_filter in item["tags"]]

        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        return {
            "items": classified_items[:limit],
            "category": category or "all",
            "tag_filter": tag_filter,
            "updated": self._timestamp(),
            "source_policy": self.source_policy(),
            "freshness_policy": self.freshness_policy(),
            "provider_used": self.last_provider_used,
        }

    def get_channel_reports(self, limit_per_channel=3):
        raw_items = self._get_raw_items(limit=100, category="all")
        classified_items = self._classify_items(raw_items)
        classified_items = [item for item in classified_items if self._is_fresh(item)]
        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        reports = {channel: [] for channel in self.CHANNEL_ORDER}
        for item in classified_items:
            channel = item["channel"]
            if len(reports[channel]) < limit_per_channel:
                reports[channel].append(item)

        return {
            "channels": reports,
            "counts": {channel: len(items) for channel, items in reports.items()},
            "updated": self._timestamp(),
            "source_policy": self.source_policy(),
            "freshness_policy": self.freshness_policy(),
            "provider_used": self.last_provider_used,
        }

    def channel_map_text(self):
        return "\n".join(f"• {tag} → `#{channel}`" for tag, channel in self.CHANNEL_MAP.items())

    def source_policy(self):
        parts = []
        if self.marketaux_provider.enabled:
            parts.append("Marketaux mode is ON. MarketOps checks Marketaux first for free market-news API coverage.")
            parts.append(self.marketaux_provider.source_policy())
        else:
            parts.append("Marketaux is OFF because MARKETAUX_API_KEY is missing or disabled.")
        if self.fallback_to_rss:
            parts.append("Reuters RSS/search is ON.")
            parts.append("Major-source RSS/search is ON by default for AP, NPR, CNBC, BBC, and Yahoo Finance as second data points.")
            parts.append(self.rss_provider.source_policy())
        if self.include_reddit:
            parts.append("Reddit RSS monitor is ON and routes chatter to #reddit-hot only.")
        parts.append("Sports/entertainment filtering is ON. AI routing requires actual AI/chip/data-center context.")
        return " ".join(parts)

    def freshness_policy(self):
        max_minutes = round(self.max_age_hours * 60)
        if max_minutes < 60:
            return f"MarketOps shows headlines published within the last {max_minutes} minutes."
        return f"MarketOps shows headlines published within the last {self.max_age_hours:g} hour(s)."

    def category_help(self):
        return (
            "Use one of these:\n"
            "• `!news` — all MarketOps news\n"
            "• `!news market` — market-moving / broad market\n"
            "• `!news general` — important national/world news that can affect markets or companies\n"
            "• `!news ai` — real AI / chips / data-center news only\n"
            "• `!news fed` — Fed / rates / inflation\n"
            "• `!news geo` — oil / geopolitics\n"
            "• `!news crypto` — bitcoin / crypto\n"
            "• `!news reddit` — Reddit market chatter only\n"
            "• `!news channels` — show channel routing\n"
            "• `!news sources` — show provider policy\n"
            "• `!news debug` — show how many fresh headlines each channel found\n"
            "• `!news post` — post fresh headlines into matching channels"
        )

    def _get_raw_items(self, limit, category="all"):
        items = []
        used = []
        normalized_category = (category or "all").strip().lower()

        if normalized_category in ("reddit", "reddits", "reddit-hot", "social"):
            reddit_items = self.reddit_provider.get_latest_news(limit=limit)
            self.last_provider_used = "Reddit RSS"
            return reddit_items

        if self.marketaux_provider.enabled:
            marketaux_items = self.marketaux_provider.get_latest_news(limit=limit)
            if marketaux_items:
                items.extend(marketaux_items)
                used.append("Marketaux")

        if self.use_finlight and self.finlight_provider.enabled:
            finlight_items = self.finlight_provider.get_latest_news(limit=limit)
            if finlight_items:
                items.extend(finlight_items)
                used.append("Finlight REST")

        if self.fallback_to_rss:
            rss_items = self.rss_provider.get_latest_news(limit=limit)
            if rss_items:
                items.extend(rss_items)
                used.append("Trusted RSS")

        if self.include_reddit:
            reddit_items = self.reddit_provider.get_latest_news(limit=limit)
            if reddit_items:
                items.extend(reddit_items)
                used.append("Reddit RSS")

        if not used:
            used.append("No provider returned raw items")

        self.last_provider_used = " + ".join(used)
        return self._dedupe_raw_items(items)[:limit]

    def _classify_items(self, raw_items):
        classified = []
        for item in raw_items:
            result = self._classify(item)
            if result is not None:
                classified.append(result)
        return classified

    def _classify(self, item):
        title = item.get("title", "Untitled")
        summary = item.get("summary", "")
        source = item.get("source", "")
        feed_name = item.get("feed_name", "")
        provider = item.get("provider", "RSS")
        category_hint = item.get("category_hint")

        routing_text = self._normalize_text(f"{title} {summary} {source} {feed_name}")

        if provider == "Reddit RSS":
            tags = ["🧵 Reddit Hot"]
            primary_tag = "🧵 Reddit Hot"
        else:
            if self._should_ignore(routing_text):
                return None

            tags = self._detect_tags(routing_text)

            # Do not let generic "technology" feeds auto-route into AI.
            # AI needs actual AI/chip/data-center context, not just Amazon/Apple/Microsoft/etc.
            if not tags and category_hint in self.CHANNEL_MAP:
                if category_hint == "🤖 AI / Tech":
                    if self._is_ai_tech(routing_text):
                        tags.append("🤖 AI / Tech")
                    elif self._matches_any(routing_text, self.COMPANY_GENERAL_KEYWORDS + self.GENERAL_NEWS_KEYWORDS):
                        tags.append("🗞 General News")
                else:
                    tags.append(category_hint)

            if not tags:
                return None
            primary_tag = self._primary_tag(tags)

        channel = self.CHANNEL_MAP[primary_tag]
        score = len(tags) + 1

        if provider == "Marketaux":
            score += 1
        if provider == "Finlight":
            score += 1
        if provider == "Reddit RSS":
            score = 1
        if any(name in source.lower() for name in ("reuters", "ap", "associated press", "npr", "cnbc", "bbc", "yahoo finance")):
            score += 1
        if self._matches_any(routing_text, self.MAJOR_GENERAL_BOOST_KEYWORDS):
            score += 1

        published_dt = item.get("published_dt")
        return {
            "source": source or provider or "Unknown",
            "title": title,
            "link": item.get("link", ""),
            "summary": summary,
            "published": item.get("published", ""),
            "published_dt": published_dt,
            "published_label": self._published_label(published_dt),
            "age_label": self._age_label(published_dt),
            "age_minutes": self._age_minutes(published_dt),
            "tags": tags,
            "primary_tag": primary_tag,
            "channel": channel,
            "importance": self._importance(score),
            "importance_score": score,
            "why_it_matters": self._why_it_matters(tags),
            "watch": self._watch(tags),
            "trusted": item.get("trusted", False),
            "provider": provider,
        }

    def _detect_tags(self, title_text):
        tags = []

        if self._matches_any(title_text, self.FED_RATES_KEYWORDS):
            tags.append("🏦 Fed / Rates")

        if self._matches_any(title_text, self.GEO_STRONG_KEYWORDS) or self._china_market_context(title_text):
            tags.append("🛢 Oil / Geopolitics")

        if self._is_ai_tech(title_text):
            tags.append("🤖 AI / Tech")

        if self._matches_any(title_text, self.CRYPTO_KEYWORDS):
            tags.append("₿ Crypto")

        if self._matches_any(title_text, self.BROAD_MARKET_KEYWORDS):
            tags.append("📊 Broad Market")

        if self._matches_any(title_text, self.GENERAL_NEWS_KEYWORDS):
            tags.append("🗞 General News")

        if not tags and self._matches_any(title_text, self.COMPANY_GENERAL_KEYWORDS):
            tags.append("🗞 General News")

        return self._dedupe_tags(tags)

    def _is_ai_tech(self, title_text):
        # Actual AI/chip/data-center words are enough.
        if self._matches_any(title_text, self.AI_PURE_KEYWORDS):
            return True

        # Company names alone are NOT enough for #ai-news.
        has_ai_company = self._matches_any(title_text, self.AI_COMPANIES)
        has_ai_context = self._matches_any(title_text, self.AI_CONTEXT_KEYWORDS)
        return has_ai_company and has_ai_context

    def _should_ignore(self, title_text):
        if self._sports_or_entertainment_noise(title_text):
            return True

        if not self._matches_any(title_text, self.IRRELEVANT_KEYWORDS):
            return False

        return not self._matches_any(title_text, self.OVERRIDE_KEEP_KEYWORDS)

    def _sports_or_entertainment_noise(self, title_text):
        has_sports = self._matches_any(title_text, self.SPORTS_NOISE_KEYWORDS)
        has_entertainment = self._matches_any(title_text, self.ENTERTAINMENT_NOISE_KEYWORDS)

        if not has_sports and not has_entertainment:
            return False

        # Keep rare sports/entertainment stories only when the headline is really business/market related.
        has_business_context = self._matches_any(title_text, self.SPORTS_ENTERTAINMENT_KEEP_KEYWORDS)
        has_company_context = self._matches_any(title_text, self.COMPANY_GENERAL_KEYWORDS)
        has_market_context = self._matches_any(title_text, self.BROAD_MARKET_KEYWORDS)

        return not (has_business_context and (has_company_context or has_market_context))

    def _china_market_context(self, title_text):
        if not self._keyword_match(title_text, "china") and not self._keyword_match(title_text, "beijing"):
            return False
        return self._matches_any(title_text, self.CHINA_CONTEXT_KEYWORDS)

    def _is_fresh(self, item):
        age_minutes = item.get("age_minutes")
        if age_minutes is None:
            return False
        return age_minutes <= self.max_age_hours * 60

    def _resolve_category(self, category):
        if category is None:
            return None
        normalized = category.strip().lower()
        return self.CATEGORY_ALIASES.get(normalized)

    def _primary_tag(self, tags):
        for tag in self.TAG_PRIORITY:
            if tag in tags:
                return tag
        return tags[0]

    def _dedupe_tags(self, tags):
        deduped = []
        for tag in tags:
            if tag not in deduped:
                deduped.append(tag)
        return deduped

    def _dedupe_raw_items(self, items):
        seen = set()
        deduped = []
        for item in items:
            key = item.get("link") or item.get("title", "").lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _matches_any(self, text, keywords):
        return any(self._keyword_match(text, keyword) for keyword in keywords)

    def _keyword_match(self, text, keyword):
        normalized_keyword = self._normalize_text(keyword)
        if not normalized_keyword:
            return False
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return re.search(pattern, text) is not None

    def _normalize_text(self, text):
        text = (text or "").lower()
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _importance(self, score):
        if score >= 4:
            return "★★★★★"
        if score == 3:
            return "★★★★☆"
        if score == 2:
            return "★★★☆☆"
        return "★★☆☆☆"

    def _why_it_matters(self, tags):
        if "🧵 Reddit Hot" in tags:
            return "Reddit is chatter, not confirmed news. Use it as an early watchlist idea only."
        if "🏦 Fed / Rates" in tags:
            return "Rates and inflation can move the whole market, especially tech and growth stocks."
        if "🛢 Oil / Geopolitics" in tags:
            return "Oil, tariffs, sanctions, and geopolitical headlines can affect inflation, energy, defense, and risk appetite."
        if "🤖 AI / Tech" in tags:
            return "AI, chips, GPUs, and data-center headlines can drive Nasdaq futures, QQQ, NVDA, AMD, and related names."
        if "₿ Crypto" in tags:
            return "Crypto headlines may move Bitcoin even when the broader stock market is quiet."
        if "📊 Broad Market" in tags:
            return "Broad market headlines can explain moves in S&P futures, Nasdaq futures, and VIX."
        if "🗞 General News" in tags:
            return "Major U.S./world news can affect markets through policy, regulation, lawsuits, supply chains, labor, energy, or company risk."
        return "Watch market reaction before treating this as important."

    def _watch(self, tags):
        watch = []
        if "🧵 Reddit Hot" in tags:
            watch.extend(["Verify source", "Price/volume reaction", "Do not trade rumor alone"])
        if "🏦 Fed / Rates" in tags:
            watch.extend(["US10Y", "DXY", "Nasdaq Futures", "VIX"])
        if "🛢 Oil / Geopolitics" in tags:
            watch.extend(["Oil", "VIX", "S&P Futures", "Defense"])
        if "🤖 AI / Tech" in tags:
            watch.extend(["Nasdaq Futures", "NVDA", "AMD", "QQQ"])
        if "₿ Crypto" in tags:
            watch.extend(["Bitcoin", "Coinbase", "Crypto ETFs"])
        if "📊 Broad Market" in tags:
            watch.extend(["S&P Futures", "Nasdaq Futures", "VIX"])
        if "🗞 General News" in tags:
            watch.extend(["Affected sector", "SPY/QQQ/VIX", "Follow-up source", "Policy impact"])

        deduped = []
        for item in watch:
            if item not in deduped:
                deduped.append(item)
        return ", ".join(deduped[:5]) or "Market reaction"

    def _published_label(self, published_dt):
        if published_dt is None:
            return "Unknown"
        try:
            local_time = published_dt.astimezone(ZoneInfo("America/Los_Angeles"))
            return local_time.strftime("%I:%M %p PT").lstrip("0")
        except Exception:
            return "Unknown"

    def _age_label(self, published_dt):
        minutes = self._age_minutes(published_dt)
        if minutes is None:
            return "Unknown"
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes == 0:
            return f"{hours}h ago"
        return f"{hours}h {remaining_minutes}m ago"

    def _age_minutes(self, published_dt):
        if published_dt is None:
            return None
        try:
            now = datetime.now(ZoneInfo("UTC"))
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=ZoneInfo("UTC"))
            published_utc = published_dt.astimezone(ZoneInfo("UTC"))
            seconds = (now - published_utc).total_seconds()
            return max(0, int(seconds // 60))
        except Exception:
            return None

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")
