import asyncio

import discord
from discord.ext import commands

from market.market_service import MarketService


VERSION = "MarketOps v2.0"


class Learn(commands.Cog):
    """Simple market learning command.

    Plain English: this command turns the dashboard into a short lesson so the
    user learns why the bot is saying risk-on, risk-off, or mixed.
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

        embed = discord.Embed(
            title="🎓 MarketOps Daily Learning Report",
            description="A quick lesson based on today's dashboard.",
            color=self._risk_color(score),
        )

        embed.add_field(
            name="Today's Market Mood",
            value=f'**{mood}**\nScore: **{score}/100**\nConfidence: {dashboard.get("confidence", "Unknown")}',
            inline=False,
        )

        embed.add_field(
            name="What This Means",
            value=self._explain_mood(score),
            inline=False,
        )

        reasons = dashboard.get("reasons", [])
        reason_text = "\n".join(f"• {reason}" for reason in reasons[:5]) if reasons else "No clear reason yet."
        embed.add_field(name="Why MarketOps Thinks That", value=reason_text, inline=False)

        embed.add_field(
            name="What To Check Next",
            value=(
                f'• Leader: {dashboard.get("leader", "Unknown")}\n'
                f'• Weakest: {dashboard.get("loser", "Unknown")}\n'
                f'• Warning signal: {dashboard.get("warning_signal", "Unknown")}\n'
                f'• Oil/geo: {dashboard.get("energy_signal", "Unknown")}\n'
                f'• Crypto: {dashboard.get("crypto_signal", "Unknown")}\n'
                "• Then check whether fresh headlines confirm or disagree with the move."
            ),
            inline=False,
        )

        embed.add_field(
            name="Mini Lesson",
            value=(
                "Do not trade from one signal. Build a stack:\n"
                "1) Futures direction\n"
                "2) VIX/fear direction\n"
                "3) Oil/rates/dollar pressure\n"
                "4) Fresh headlines\n"
                "5) Price + volume confirmation"
            ),
            inline=False,
        )

        embed.set_footer(text=f'Updated {dashboard.get("updated", "Unknown")} • {VERSION}')
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
