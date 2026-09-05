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
        description="View today's market dashboard."
    )
    async def market(self, interaction: discord.Interaction):

        dashboard = self.market.get_dashboard()

        embed = discord.Embed(
            title="📊 Market Dashboard",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Risk",
            value=dashboard["risk"],
            inline=False
        )

        embed.add_field(
            name="Today's Theme",
            value=dashboard["theme"],
            inline=False
        )

        embed.add_field(
            name="🇺🇸 ES",
            value=dashboard["es"],
            inline=True
        )

        embed.add_field(
            name="🤖 NQ",
            value=dashboard["nq"],
            inline=True
        )

        embed.add_field(
            name="😨 VIX",
            value=dashboard["vix"],
            inline=True
        )

        embed.add_field(
            name="🛢 Oil",
            value=dashboard["oil"],
            inline=True
        )

        embed.add_field(
            name="₿ Bitcoin",
            value=dashboard["btc"],
            inline=True
        )

        embed.add_field(
            name="💵 Dollar",
            value=dashboard["dxy"],
            inline=True
        )

        embed.add_field(
            name="🏦 US10Y",
            value=dashboard["us10y"],
            inline=True
        )

        embed.add_field(
            name="🏆 Leader",
            value=dashboard["leader"],
            inline=True
        )

        embed.add_field(
            name="📉 Weakest",
            value=dashboard["loser"],
            inline=True
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Market(bot))