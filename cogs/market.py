import discord
from discord import app_commands
from discord.ext import commands

from market.market_service import MarketService


class Market(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.market = MarketService()

    @app_commands.command(
        name="market",
        description="View today's MarketOps dashboard.",
    )
    async def market(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            dashboard = self.market.get_dashboard()
            embed = self._build_market_embed(dashboard)
            await interaction.followup.send(embed=embed)

        except Exception as error:
            print(f"❌ /market error: {error}")

            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the dashboard. "
                "Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="market")
    async def market_prefix(self, ctx):
        """Desktop/web fallback command.

        If Discord desktop/web refuses to show bot slash commands, type !market.
        This uses the same dashboard as /market but does not rely on Discord's
        slash-command picker.
        """
        try:
            dashboard = self.market.get_dashboard()
            embed = self._build_market_embed(dashboard)
            await ctx.send(embed=embed)

        except Exception as error:
            print(f"❌ !market error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the dashboard. "
                "Check the terminal for the error."
            )

    def _build_market_embed(self, dashboard):
        embed = discord.Embed(
            title="🌅 MarketOps Dashboard",
            description="What kind of market are we walking into?",
            color=self._risk_color(dashboard["score"]),
        )

        embed.add_field(
            name="🧠 Market Mood",
            value=(
                f'**{dashboard["risk"]}**\n'
                f'Score: **{dashboard["score"]}/100**\n'
                f'Confidence: {dashboard["confidence"]}'
            ),
            inline=False,
        )

        embed.add_field(
            name="Why?",
            value=self._format_reasons(dashboard["reasons"]),
            inline=False,
        )

        embed.add_field(
            name="🇺🇸 S&P Futures",
            value=dashboard["assets"]["market"],
            inline=True,
        )

        embed.add_field(
            name="🤖 Nasdaq Futures",
            value=dashboard["assets"]["tech"],
            inline=True,
        )

        embed.add_field(
            name="😨 Fear / VIX",
            value=dashboard["assets"]["fear"],
            inline=True,
        )

        embed.add_field(
            name="🛢 Oil",
            value=dashboard["assets"]["oil"],
            inline=True,
        )

        embed.add_field(
            name="💵 Dollar",
            value=dashboard["assets"]["dollar"],
            inline=True,
        )

        embed.add_field(
            name="🏦 US10Y",
            value=dashboard["assets"]["rates"],
            inline=True,
        )

        embed.add_field(
            name="₿ Bitcoin",
            value=dashboard["assets"]["bitcoin"],
            inline=True,
        )

        embed.add_field(
            name="📰 Today's Theme",
            value=dashboard["theme"],
            inline=True,
        )

        embed.add_field(
            name="🏆 Equity Leader",
            value=dashboard["leader"],
            inline=True,
        )

        embed.add_field(
            name="📉 Equity Weakest",
            value=dashboard["loser"],
            inline=True,
        )

        embed.add_field(
            name="⚠️ Biggest Warning Signal",
            value=dashboard["warning_signal"],
            inline=True,
        )

        embed.add_field(
            name="🛢 Energy / Geo Signal",
            value=dashboard["energy_signal"],
            inline=True,
        )

        embed.add_field(
            name="₿ Crypto Signal",
            value=dashboard["crypto_signal"],
            inline=True,
        )

        embed.add_field(
            name="🌙 After-Market Note",
            value=dashboard["after_market_note"],
            inline=False,
        )

        embed.set_footer(
            text=f'Updated {dashboard["updated"]} • MarketOps v0.2.4'
        )

        return embed

    def _format_reasons(self, reasons):
        if not reasons:
            return "No clear reason yet."

        return "\n".join(f"• {reason}" for reason in reasons[:5])

    def _risk_color(self, score):
        if score >= 60:
            return discord.Color.green()

        if score <= 30:
            return discord.Color.red()

        if score <= 45:
            return discord.Color.orange()

        return discord.Color.gold()


async def setup(bot):
    await bot.add_cog(Market(bot))
