class RiskEngine:

    def calculate(
        self,
        spy,
        qqq,
        vix,
        oil,
        btc,
        dxy,
        us10y,
    ):
        score = 50
        positive_reasons = []
        negative_reasons = []
        watch_items = []

        if spy >= 0.25:
            score += 12
            positive_reasons.append("📈 Stocks rising")
        elif spy <= -0.25:
            score -= 12
            negative_reasons.append("📉 Stocks falling")
        else:
            watch_items.append("🇺🇸 Market mostly flat")

        if qqq > spy + 0.20 and qqq > 0:
            score += 10
            positive_reasons.append("🤖 Tech leading")
        elif qqq < spy - 0.20 and qqq < 0:
            score -= 8
            negative_reasons.append("🤖 Tech weak")
        else:
            watch_items.append("🤖 Tech not clearly leading")

        if vix <= -2:
            score += 20
            positive_reasons.append("😌 Fear falling")
        elif vix >= 5:
            score -= 25
            negative_reasons.append("😨 Fear rising fast")
        elif vix > 0:
            score -= 10
            negative_reasons.append("😟 Fear slightly higher")
        else:
            watch_items.append("😨 Fear mostly calm")

        if oil >= 2:
            score -= 8
            negative_reasons.append("🛢 Oil rising strongly")
        elif oil <= -1:
            score += 5
            positive_reasons.append("🛢 Oil easing")

        if btc >= 1:
            score += 5
            positive_reasons.append("₿ Bitcoin strong")
        elif btc <= -1:
            score -= 5
            negative_reasons.append("₿ Bitcoin weak")

        if dxy >= 0.40:
            score -= 5
            negative_reasons.append("💵 Dollar stronger")
        elif dxy <= -0.30:
            score += 3
            positive_reasons.append("💵 Dollar weaker")

        if us10y >= 1:
            score -= 4
            negative_reasons.append("🏦 Yields rising")
        elif us10y <= -1:
            score += 4
            positive_reasons.append("🏦 Yields easing")

        score = max(0, min(100, round(score)))

        if score >= 75:
            mood = "🟢 Strong Risk-On"
        elif score >= 60:
            mood = "🟢 Slight Risk-On"
        elif score > 40:
            mood = "🟡 Mixed / Wait-and-See"
        elif score > 25:
            mood = "🔴 Risk-Off"
        else:
            mood = "🔴 Heavy Risk-Off"

        confidence = self._confidence(score)

        reasons = positive_reasons + negative_reasons

        if not reasons:
            reasons = watch_items or ["Market signals are mixed"]

        return {
            "score": score,
            "mood": mood,
            "confidence": confidence,
            "reasons": reasons,
            "positive_reasons": positive_reasons,
            "negative_reasons": negative_reasons,
            "watch_items": watch_items,
        }

    def _confidence(self, score):
        distance_from_neutral = abs(score - 50)

        if distance_from_neutral >= 35:
            return "★★★★★"

        if distance_from_neutral >= 25:
            return "★★★★☆"

        if distance_from_neutral >= 15:
            return "★★★☆☆"

        return "★★☆☆☆"
