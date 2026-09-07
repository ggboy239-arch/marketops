import asyncio

import discord
from discord.ext import commands

from market.market_service import MarketService


VERSION = "MarketOps v2.4.4"


class Learn(commands.Cog):
    """Market learning commands.

    Plain English: this command turns the live dashboard into a short lesson.
    The lesson changes based on the current market setup instead of repeating
    the same generic text every time.
    """

    def __init__(self, bot):
        self.bot = bot
        self.market = MarketService()

    @commands.command(name="learn")
    async def learn_prefix(self, ctx):
        try:
            dashboard = await asyncio.to_thread(self.market.get_dashboard)
            await ctx.send(embed=self._build_learning_embed(dashboard))
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
            title="🎓 MarketOps Daily Learning Report",
            description="A quick lesson based on the current dashboard setup.",
            color=self._risk_color(score),
        )

        embed.add_field(
            name="Today's Market Mood",
            value=f'**{mood}**\nScore: **{score}/100**\nConfidence: {dashboard.get("confidence", "Unknown")}',
            inline=False,
        )

        embed.add_field(
            name="What This Means Right Now",
            value=self._explain_mood(score),
            inline=False,
        )

        reasons = dashboard.get("reasons", [])
        reason_text = "\n".join(f"• {self._clean_market_text(reason)}" for reason in reasons[:5]) if reasons else "No clear reason yet."
        embed.add_field(name="Why MarketOps Thinks That", value=reason_text, inline=False)

        embed.add_field(
            name="What To Check Next",
            value=(
                f'• Leader: {self._clean_market_text(dashboard.get("leader", "Unknown"))}\n'
                f'• Weakest: {self._clean_market_text(dashboard.get("loser", "Unknown"))}\n'
                f'• Warning signal: {self._clean_market_text(dashboard.get("warning_signal", "Unknown"))}\n'
                f'• Oil/geo: {self._clean_market_text(dashboard.get("energy_signal", "Unknown"))}\n'
                f'• Crypto: {self._clean_market_text(dashboard.get("crypto_signal", "Unknown"))}\n'
                "• Then check whether fresh headlines confirm or disagree with the move."
            ),
            inline=False,
        )

        embed.add_field(
            name=lesson["title"],
            value=lesson["lesson"],
            inline=False,
        )

        embed.add_field(
            name="Today's Practice Question",
            value=lesson["question"],
            inline=False,
        )

        embed.set_footer(text=f'Updated {dashboard.get("updated", "Unknown")} PT • {VERSION}')
        return embed

    def _build_playbook_embed(self):
        embed = discord.Embed(
            title="📘 MarketOps Quick Playbook",
            description="Use this when you are trying to understand the market fast.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Morning Order",
            value="`!brief` → `!watchlist` → `!alerts` → `!learn`",
            inline=False,
        )
        embed.add_field(
            name="Risk-On Clues",
            value="S&P/Nasdaq up, VIX down, BTC up, dollar/rates calm, good tech breadth.",
            inline=False,
        )
        embed.add_field(
            name="Risk-Off Clues",
            value="S&P/Nasdaq down, VIX up, oil shock, rates spike, dollar strong, bad geopolitics.",
            inline=False,
        )
        embed.add_field(
            name="Rule",
            value="Treat alerts as leads. Confirm the source, chart reaction, and volume before acting.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _dynamic_lesson(self, dashboard):
        score = dashboard.get("score", 50)
        text = " ".join(
            str(dashboard.get(key, ""))
            for key in ["leader", "loser", "warning_signal", "energy_signal", "crypto_signal", "theme"]
        ).lower()
        reasons = " ".join(str(item) for item in dashboard.get("reasons", [])).lower()
        combined = f"{text} {reasons}"

        if "fear" in combined or "vix" in combined:
            return {
                "title": "Mini Lesson: Fear / VIX Check",
                "lesson": (
                    "When VIX or fear rises, the market is saying traders are buying protection. "
                    "That does not always mean a crash, but it means you should avoid chasing entries. "
                    "Look for confirmation: are S&P/Nasdaq also falling, or is fear rising by itself?"
                ),
                "question": "Is fear confirming the move, or is it only a small warning while stocks hold up?",
            }

        if "oil" in combined or "energy" in combined or "geo" in combined:
            return {
                "title": "Mini Lesson: Oil / Geopolitics Pressure",
                "lesson": (
                    "Oil moving hard can affect inflation expectations, energy stocks, airlines, consumers, "
                    "and geopolitics. If oil is rising with war or OPEC headlines, treat it as a risk signal. "
                    "Check whether XOM/CVX are moving with oil or whether the whole market is getting nervous."
                ),
                "question": "Is oil helping only energy stocks, or is it creating pressure for the whole market?",
            }

        if "bitcoin" in combined or "crypto" in combined or "btc" in combined:
            return {
                "title": "Mini Lesson: Crypto Risk Appetite",
                "lesson": (
                    "Bitcoin can act like a risk-appetite clue. If BTC is strong while Nasdaq is strong, traders may be comfortable taking risk. "
                    "If BTC drops while VIX rises, caution is usually higher. Do not use BTC alone; compare it with tech, VIX, and headlines."
                ),
                "question": "Is Bitcoin agreeing with stocks, or is it warning that risk appetite is fading?",
            }

        if "nasdaq" in combined or "tech" in combined or "ai" in combined:
            return {
                "title": "Mini Lesson: Tech / AI Leadership",
                "lesson": (
                    "When Nasdaq or AI names lead, the market may be leaning into growth and risk. "
                    "But leadership can be narrow. Check whether NVDA/AMD/QQQ are strong together, "
                    "and whether SPY is also following or lagging behind."
                ),
                "question": "Is tech leadership broad and healthy, or is only one big name carrying the market?",
            }

        if score >= 55:
            return {
                "title": "Mini Lesson: Risk-On Confirmation",
                "lesson": (
                    "Risk-on means buyers are more willing to take risk. The cleanest version is: futures up, VIX down, BTC up, "
                    "rates calm, and positive headlines. If only one piece is bullish, wait for more confirmation."
                ),
                "question": "Which signals agree with risk-on, and which signal is the weak spot?",
            }

        if score <= 45:
            return {
                "title": "Mini Lesson: Risk-Off Protection",
                "lesson": (
                    "Risk-off means traders are more cautious. Your job is not to guess the bottom. "
                    "Your job is to identify what caused the caution: VIX, rates, oil, geopolitics, or weak tech. "
                    "Then wait to see if price and headlines stabilize."
                ),
                "question": "What is the main reason the market is cautious right now?",
            }

        return {
            "title": "Mini Lesson: Mixed Market Patience",
            "lesson": (
                "Mixed markets are hard because signals disagree. That is usually a wait-and-confirm environment. "
                "Build a stack before acting: futures direction, VIX, oil/rates/dollar, fresh headlines, then price and volume."
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

    def _explain_mood(self, score):
        if score >= 70:
            return "Strong risk-on: buyers are likely more comfortable taking risk, but still avoid chasing without confirmation."
        if score >= 55:
            return "Mild risk-on: the market leans positive, but one bad headline can still flip the mood."
        if score >= 45:
            return "Mixed: signals disagree. This is usually a wait-and-confirm environment."
        if score >= 30:
            return "Mild risk-off: caution is showing. Watch VIX, rates, oil, and whether tech leadership holds."
        return "Strong risk-off: fear is elevated. Protect capital and avoid guessing bottoms without confirmation."

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
