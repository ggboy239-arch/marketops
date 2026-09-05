class RiskEngine:

    def calculate(
        self,
        spy,
        qqq,
        vix,
        oil,
        btc,
        dxy,
        us10y
    ):

        score = 50

        reasons = []

        # -----------------------
        # Market
        # -----------------------

        if spy > 0:
            score += 10
            reasons.append("📈 Stocks Rising")
        else:
            score -= 10
            reasons.append("📉 Stocks Falling")

        # -----------------------

        if qqq > 0:
            score += 10
            reasons.append("🤖 Tech Leading")
        else:
            score -= 10
            reasons.append("🤖 Tech Weak")

        # -----------------------

        if vix < 0:
            score += 20
            reasons.append("😌 Fear Falling")
        else:
            score -= 20
            reasons.append("😨 Fear Rising")

        # -----------------------

        if btc > 0:
            score += 5
            reasons.append("₿ Crypto Strong")
        else:
            score -= 5
            reasons.append("₿ Crypto Weak")

        # -----------------------

        if oil > 2:
            score -= 5
            reasons.append("🛢 Oil Surging")

        # -----------------------

        if score >= 70:
            mood = "🟢 Risk-On"

        elif score <= 30:
            mood = "🔴 Risk-Off"

        else:
            mood = "🟡 Mixed"

        return {
            "score": score,
            "mood": mood,
            "reasons": reasons
        }