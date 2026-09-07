import asyncio

import discord
from discord.ext import commands

from market.market_service import MarketService


VERSION = "MarketOps v2.9"


class Learn(commands.Cog):
    """Market learning commands.

    Plain English: this turns the live dashboard into a real lesson. It explains
    the signal, why it matters, what to compare, and what question to ask next.
    """

    def __init__(self, bot):
        self.bot = bot
        self.market = MarketService()

    @commands.command(name="learn", aliases=["lesson", "marketlesson"])
    async def learn_prefix(self, ctx, *, topic: str = ""):
        try:
            dashboard = await asyncio.to_thread(self.market.get_dashboard)
            topic = (topic or "").strip().lower()
            if topic:
                embed = self._topic_lesson_embed(topic, dashboard)
            else:
                embed = self._build_learning_embed(dashboard)
            await ctx.send(embed=embed)
        except Exception as error:
            print(f"❌ !learn error: {error}")
            await ctx.send("⚠️ MarketOps had trouble building the learning report. Check the terminal for the error.")

    @commands.command(name="playbook")
    async def playbook_prefix(self, ctx):
        await ctx.send(embed=self._build_playbook_embed())

    def _build_learning_embed(self, dashboard):
        score = dashboard.get("score", 50)
        mood = dashboard.get("risk", "Mixed")
        lesson = self._dynamic_lesson(dashboard)

        embed = discord.Embed(
            title="🎓 MarketOps Learning Session",
            description="Price action + risk signals + news context. This is how to read the market, not just collect headlines.",
            color=self._risk_color(score),
        )

        embed.add_field(
            name="1) Fast Read",
            value=(
                f"Mood: **{mood}**\n"
                f"Score: **{score}/100**\n"
                f"Theme: **{dashboard.get('theme', 'Unknown')}**\n"
                f"Confidence: **{dashboard.get('confidence', 'Unknown')}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="2) What Each Signal Means",
            value=(
                "**S&P/ES** = broad market direction.\n"
                "**Nasdaq/NQ** = tech/growth risk appetite.\n"
                "**VIX** = fear/protection demand.\n"
                "**Oil** = inflation/geopolitical pressure.\n"
                "**Gold** = safety bid / fear / dollar-rate reaction.\n"
                "**DXY + 10Y** = dollar and rates pressure.\n"
                "**BTC** = speculative risk appetite."
            ),
            inline=False,
        )

        embed.add_field(
            name="3) What MarketOps Sees",
            value=(
                f"Leader: {self._clean_market_text(dashboard.get('leader', 'Unknown'))}\n"
                f"Weakest: {self._clean_market_text(dashboard.get('loser', 'Unknown'))}\n"
                f"Warning: {self._clean_market_text(dashboard.get('warning_signal', 'Unknown'))}\n"
                f"Oil/Geo: {self._clean_market_text(dashboard.get('energy_signal', 'Unknown'))}\n"
                f"Gold/Safety: {self._clean_market_text(dashboard.get('gold_signal', 'Unknown'))}\n"
                f"Crypto: {self._clean_market_text(dashboard.get('crypto_signal', 'Unknown'))}"
            ),
            inline=False,
        )

        reasons = dashboard.get("reasons", [])
        reason_text = "\n".join(f"• {self._clean_market_text(reason)}" for reason in reasons[:5]) if reasons else "No clear reason yet."
        embed.add_field(name="4) Reason Stack", value=reason_text, inline=False)

        embed.add_field(name=lesson["title"], value=lesson["lesson"], inline=False)

        embed.add_field(
            name="6) Step-By-Step Process",
            value=(
                "1. Run `!pulse` to see what is moving right now.\n"
                "2. Run `!chart SPY 1d` or `!chart QQQ 1d` to see candles.\n"
                "3. Check if VIX, gold, dollar, or 10Y are warning you.\n"
                "4. Run `!news post` or read routed news to find a reason.\n"
                "5. Decide: continuation, reversal, or wait for confirmation."
            ),
            inline=False,
        )

        embed.add_field(
            name="7) Practice Answer Format",
            value=(
                "Write this in your head: `Market is ___ because ___; warning is ___; chart confirms/rejects because ___; next I watch ___.`\n\n"
                f"Practice question: **{lesson['question']}**"
            ),
            inline=False,
        )

        embed.set_footer(text=f'Updated {dashboard.get("updated", "Unknown")} PT • {VERSION}')
        return embed

    def _topic_lesson_embed(self, topic, dashboard):
        lessons = {
            "candles": self._candles_lesson(),
            "candle": self._candles_lesson(),
            "ohlc": self._candles_lesson(),
            "risk": self._risk_lesson(),
            "risk-on": self._risk_lesson(),
            "riskoff": self._risk_lesson(),
            "risk-off": self._risk_lesson(),
            "vix": self._vix_lesson(),
            "fear": self._vix_lesson(),
            "rates": self._rates_lesson(),
            "10y": self._rates_lesson(),
            "gold": self._gold_lesson(),
            "news": self._news_lesson(),
        }
        lesson = lessons.get(topic, self._unknown_topic_lesson(topic))
        embed = discord.Embed(title=lesson["title"], description=lesson["description"], color=discord.Color.gold())
        for name, value in lesson["fields"]:
            embed.add_field(name=name, value=value, inline=False)
        embed.add_field(
            name="Live Practice",
            value=f"Current MarketOps mood: **{dashboard.get('risk', 'Unknown')}**. Now compare this lesson to `!pulse` and `!chart SPY 1d`.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _build_playbook_embed(self):
        embed = discord.Embed(
            title="📘 MarketOps Full Playbook",
            description="Use this when you are trying to understand the market fast without guessing.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Fast Flow", value="`!pulse` → `!chart SPY 1d` → `!chart QQQ 1d` → `!news post` → `!learn`", inline=False)
        embed.add_field(name="Risk-On Clues", value="S&P/Nasdaq up, VIX down, BTC up, dollar/rates calm, good tech breadth, no bad headline pressure.", inline=False)
        embed.add_field(name="Risk-Off Clues", value="S&P/Nasdaq down, VIX up, oil/gold spike, rates/dollar strong, weak tech, bad geopolitics or Fed pressure.", inline=False)
        embed.add_field(name="Candlestick Rule", value="Green body = buyers won that candle. Red body = sellers won. Big wick = rejection. Big body = control. One candle alone is not enough.", inline=False)
        embed.add_field(name="News Rule", value="News explains why price may move, but price action confirms whether traders care. Always compare headline + chart + volume.", inline=False)
        embed.add_field(name="Learning Topics", value="`!learn candles`, `!learn risk`, `!learn vix`, `!learn rates`, `!learn gold`, `!learn news`", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _candles_lesson(self):
        return {
            "title": "🕯️ Lesson: Candlesticks / OHLC",
            "description": "A candle is a time box. A 5-minute candle shows what happened during 5 minutes. A daily candle shows what happened during one full trading day.",
            "fields": [
                ("Open / High / Low / Close", "**Open** = first price. **High** = highest price. **Low** = lowest price. **Close** = last price."),
                ("Body", "The thick body is the distance between open and close. Green body means close > open. Red body means close < open."),
                ("Wicks", "Upper wick means price went up but got rejected. Lower wick means price went down but buyers defended it."),
                ("How To Read", "Ask: Who controlled the candle? Did the next candle confirm it? Is it near support/resistance? Is news backing the move?"),
            ],
        }

    def _risk_lesson(self):
        return {
            "title": "📈 Lesson: Risk-On / Risk-Off",
            "description": "Risk-on means traders are willing to buy growth/speculative assets. Risk-off means traders are protecting capital.",
            "fields": [
                ("Risk-On", "Usually S&P/Nasdaq up, VIX down, BTC up, rates calm, dollar calm, strong tech leadership."),
                ("Risk-Off", "Usually stocks down, VIX up, gold/oil/dollar/rates moving defensively, bad news driving caution."),
                ("Common Trap", "One green candle does not equal risk-on. You want multiple signals agreeing."),
            ],
        }

    def _vix_lesson(self):
        return {
            "title": "😨 Lesson: VIX / Fear",
            "description": "VIX is a fear/protection signal. It rises when traders pay more for protection.",
            "fields": [
                ("Why It Matters", "If VIX rises while stocks fall, caution is real. If VIX rises while stocks hold up, it may be an early warning."),
                ("How To Use", "Compare VIX to S&P/Nasdaq candles. VIX up + red candles = risk-off confirmation."),
                ("Common Trap", "VIX can spike and fade. Do not panic from VIX alone."),
            ],
        }

    def _rates_lesson(self):
        return {
            "title": "🏦 Lesson: Rates / 10Y / DXY",
            "description": "Rates and the dollar can pressure stocks, especially tech and growth names.",
            "fields": [
                ("10Y", "When 10Y yield jumps, growth stocks can struggle because future earnings get discounted harder."),
                ("DXY", "A strong dollar can pressure commodities, multinational companies, and risk appetite."),
                ("How To Use", "If QQQ is red and 10Y/DXY are green, rates/dollar may be part of the reason."),
            ],
        }

    def _gold_lesson(self):
        return {
            "title": "🥇 Lesson: Gold",
            "description": "Gold is often watched as a safety, inflation, dollar, and rate-sensitive asset.",
            "fields": [
                ("Safety Bid", "If stocks fall while gold rises, traders may be moving defensive."),
                ("Rates/Dollar Link", "Gold can struggle when real yields or the dollar rise, but it can rise on fear/inflation/geopolitical stress."),
                ("How To Use", "Compare gold with VIX, DXY, 10Y, oil, and geopolitics. Gold alone is not enough."),
            ],
        }

    def _news_lesson(self):
        return {
            "title": "📰 Lesson: News vs Price Action",
            "description": "News gives a reason. Price action tells you whether traders actually care.",
            "fields": [
                ("Step 1", "Read the headline and identify the affected market: SPY, QQQ, oil, gold, yields, BTC, defense, energy, tech."),
                ("Step 2", "Check candles. Did price break higher/lower, reject, or ignore the headline?"),
                ("Step 3", "Check follow-through. A first move can be fake; confirmation matters."),
            ],
        }

    def _unknown_topic_lesson(self, topic):
        return {
            "title": "🎓 MarketOps Learning Topics",
            "description": f"I do not have a detailed lesson for `{topic}` yet.",
            "fields": [
                ("Available", "Use: `!learn candles`, `!learn risk`, `!learn vix`, `!learn rates`, `!learn gold`, `!learn news`."),
            ],
        }

    def _dynamic_lesson(self, dashboard):
        score = dashboard.get("score", 50)
        text = " ".join(
            str(dashboard.get(key, ""))
            for key in ["leader", "loser", "warning_signal", "energy_signal", "gold_signal", "crypto_signal", "theme"]
        ).lower()
        reasons = " ".join(str(item) for item in dashboard.get("reasons", [])).lower()
        combined = f"{text} {reasons}"

        if "gold" in combined:
            return {
                "title": "5) Mini Lesson: Gold / Safety Check",
                "lesson": (
                    "Gold rising can mean safety demand, inflation concern, rate expectations, or dollar weakness. "
                    "Do not read gold alone. Compare it with VIX, 10Y, DXY, oil, and stock candles. "
                    "Gold up while stocks are red can be defensive. Gold up while stocks are green can mean inflation or dollar pressure."
                ),
                "question": "Is gold acting like safety demand, inflation pressure, or just moving with the dollar/rates?",
            }

        if "fear" in combined or "vix" in combined:
            return {
                "title": "5) Mini Lesson: Fear / VIX Check",
                "lesson": (
                    "When VIX rises, traders are buying protection. That does not always mean crash, but it says caution is increasing. "
                    "Your job is to compare: are S&P/Nasdaq candles also red, or is VIX rising by itself? If VIX rises and QQQ/ES break lower, that is stronger risk-off confirmation."
                ),
                "question": "Is fear confirming the stock move, or is it only a warning while stocks hold up?",
            }

        if "oil" in combined or "energy" in combined or "geo" in combined:
            return {
                "title": "5) Mini Lesson: Oil / Geopolitics Pressure",
                "lesson": (
                    "Oil can affect inflation, airlines, consumers, energy stocks, and geopolitics. If oil rises on war/OPEC/sanctions, it can pressure risk appetite. "
                    "Check whether XOM/CVX move with oil and whether SPY/QQQ get nervous."
                ),
                "question": "Is oil helping only energy stocks, or creating pressure for the whole market?",
            }

        if "bitcoin" in combined or "crypto" in combined or "btc" in combined:
            return {
                "title": "5) Mini Lesson: Crypto Risk Appetite",
                "lesson": (
                    "Bitcoin can act like a speculative risk clue. If BTC and Nasdaq are both strong, traders may be comfortable taking risk. "
                    "If BTC drops while VIX rises, caution is usually higher. Compare BTC with tech, VIX, and headlines."
                ),
                "question": "Is Bitcoin agreeing with stocks, or warning that risk appetite is fading?",
            }

        if "nasdaq" in combined or "tech" in combined or "ai" in combined:
            return {
                "title": "5) Mini Lesson: Tech / AI Leadership",
                "lesson": (
                    "When Nasdaq or AI names lead, the market may be leaning into growth and risk. But leadership can be narrow. "
                    "Check whether NVDA/AMD/QQQ are strong together and whether SPY is also following or lagging."
                ),
                "question": "Is tech leadership broad and healthy, or is one mega-cap carrying the market?",
            }

        if score >= 55:
            return {
                "title": "5) Mini Lesson: Risk-On Confirmation",
                "lesson": (
                    "Risk-on means buyers are more willing to take risk. The clean version is futures up, VIX down, BTC up, rates calm, and positive headlines. "
                    "If only one piece is bullish, wait for more confirmation."
                ),
                "question": "Which signals agree with risk-on, and which signal is the weak spot?",
            }

        if score <= 45:
            return {
                "title": "5) Mini Lesson: Risk-Off Protection",
                "lesson": (
                    "Risk-off means traders are cautious. Your job is not to guess the bottom. Identify the cause: VIX, rates, oil, gold, geopolitics, or weak tech. "
                    "Then wait to see if price and headlines stabilize."
                ),
                "question": "What is the main reason the market is cautious right now?",
            }

        return {
            "title": "5) Mini Lesson: Mixed Market Patience",
            "lesson": (
                "Mixed markets are hard because signals disagree. Build a stack before acting: futures direction, VIX, oil/gold/rates/dollar, fresh headlines, then price/volume confirmation."
            ),
            "question": "Which two signals are disagreeing the most right now?",
        }

    def _clean_market_text(self, value):
        text = str(value)
        lower_text = text.lower()

        if "nan" not in lower_text and "inf" not in lower_text:
            return text

        cleaned = text.replace("+nan%", "no fresh % data")
        cleaned = cleaned.replace("-nan%", "no fresh % data")
        cleaned = cleaned.replace("nan%", "no fresh % data")
        cleaned = cleaned.replace("+inf%", "no fresh % data")
        cleaned = cleaned.replace("-inf%", "no fresh % data")
        cleaned = cleaned.replace("inf%", "no fresh % data")
        return cleaned

    def _risk_color(self, score):
        if score >= 60:
            return discord.Color.green()
        if score <= 30:
            return discord.Color.red()
        if score <= 45:
            return discord.Color.orange()
        return discord.Color.gold()


async def setup(bot):
    await bot.add_cog(Learn(bot))
