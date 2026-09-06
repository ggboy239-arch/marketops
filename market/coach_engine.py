class CoachEngine:
    """Turns market dashboard data into plain-English coaching.

    This file does not talk to Discord and does not fetch prices.
    Its only job is to explain what the dashboard means.
    """

    def build(self, dashboard):
        score = dashboard.get("score", 50)
        risk = dashboard.get("risk", "🟡 Mixed / Wait-and-See")
        theme = dashboard.get("theme", "📈 Live Market")
        reasons = dashboard.get("reasons", [])
        raw = dashboard.get("raw", {})

        market = self._change(raw, "market")
        tech = self._change(raw, "tech")
        fear = self._change(raw, "fear")
        oil = self._change(raw, "oil")
        bitcoin = self._change(raw, "bitcoin")

        return {
            "title": "🧠 Market Coach",
            "read": self._read(score, risk),
            "meaning": self._meaning(score, market, tech, fear, oil, bitcoin),
            "why": self._why(reasons),
            "watch": self._watch_list(market, tech, fear, oil, bitcoin),
            "lesson": self._lesson(market, tech, fear, oil, bitcoin),
            "theme": theme,
            "reminder": self._reminder(score),
            "updated": dashboard.get("updated", "Unknown"),
        }

    def _change(self, raw, key):
        try:
            return float(raw[key]["change_percent"])
        except (KeyError, TypeError, ValueError):
            return 0

    def _read(self, score, risk):
        return f"{risk}\nScore: **{score}/100**"

    def _meaning(self, score, market, tech, fear, oil, bitcoin):
        if score >= 75:
            return (
                "The market is strongly risk-on. Investors are showing confidence, "
                "especially if futures are green and fear is falling."
            )

        if score >= 60:
            return (
                "The market is slightly risk-on. Buyers are active, but you still "
                "want to check whether VIX and oil confirm the move."
            )

        if score > 40:
            return (
                "The market is mixed. This usually means investors are waiting for "
                "more information before making a strong move."
            )

        if score > 25:
            return (
                "The market is mildly risk-off. Investors are cautious, but this does "
                "not automatically mean panic. Watch whether VIX or oil accelerates."
            )

        return (
            "The market is heavily risk-off. Fear is elevated and investors may be "
            "reducing risk more aggressively."
        )

    def _why(self, reasons):
        if not reasons:
            return "No clear reason yet. Keep watching S&P futures, Nasdaq futures, VIX, and oil."

        return "\n".join(f"• {reason}" for reason in reasons[:5])

    def _watch_list(self, market, tech, fear, oil, bitcoin):
        watch = []

        if fear > 0:
            watch.append("😨 VIX — fear is rising")
        else:
            watch.append("😌 VIX — fear is calm/falling")

        if oil >= 1:
            watch.append("🛢 Oil — watch for geopolitics or inflation pressure")
        elif oil <= -1:
            watch.append("🛢 Oil — easing oil can support risk assets")
        else:
            watch.append("🛢 Oil — not a major signal yet")

        if market < 0:
            watch.append("🇺🇸 S&P Futures — broad market is weak")
        else:
            watch.append("🇺🇸 S&P Futures — broad market is holding up")

        if tech > market + 0.20:
            watch.append("🤖 Nasdaq Futures — tech is outperforming")
        elif tech < market - 0.20:
            watch.append("🤖 Nasdaq Futures — tech is lagging")

        if abs(bitcoin) >= 1:
            watch.append("₿ Bitcoin — crypto is making a stronger move")

        return "\n".join(f"• {item}" for item in watch[:5])

    def _lesson(self, market, tech, fear, oil, bitcoin):
        if tech > market + 0.20 and tech > 0:
            return (
                "When Nasdaq futures are stronger than S&P futures, tech is showing "
                "relative strength. That can point to AI, growth stocks, or rate optimism."
            )

        if fear > 0 and market < 0:
            return (
                "When S&P futures fall and VIX rises, investors are becoming more cautious. "
                "That is a classic risk-off clue."
            )

        if oil >= 2:
            return (
                "Oil rising more than 2% can signal energy, supply, inflation, or geopolitical risk. "
                "Check oil together with VIX and S&P futures."
            )

        if bitcoin >= 2:
            return (
                "Bitcoin can move because of crypto-specific catalysts. If Bitcoin jumps while "
                "stocks are flat, ask whether it is a crypto story instead of a whole-market story."
            )

        return (
            "Do not let one indicator decide the whole story. Read S&P futures, Nasdaq futures, "
            "VIX, oil, dollar, rates, and Bitcoin together."
        )

    def _reminder(self, score):
        if score <= 40:
            return "Do not panic. Confirm the move with VIX, oil, and S&P futures before reacting."

        if score >= 60:
            return "Do not chase green candles. Look for confirmation and avoid emotional entries."

        return "Mixed markets are observation days. Let the market show direction first."
