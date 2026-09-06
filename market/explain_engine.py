class ExplainEngine:
    """Explains market dashboard symbols in plain English.

    This file does not talk to Discord and does not fetch prices.
    Its only job is to explain what each market signal means.
    """

    TOPIC_ALIASES = {
        "market": "market",
        "sp": "market",
        "sp500": "market",
        "s&p": "market",
        "s&p500": "market",
        "s&p futures": "market",
        "es": "market",
        "es=f": "market",
        "tech": "tech",
        "nasdaq": "tech",
        "nasdaq futures": "tech",
        "nq": "tech",
        "nq=f": "tech",
        "qqq": "tech",
        "vix": "fear",
        "fear": "fear",
        "volatility": "fear",
        "oil": "oil",
        "crude": "oil",
        "cl": "oil",
        "cl=f": "oil",
        "dollar": "dollar",
        "dxy": "dollar",
        "usd": "dollar",
        "rates": "rates",
        "rate": "rates",
        "10y": "rates",
        "us10y": "rates",
        "tnx": "rates",
        "bonds": "rates",
        "bitcoin": "bitcoin",
        "btc": "bitcoin",
        "crypto": "bitcoin",
    }

    TOPIC_DETAILS = {
        "market": {
            "title": "🇺🇸 S&P Futures / Market",
            "plain": "This is the broad U.S. stock-market mood. It helps answer: are investors buying or selling the overall market?",
            "up": "Usually bullish. Investors are more willing to own stocks.",
            "down": "Usually cautious. Investors are selling or waiting for more information.",
            "benefits": "Broad ETFs like VOO/SPY and many large-cap stocks usually benefit when this is strong.",
            "loses": "Defensive assets may lag when the broad market is strongly risk-on.",
            "watch": "Compare it with Nasdaq futures and VIX. If S&P is down and VIX is up, that is a risk-off clue.",
        },
        "tech": {
            "title": "🤖 Nasdaq Futures / Tech",
            "plain": "This is the tech and growth-stock signal. It is useful for AI names, semiconductors, and big technology stocks.",
            "up": "Tech is attracting buyers. AI, semis, and growth stocks may be leading.",
            "down": "Tech is under pressure. This can happen when yields rise, earnings disappoint, or risk appetite fades.",
            "benefits": "QQQ, NVDA, AMD, MSFT, and other growth/AI names can benefit when tech leads.",
            "loses": "Tech-heavy portfolios can struggle when Nasdaq futures lag the S&P.",
            "watch": "Compare Nasdaq futures against S&P futures. If Nasdaq is stronger, tech is showing relative strength.",
        },
        "fear": {
            "title": "😨 VIX / Fear Index",
            "plain": "VIX is the market's fear gauge. It measures expected volatility in the S&P 500.",
            "up": "Fear is rising. Investors may be buying protection or preparing for bigger moves.",
            "down": "Fear is falling. That often supports a calmer, more risk-on market.",
            "benefits": "Volatility products and defensive positioning can benefit when fear rises.",
            "loses": "Risk assets can struggle if VIX rises quickly, especially if S&P futures are also falling.",
            "watch": "A small VIX rise is caution. A large VIX jump with falling futures is a stronger warning.",
        },
        "oil": {
            "title": "🛢 Oil / Energy + Geopolitics",
            "plain": "Oil helps you watch energy, inflation pressure, and geopolitical risk.",
            "up": "Oil rising can mean stronger demand, supply concerns, OPEC news, hurricanes, or Middle East risk.",
            "down": "Oil falling can mean weaker demand, more supply, or less geopolitical concern.",
            "benefits": "Energy names like XOM, CVX, and XLE can benefit if higher oil is expected to last.",
            "loses": "Airlines, shipping, and inflation-sensitive areas can struggle if oil jumps hard.",
            "watch": "Oil above +2% with VIX up and S&P down is a stronger geopolitical/inflation warning.",
        },
        "dollar": {
            "title": "💵 Dollar / DXY",
            "plain": "The dollar shows demand for U.S. dollars. It can act like a safety and rates signal.",
            "up": "A stronger dollar can mean safety demand or higher U.S. rate expectations.",
            "down": "A weaker dollar can support risk assets and global trade-sensitive companies.",
            "benefits": "Dollar strength can help companies with mostly U.S. costs and foreign revenue exposure varies by company.",
            "loses": "A very strong dollar can pressure commodities, emerging markets, and some multinational earnings.",
            "watch": "If dollar and VIX both rise while stocks fall, that often confirms risk-off behavior.",
        },
        "rates": {
            "title": "🏦 US10Y / 10-Year Yield",
            "plain": "The 10-year yield helps you read interest-rate, inflation, and growth expectations.",
            "up": "Higher yields can pressure tech and growth stocks because future earnings get discounted more heavily.",
            "down": "Lower yields can support tech, but if yields fall because of recession fear, stocks may still fall.",
            "benefits": "Banks and some financials may benefit from certain rising-rate environments.",
            "loses": "High-growth tech, housing, and rate-sensitive stocks can struggle when yields rise quickly.",
            "watch": "If yields rise and Nasdaq falls more than S&P, it may be a rate-fear day.",
        },
        "bitcoin": {
            "title": "₿ Bitcoin / Crypto Risk Appetite",
            "plain": "Bitcoin helps you watch crypto-specific demand and extra risk appetite.",
            "up": "Bitcoin rising can mean risk appetite is improving, or it can be a crypto-specific story like ETF flows or regulation.",
            "down": "Bitcoin falling can mean risk appetite is weaker, or crypto-specific sellers are active.",
            "benefits": "Crypto-related names and Bitcoin ETFs can benefit when Bitcoin has a strong move.",
            "loses": "Crypto-sensitive stocks and high-beta risk assets can struggle when Bitcoin sells off hard.",
            "watch": "If Bitcoin moves alone while stocks are flat, ask whether it is a crypto story instead of a whole-market story.",
        },
    }

    def build(self, topic, dashboard):
        key = self._resolve_topic(topic)

        if key is None:
            return {
                "found": False,
                "title": "MarketOps Explain",
                "message": self.available_topics(),
            }

        details = self.TOPIC_DETAILS[key]
        raw = dashboard.get("raw", {})
        quote = raw.get(key, {})
        change = self._change(quote)

        return {
            "found": True,
            "key": key,
            "title": details["title"],
            "current": self._current_line(quote),
            "plain": details["plain"],
            "up": details["up"],
            "down": details["down"],
            "benefits": details["benefits"],
            "loses": details["loses"],
            "watch": details["watch"],
            "today": self._today_read(key, change),
            "updated": dashboard.get("updated", "Unknown"),
        }

    def available_topics(self):
        return (
            "Try one of these:\n"
            "• `!explain market`\n"
            "• `!explain tech`\n"
            "• `!explain vix`\n"
            "• `!explain oil`\n"
            "• `!explain dollar`\n"
            "• `!explain rates`\n"
            "• `!explain bitcoin`"
        )

    def _resolve_topic(self, topic):
        if topic is None:
            return None

        normalized = topic.strip().lower()

        return self.TOPIC_ALIASES.get(normalized)

    def _change(self, quote):
        try:
            return float(quote.get("change_percent", 0))
        except (TypeError, ValueError):
            return 0

    def _current_line(self, quote):
        if not quote:
            return "Current data unavailable."

        symbol = quote.get("symbol", "Unknown")
        price = quote.get("price", 0)
        change = quote.get("change_percent", 0)
        status = quote.get("status", "Unknown")
        kind = quote.get("kind", "number")

        return (
            f"{symbol}\n"
            f"Price: **{self._format_price(price, kind)}**\n"
            f"Today: **{change:+.2f}%**\n"
            f"Status: {status}"
        )

    def _format_price(self, price, kind):
        if kind == "crypto":
            return f"${price:,.0f}"

        if kind in ("money", "futures_money"):
            return f"${price:,.2f}"

        if kind == "futures":
            return f"{price:,.2f} pts"

        if kind == "yield":
            return f"{price:.2f}%"

        return f"{price:,.2f}"

    def _today_read(self, key, change):
        if abs(change) < 0.25:
            return "Today this signal is mostly flat. Do not overreact to small moves."

        if key == "fear":
            if change > 0:
                return "Today fear is higher. That adds caution, especially if S&P futures are falling."
            return "Today fear is lower. That usually helps risk assets."

        if key == "oil":
            if change >= 2:
                return "Oil is making a meaningful move higher. Check geopolitics, OPEC, supply, or inflation headlines."
            if change > 0:
                return "Oil is higher, but not enough by itself to call panic. Watch if it keeps climbing."
            return "Oil is lower. That can reduce inflation/geopolitical pressure if the move continues."

        if key == "rates":
            if change > 0:
                return "Yields are higher. Watch whether tech starts to weaken because of rate pressure."
            return "Yields are lower. That can help tech, unless the move is caused by recession fear."

        if key == "dollar":
            if change > 0:
                return "The dollar is stronger. If stocks are also falling, this can confirm defensive behavior."
            return "The dollar is weaker. That can be supportive for risk assets."

        if key == "bitcoin":
            if change > 0:
                return "Bitcoin is higher. Check whether crypto is moving with the market or from a crypto-specific catalyst."
            return "Bitcoin is lower. That can suggest weaker risk appetite or crypto-specific selling."

        if key == "tech":
            if change > 0:
                return "Tech is higher. Compare it with S&P futures to see if tech is leading."
            return "Tech is lower. Watch whether rates or earnings are pressuring growth stocks."

        if change > 0:
            return "The broad market is higher. That usually supports a risk-on read if VIX is falling."

        return "The broad market is lower. That adds caution, especially if VIX is also rising."
